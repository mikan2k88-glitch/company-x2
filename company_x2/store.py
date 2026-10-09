"""Durable sandbox orders; transactions claim each job before processing."""
import hashlib
import json
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from .data_services import require_service


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            pragma journal_mode=WAL;
            create table if not exists orders (
                id text primary key, token_hash text not null, request_key text unique not null,
                request_hash text not null, status text not null, input text not null,
                result text, error text, created_at text not null default CURRENT_TIMESTAMP,
                updated_at text not null default CURRENT_TIMESTAMP
            );
            create table if not exists events (
                id integer primary key, order_id text not null references orders(id),
                kind text not null, created_at text not null default CURRENT_TIMESTAMP
            );
            create table if not exists opportunities (
                source text not null, external_id text not null, data text not null,
                decision text not null, reason text not null,
                created_at text not null default CURRENT_TIMESTAMP,
                primary key(source, external_id)
            );
            create table if not exists scout_state (
                id integer primary key check(id=1), status text not null default 'waiting',
                lease text, lease_until real, next_run_at real not null default 0,
                last_attempt_at real, last_success_at real, error text, report text
            );
            insert or ignore into scout_state(id) values(1);
            ''')
            if 'service_key' not in {r['name'] for r in db.execute('pragma table_info(orders)')}:
                db.execute("alter table orders add column service_key text not null default 'csv_exact_dedup'")
        from .company_store import initialize
        initialize(self)
        from .support_store import SCHEMA as SUPPORT_SCHEMA
        with self.connect() as db:
            db.executescript(SUPPORT_SCHEMA)
        from .case_store import SCHEMA as CASE_SCHEMA
        with self.connect() as db:db.executescript(CASE_SCHEMA)
        from .automation_store import SCHEMA as AUTOMATION_SCHEMA
        with self.connect() as db:db.executescript(AUTOMATION_SCHEMA)
        from .outreach_store import SCHEMA as OUTREACH_SCHEMA
        with self.connect() as db:db.executescript(OUTREACH_SCHEMA)

    def outreach_rpc(self, action, payload=None):
        from .outreach_store import rpc
        return rpc(self,action,payload or {})

    def automation_rpc(self, action, payload=None):
        from .automation_store import rpc
        return rpc(self,action,payload or {})

    def support_rpc(self, action, payload=None):
        from .support_store import rpc
        return rpc(self, action, payload or {})

    def case_rpc(self, action, payload=None):
        from .case_store import rpc
        return rpc(self, action, payload or {})

    def company_rpc(self, action, payload=None):
        from .company_store import rpc
        return rpc(self, action, payload or {})

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('pragma foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def digest(text):
        return hashlib.sha256(text.encode()).hexdigest()

    @staticmethod
    def request_digest(text, service_key):
        return Store.digest(text if service_key == 'csv_exact_dedup' else service_key + '\0' + text)

    def services_ready(self):
        return True

    def submit(self, text, request_key, token, service_key='csv_exact_dedup'):
        require_service(service_key)
        if not 16 <= len(request_key) <= 128 or not 32 <= len(token) <= 128:
            raise ValueError('Invalid request key or access token')
        request_hash = self.request_digest(text, service_key)
        token_hash = self.digest(token)
        with self.connect() as db:
            db.execute('begin immediate')
            existing = db.execute('select * from orders where request_key=?', (request_key,)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash or existing['token_hash'] != token_hash:
                    raise ValueError('Request key already used for different content or owner')
                return existing['id']
            order_id = secrets.token_urlsafe(18)
            db.execute('insert into orders(id,token_hash,request_key,request_hash,status,input,service_key) values(?,?,?,?,?,?,?)',
                       (order_id, token_hash, request_key, request_hash, 'queued', text, service_key))
            db.execute('insert into events(order_id,kind) values(?,?)', (order_id, 'sandbox_order_received'))
            return order_id

    def claim(self):
        with self.connect() as db:
            db.execute('begin immediate')
            row = db.execute("select id,input,service_key from orders where status='queued' order by created_at,id limit 1").fetchone()
            if not row:
                return None
            db.execute("update orders set status='processing',updated_at=CURRENT_TIMESTAMP where id=?", (row['id'],))
            db.execute('insert into events(order_id,kind) values(?,?)', (row['id'], 'processing_started'))
            return dict(row)

    def finish(self, order_id, *, result=None, error=None, lease=None):
        status = 'failed' if error else 'ready'
        with self.connect() as db:
            db.execute('begin immediate')
            updated = db.execute("update orders set status=?,result=?,error=?,input='',updated_at=CURRENT_TIMESTAMP where id=? and status='processing'",
                                 (status, json.dumps(result) if result is not None else None, error, order_id))
            if updated.rowcount != 1:
                raise ValueError('Order not processing')
            db.execute('insert into events(order_id,kind) values(?,?)', (order_id, status))

    def recover(self):
        # Only call before starting the sole worker. Processing has no external side effects.
        with self.connect() as db:
            db.execute("insert into events(order_id,kind) select id,'restart_requeued' from orders where status='processing'")
            db.execute("update orders set status='queued' where status='processing'")

    def ping(self):
        with self.connect() as db:
            return db.execute('select 1').fetchone()[0] == 1

    def get(self, order_id, token):
        with self.connect() as db:
            row = db.execute('select * from orders where id=?', (order_id,)).fetchone()
            if not row or not secrets.compare_digest(row['token_hash'], self.digest(token)):
                return None
            result = json.loads(row['result']) if row['result'] else None
            events = [dict(e) for e in db.execute('select kind,created_at from events where order_id=? order by id', (order_id,))]
            return {'id': row['id'], 'status': row['status'], 'error': row['error'],
                    'service_key': row['service_key'], 'result': result, 'events': events, 'mode': 'sandbox', 'revenue_jpy': 0}

    def save_opportunity(self, candidate, decision, reason):
        with self.connect() as db:
            db.execute('insert into opportunities(source,external_id,data,decision,reason) values(?,?,?,?,?) '
                       'on conflict(source,external_id) do update set data=excluded.data,decision=excluded.decision,reason=excluded.reason',
                       (candidate['source'], candidate['external_id'], json.dumps(candidate), decision, reason))

    def opportunities(self):
        with self.connect() as db:
            return [{**json.loads(r['data']), 'decision': r['decision'], 'reason': r['reason']}
                    for r in db.execute('select * from opportunities order by created_at desc limit 100')]

    def claim_scan(self):
        now = time.time()
        lease = secrets.token_urlsafe(24)
        with self.connect() as db:
            db.execute('begin immediate')
            changed = db.execute("update scout_state set status='running',lease=?,lease_until=?,last_attempt_at=?,error=null "
                                 'where id=1 and next_run_at<=? and (lease_until is null or lease_until<?)',
                                 (lease, now + 180, now, now, now))
            return lease if changed.rowcount else None

    def finish_scan(self, lease, *, items=None, report=None, error=None, delay=3600):
        now = time.time()
        if error is None and (not isinstance(items, list) or len(items) > 30
                or any(c.get('source') != 'github_public_bounty' or not c.get('external_id', '').isdigit()
                       or c.get('decision') not in ('needs_review', 'blocked', 'rejected') for c in items)):
            raise ValueError('Invalid scout batch')
        with self.connect() as db:
            db.execute('begin immediate')
            row = db.execute('select * from scout_state where id=1').fetchone()
            if not row['lease'] or row['lease'] != lease or row['lease_until'] <= now:
                raise ValueError('Invalid scout lease')
            if error is None:
                db.execute("delete from opportunities where source='github_public_bounty'")
                for c in items:
                    db.execute('insert into opportunities(source,external_id,data,decision,reason) values(?,?,?,?,?)',
                               (c['source'], c['external_id'], json.dumps(c), c['decision'], c['reason']))
                db.execute("update scout_state set status='completed',last_success_at=?,report=?,error=null where id=1",
                           (now, json.dumps(report)))
            else:
                db.execute("update scout_state set status='retry_wait',error=? where id=1", (str(error)[:300],))
            db.execute('update scout_state set lease=null,lease_until=null,next_run_at=? where id=1',
                       (now + max(300, min(86400, delay)),))

    def scan_snapshot(self):
        with self.connect() as db:
            # One read transaction keeps report and current items consistent.
            db.execute('begin')
            row = dict(db.execute('select * from scout_state where id=1').fetchone())
            items = [json.loads(r['data']) for r in db.execute(
                "select data from opportunities where source='github_public_bounty' order by external_id")]
        if row['status'] == 'running' and row['lease_until'] < time.time():
            row['status'] = 'retry_wait'
        for key in ('next_run_at', 'last_attempt_at', 'last_success_at'):
            row[key] = datetime.fromtimestamp(row[key], timezone.utc).isoformat() if row[key] else None
        return {k: row[k] for k in ('status', 'next_run_at', 'last_attempt_at', 'last_success_at', 'error')} | {
            'report': json.loads(row['report']) if row['report'] else None, 'items': items}
