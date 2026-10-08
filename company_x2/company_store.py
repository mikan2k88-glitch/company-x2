"""SQLite equivalent of cx2_company. All transitions are atomic."""
import json
import secrets
import re
import time
from . import refund_store

SCHEMA = '''
create table if not exists company_orders (
 id text primary key, request_key text unique not null, request_hash text not null,
 token_hash text not null, plan text not null, source_url text not null, input text not null,
 status text not null, payment_status text not null, session_id text unique, session_url text,
 result text, error text, lease text, lease_until real, attempts integer not null default 0,
 created_at text not null default CURRENT_TIMESTAMP, updated_at text not null default CURRENT_TIMESTAMP
);
create table if not exists company_events (
 id integer primary key, order_id text not null references company_orders(id),
 kind text not null, created_at text not null default CURRENT_TIMESTAMP
);
create table if not exists company_payment_events (
 event_id text primary key, order_id text not null references company_orders(id),
 fingerprint text not null, created_at text not null default CURRENT_TIMESTAMP
);
create table if not exists company_ai_calls (
 request_hash text primary key, month text not null, day text not null,
 reserve integer not null, result text, created_at text not null default CURRENT_TIMESTAMP
);
'''


def initialize(store):
    with store.connect() as db:
        db.executescript(SCHEMA)
        db.executescript(refund_store.SCHEMA)


def validate_submit(p):
    plan = p.get('plan', {})
    if (not isinstance(p.get('input'), str) or len(p['input'].encode()) > 1_000_000
            or not 16 <= len(p.get('request_key', '')) <= 128
            or any(len(p.get(k, '')) != 64 for k in ('request_hash', 'token_hash'))
            or plan.get('payment_mode') not in ('sandbox', 'stripe_test','stripe_live')
            or plan.get('service_key') not in ('csv_exact_dedup', 'csv_trim', 'csv_to_json', 'csv_audit')
            or (plan['payment_mode']=='stripe_live' and (type(plan.get('price_jpy')) is not int or not 50<=plan['price_jpy']<=10000))
            or (plan['payment_mode']!='stripe_live' and plan.get('price_jpy') != (100 if plan['payment_mode'] == 'stripe_test' else 0))
            or plan.get('currency') != 'jpy' or plan.get('terms_version') != ('e19-live-v1' if plan['payment_mode']=='stripe_live' else 'e09-v1')):
        raise ValueError('Invalid company order')


