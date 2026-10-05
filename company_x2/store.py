"""Durable sandbox orders; transactions claim each job before processing."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path


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
            ''')

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

    def submit(self, text, request_key, token):
        if not 16 <= len(request_key) <= 128 or not 32 <= len(token) <= 128:
            raise ValueError('Invalid request key or access token')
        request_hash = self.digest(text)
        token_hash = self.digest(token)
        with self.connect() as db:
            db.execute('begin immediate')
            existing = db.execute('select * from orders where request_key=?', (request_key,)).fetchone()
            if existing:
                if existing['request_hash'] != request_hash or existing['token_hash'] != token_hash:
                    raise ValueError('Request key already used for different content or owner')
                return existing['id']
            order_id = secrets.token_urlsafe(18)
            db.execute('insert into orders(id,token_hash,request_key,request_hash,status,input) values(?,?,?,?,?,?)',
                       (order_id, token_hash, request_key, request_hash, 'queued', text))
            db.execute('insert into events(order_id,kind) values(?,?)', (order_id, 'sandbox_order_received'))
            return order_id

    def claim(self):
        with self.connect() as db:
            db.execute('begin immediate')
            row = db.execute("select id,input from orders where status='queued' order by created_at,id limit 1").fetchone()
            if not row:
                return None
            db.execute("update orders set status='processing',updated_at=CURRENT_TIMESTAMP where id=?", (row['id'],))
            db.execute('insert into events(order_id,kind) values(?,?)', (row['id'], 'processing_started'))
            return dict(row)

    def finish(self, order_id, *, result=None, error=None):
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

    def get(self, order_id, token):
        with self.connect() as db:
            row = db.execute('select * from orders where id=?', (order_id,)).fetchone()
            if not row or not secrets.compare_digest(row['token_hash'], self.digest(token)):
                return None
            result = json.loads(row['result']) if row['result'] else None
            events = [dict(e) for e in db.execute('select kind,created_at from events where order_id=? order by id', (order_id,))]
            return {'id': row['id'], 'status': row['status'], 'error': row['error'],
                    'result': result, 'events': events, 'mode': 'sandbox', 'revenue_jpy': 0}

    def save_opportunity(self, candidate, decision, reason):
        with self.connect() as db:
            db.execute('insert into opportunities(source,external_id,data,decision,reason) values(?,?,?,?,?) '
                       'on conflict(source,external_id) do update set data=excluded.data,decision=excluded.decision,reason=excluded.reason',
                       (candidate['source'], candidate['external_id'], json.dumps(candidate), decision, reason))

    def opportunities(self):
        with self.connect() as db:
            return [{**json.loads(r['data']), 'decision': r['decision'], 'reason': r['reason']}
                    for r in db.execute('select * from opportunities order by created_at desc limit 100')]
