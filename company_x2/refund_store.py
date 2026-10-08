"""SQLite refund RPCs; invoked inside the company transaction."""
import json
import re

SCHEMA = '''
create table if not exists company_payment_bindings (
 order_id text primary key references company_orders(id), payment_intent text unique not null
);
create table if not exists company_refund_jobs (
 order_id text primary key references company_orders(id), state text not null,
 checked_at text not null default CURRENT_TIMESTAMP
);
create table if not exists company_refunds (
 refund_id text primary key, order_id text not null references company_orders(id),
 amount integer not null, status text not null
);
'''


def info(db, order):
    job = db.execute('select state from company_refund_jobs where order_id=?', (order,)).fetchone()
    items = [dict(x) for x in db.execute('select refund_id,amount,status from company_refunds where order_id=?', (order,))]
    return {'state': job['state'] if job else 'none', 'items': items,
        'refunded_jpy': sum(x['amount'] for x in items if x['status'] == 'succeeded')}


def rpc(db, action, p, event):
    if action == 'refund_ping':
        return {'refund_schema_version': 20}
    if action == 'refund_bindings':
        rows=[dict(x) for x in db.execute("""select id,session_id,plan from company_orders o
            where payment_status='paid' and session_id is not null and updated_at<=datetime('now','-60 seconds')
            and not exists(select 1 from company_payment_bindings b where b.order_id=o.id) order by updated_at,id limit 1""")]
        for row in rows:
            row['plan']=json.loads(row['plan'])
            db.execute('update company_orders set updated_at=CURRENT_TIMESTAMP where id=?',(row['id'],))
        return rows
    if action == 'refund_bind':
        row = db.execute('select * from company_orders where id=?', (p.get('id'),)).fetchone()
        if (not row or row['payment_status'] != 'paid' or row['session_id'] != p.get('session_id')
                or p.get('livemode') is not (json.loads(row['plan'])['payment_mode'] == 'stripe_live')
                or not re.fullmatch(r'pi_[A-Za-z0-9]+', p.get('payment_intent', ''))):
            raise ValueError('Payment binding rejected')
        old = db.execute('select payment_intent from company_payment_bindings where order_id=?', (row['id'],)).fetchone()
        if old and old['payment_intent'] != p['payment_intent']:
            raise ValueError('Payment binding conflict')
        other=db.execute('select order_id from company_payment_bindings where payment_intent=?',(p['payment_intent'],)).fetchone()
        if other and other['order_id'] != row['id']:
            raise ValueError('Payment identity already bound')
        db.execute('insert or ignore into company_payment_bindings values(?,?)', (row['id'], p['payment_intent']))
        return True
    if action == 'refund_claim':
        rows = db.execute("""select o.id from company_orders o where o.payment_status='paid'
            and o.status in ('failed','queued','processing') and o.session_id is not null
            and (o.status='failed' or exists(select 1 from company_payment_events e where e.order_id=o.id
                and e.created_at<=datetime('now','-24 hours')))
            and not exists(select 1 from company_refund_jobs j where j.order_id=o.id) order by o.id limit 3""").fetchall()
        for row in rows:
            db.execute("insert into company_refund_jobs(order_id,state) values(?,'requesting')", (row['id'],))
            db.execute("update company_orders set status='failed',input='',lease=null,lease_until=null,error='Refund processing' where id=?", (row['id'],))
            event(row['id'], 'refund_reserved')
        row = db.execute("""select o.* from company_orders o join company_refund_jobs j on j.order_id=o.id
            where j.state in ('requesting','pending') and j.checked_at<=datetime('now','-60 seconds')
            order by j.checked_at,o.id limit 1""").fetchone()
        # Fresh reservations can be picked once immediately; older jobs are leased for 60 seconds.
        if not row and rows:
            row = db.execute('select * from company_orders where id=?', (rows[0]['id'],)).fetchone()
        if not row:
            return None
        db.execute('update company_refund_jobs set checked_at=CURRENT_TIMESTAMP where order_id=?', (row['id'],))
        return {'id': row['id'], 'session_id': row['session_id'], 'plan': json.loads(row['plan'])}
    if action == 'refund_review':
        db.execute("update company_refund_jobs set state='review' where order_id=? and state<>'succeeded'", (p.get('id'),))
        return True
    if action == 'refund_update':
        row = db.execute('select o.* from company_orders o join company_payment_bindings b on b.order_id=o.id where b.payment_intent=?', (p.get('payment_intent'),)).fetchone()
        if not row:
            return False  # Another app sharing the Stripe account.
        plan = json.loads(row['plan'])
        if (not re.fullmatch(r're_[A-Za-z0-9]+', p.get('refund_id', '')) or p.get('currency') != 'jpy'
                or p.get('livemode') is not (plan['payment_mode'] == 'stripe_live')
                or type(p.get('amount')) is not int or not 0 < p['amount'] <= plan['price_jpy']
                or p.get('status') not in ('pending','requires_action','succeeded','failed','canceled')):
            raise ValueError('Refund evidence mismatch')
        old = db.execute('select * from company_refunds where refund_id=?', (p['refund_id'],)).fetchone()
        if old and (old['order_id'] != row['id'] or old['amount'] != p['amount']):
            raise ValueError('Refund identity conflict')
        if old and old['status'] in ('succeeded','failed','canceled') and p['status'] in ('pending','requires_action'):
            return True
        total = db.execute("select coalesce(sum(amount),0) from company_refunds where order_id=? and refund_id<>? and status in ('succeeded','pending','requires_action')", (row['id'],p['refund_id'])).fetchone()[0]
        if p['status'] in ('succeeded','pending','requires_action') and total+p['amount'] > plan['price_jpy']:
            raise ValueError('Refund total mismatch')
        changed = not old or old['status'] != p['status']
        db.execute('insert into company_refunds values(?,?,?,?) on conflict(refund_id) do update set status=excluded.status', (p['refund_id'],row['id'],p['amount'],p['status']))
        items = info(db, row['id'])
        state = 'succeeded' if items['refunded_jpy'] == plan['price_jpy'] else ('pending' if any(x['status']=='pending' and x['amount']==plan['price_jpy'] for x in items['items']) else 'review')
        db.execute('insert into company_refund_jobs(order_id,state) values(?,?) on conflict(order_id) do update set state=excluded.state', (row['id'],state))
        if state in ('pending','succeeded') and row['status'] not in ('ready','delivered'):
            db.execute("update company_orders set status='failed',input='',lease=null,lease_until=null where id=?", (row['id'],))
        if changed:
            event(row['id'], 'refund_' + p['status'])
        return True
    raise ValueError('Unknown refund operation')


def overview(db):
    totals = {}
    for mode in ('stripe_test','stripe_live'):
        totals[mode] = sum(x['amount'] for x in db.execute("select r.amount,o.plan from company_refunds r join company_orders o on o.id=r.order_id where r.status='succeeded'") if json.loads(x['plan'])['payment_mode'] == mode)
    return {'live_refunded_jpy': totals['stripe_live'], 'test_refunded_jpy': totals['stripe_test'],
        'refund_counts': {r['state']:r['n'] for r in db.execute('select state,count(*) n from company_refund_jobs group by state')}}