def rpc(store, action, p):
    with store.connect() as db:
        db.execute('begin immediate')
        def event(order, kind):
            db.execute('insert into company_events(order_id,kind) values(?,?)', (order, kind))
        def get_row(owner=True):
            query = 'select * from company_orders where id=?'
            args = [p.get('id')]
            if owner:
                query += ' and token_hash=?'
                args.append(p.get('token_hash'))
            row = db.execute(query, args).fetchone()
            if not row:
                raise ValueError('Transaction not found')
            return row
        if action.startswith('refund_'):
            return refund_store.rpc(db, action, p, event)
        if action == 'live_ping':return {'live_schema_version':19}
        if action == 'ping':
            return {'schema_version': 9}
        if action == 'create':
            validate_submit(p)
            row = db.execute('select * from company_orders where request_key=?', (p['request_key'],)).fetchone()
            if row:
                if row['token_hash'] != p['token_hash'] or row['request_hash'] != p['request_hash']:
                    raise ValueError('Request key conflict')
                return row['id']
            if db.execute("select count(*) from company_orders where status in ('queued','processing','awaiting_payment')").fetchone()[0] >= 100:
                raise ValueError('Queue full')
            order = 'cx_' + secrets.token_urlsafe(18)
            paid = p['plan']['payment_mode'] in ('stripe_test','stripe_live')
            db.execute('insert into company_orders(id,request_key,request_hash,token_hash,plan,source_url,input,status,payment_status) values(?,?,?,?,?,?,?,?,?)',
                (order,p['request_key'],p['request_hash'],p['token_hash'],json.dumps(p['plan']),p.get('source_url',''),p['input'],
                 'awaiting_payment' if paid else 'queued','unpaid' if paid else 'not_required'))
            event(order, 'agreement_saved')
            return order
        if action == 'get':
            row = db.execute('select * from company_orders where id=? and token_hash=?', (p.get('id'), p.get('token_hash'))).fetchone()
            if not row:
                return None
            return {'id': row['id'], 'status': row['status'], 'payment_status': row['payment_status'],
                    'plan': json.loads(row['plan']), 'source_url': row['source_url'], 'error': row['error'],
                    'session_id': row['session_id'], 'session_url': row['session_url'],
                    'result': json.loads(row['result']) if row['result'] else None, 'revenue_jpy': 0,
                    'refund': refund_store.info(db,row['id']),
                    'events': [dict(e) for e in db.execute('select kind,created_at from company_events where order_id=? order by id', (row['id'],))]}
        if action == 'session':
            row = get_row()
            if row['session_id']:
                if row['session_id'] != p['session_id']:
                    raise ValueError('Checkout session conflict')
                return True
            mode=json.loads(row['plan'])['payment_mode']
            if not re.fullmatch('cs_live_[A-Za-z0-9]+' if mode=='stripe_live' else 'cs_test_[A-Za-z0-9]+',p.get('session_id','')):raise ValueError('Checkout mode mismatch')
            if row['status'] != 'awaiting_payment' or mode not in ('stripe_test','stripe_live'):
                raise ValueError('Checkout not allowed')
            db.execute('update company_orders set session_id=?,session_url=? where id=?', (p['session_id'],p['session_url'],row['id']))
            event(row['id'], 'checkout_created')
            return True
        if action == 'payment':
            existing = db.execute('select * from company_payment_events where event_id=?', (p['event_id'],)).fetchone()
            if existing:
                if existing['fingerprint'] != p['fingerprint'] or existing['order_id'] != p['id']:
                    raise ValueError('Payment event conflict')
                return True
            row = get_row(False)
            plan = json.loads(row['plan'])
            if (plan['payment_mode'] not in ('stripe_test','stripe_live') or p.get('livemode') is not (plan['payment_mode']=='stripe_live')
                    or p.get('amount') != plan['price_jpy'] or p.get('currency') != 'jpy'
                    or p.get('session_id') != row['session_id'] or p.get('payment_status') != 'paid'):
                raise ValueError('Payment evidence mismatch')
            db.execute('insert into company_payment_events(event_id,order_id,fingerprint) values(?,?,?)', (p['event_id'],row['id'],p['fingerprint']))
            if row['payment_status'] == 'unpaid':
                db.execute("update company_orders set payment_status='paid',status='queued' where id=? and status='awaiting_payment'", (row['id'],))
                event(row['id'], 'live_payment_verified' if plan['payment_mode']=='stripe_live' else 'test_payment_verified')
            return True
        if action == 'claim':
            now = time.time()
            expired = db.execute("select id from company_orders where status='processing' and lease_until<? and attempts>=3", (now,)).fetchall()
            for row in expired:
                db.execute("update company_orders set status='failed',input='',error='Retry limit exceeded' where id=?", (row['id'],))
                event(row['id'], 'failed')
            row = db.execute("select * from company_orders where status='queued' or (status='processing' and lease_until<? and attempts<3) order by created_at,id limit 1", (now,)).fetchone()
            if not row:
                return None
            lease = secrets.token_urlsafe(24)
            db.execute("update company_orders set status='processing',lease=?,lease_until=?,attempts=attempts+1 where id=?", (lease,now+120,row['id']))
            event(row['id'], 'processing_started')
            return {'id':row['id'],'input':row['input'],'plan':json.loads(row['plan']),'lease':lease}
        if action == 'finish':
            row = get_row(False)
            if row['status'] != 'processing' or row['lease'] != p.get('lease') or row['lease_until'] <= time.time():
                raise ValueError('Invalid or expired claim')
            result, error = p.get('result'), p.get('error')
            if not error and (not isinstance(result, dict) or result.get('service_key') != json.loads(row['plan'])['service_key']
                              or len(result.get('artifact', {}).get('content', '').encode()) > 8_000_000
                              or not result.get('download_sha256')):
                raise ValueError('Invalid artifact')
            status = ('queued' if row['attempts'] < 3 else 'failed') if error else 'ready'
            db.execute('update company_orders set status=?,result=?,error=?,input=\'\',lease=null,lease_until=null where id=?',
                       (status,json.dumps(result) if result else None,error,row['id']))
            if status == 'queued':
                db.execute('update company_orders set input=? where id=?',(row['input'],row['id']))
            event(row['id'], status)
            return True
        if action == 'receipt':
            row = get_row()
            if refund_store.info(db,row['id'])['state'] != 'none':
                raise ValueError('Refunded order cannot be received')
            if row['status'] not in ('ready','delivered') or json.loads(row['result'])['download_sha256'] != p.get('download_sha256'):
                raise ValueError('Delivery evidence mismatch')
            if row['status'] == 'ready':
                db.execute("update company_orders set status='delivered' where id=?", (row['id'],))
                event(row['id'], 'client_receipt_confirmed')
            return True
        if action == 'ai_reserve':
            old = db.execute('select result from company_ai_calls where request_hash=?', (p['request_hash'],)).fetchone()
            if old:
                return {'reserved': False, 'result': json.loads(old['result']) if old['result'] else None}
            month = db.execute('select coalesce(sum(reserve),0) from company_ai_calls where month=?', (p['month'],)).fetchone()[0]
            day = db.execute('select coalesce(sum(reserve),0) from company_ai_calls where day=?', (p['day'],)).fetchone()[0]
            if p['reserve'] <= 0 or month+p['reserve'] > p['month_limit'] or day+p['reserve'] > p['day_limit']:
                raise ValueError('AI budget exhausted')
            db.execute('insert into company_ai_calls(request_hash,month,day,reserve) values(?,?,?,?)', (p['request_hash'],p['month'],p['day'],p['reserve']))
            return {'reserved': True}
        if action == 'ai_finish':
            changed = db.execute('update company_ai_calls set result=? where request_hash=? and result is null', (json.dumps(p['result']),p['request_hash']))
            if not changed.rowcount:
                raise ValueError('AI reservation unavailable')
            return True
        if action == 'overview':
            counts = {row['status']: row['n'] for row in db.execute('select status,count(*) as n from company_orders group by status')}
            return {**refund_store.overview(db),'counts':counts,'real_revenue_jpy':sum(json.loads(r['plan'])['price_jpy'] for r in db.execute("select plan from company_orders where payment_status='paid' and status='delivered'") if json.loads(r['plan'])['payment_mode']=='stripe_live'),
                    'live_failed_paid_count':sum(json.loads(r['plan'])['payment_mode']=='stripe_live' for r in db.execute("select plan from company_orders where payment_status='paid' and status='failed'")),
                    'live_collected_jpy':sum(json.loads(r['plan'])['price_jpy'] for r in db.execute("select plan from company_orders where payment_status='paid'") if json.loads(r['plan'])['payment_mode']=='stripe_live'),
                    'test_payments_jpy':sum(json.loads(r['plan'])['price_jpy'] for r in db.execute("select plan from company_orders where payment_status='paid'") if json.loads(r['plan'])['payment_mode']=='stripe_test'),
                    'ai_reserved_micro_usd':db.execute('select coalesce(sum(reserve),0) from company_ai_calls').fetchone()[0],
                    'recent':[{**dict(r),'refund_state':refund_store.info(db,r['id'])['state']} for r in db.execute('select id,status,payment_status,error,created_at from company_orders order by created_at desc,id desc limit 20')]}
        if action == 'pending_payments':
            rows=[dict(r) for r in db.execute("select id,session_id from company_orders where status='awaiting_payment' and session_id is not null and updated_at<datetime('now','-60 seconds') order by updated_at,id limit 3")]
            for row in rows:db.execute('update company_orders set updated_at=CURRENT_TIMESTAMP where id=?',(row['id'],))
            return rows
        raise ValueError('Unknown company operation')
