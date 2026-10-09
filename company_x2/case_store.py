"""Atomic case holds and decisions; no provider calls inside storage."""
import json
from .support_store import create_in, visible

SCHEMA='''create table if not exists support_cases(
 ticket_id text primary key references support_tickets(id), order_id text not null references company_orders(id),
 state text not null default 'pending', reason text not null default '',
 created_at text not null default CURRENT_TIMESTAMP, resolved_at text);
 create unique index if not exists support_case_pending on support_cases(order_id) where state='pending';
 create table if not exists support_case_events(
 id integer primary key,ticket_id text not null references support_cases(ticket_id),
 kind text not null,reason text not null default '',created_at text not null default CURRENT_TIMESTAMP);'''

def rpc(store,action,p):
    with store.connect() as db:
        db.execute('begin immediate')
        if action=='ping':return {'case_schema_version':23}
        if action=='state':
            return {'hold':bool(db.execute("select 1 from support_cases where order_id=? and state in ('pending','confirmed_defect')",(p['order_id'],)).fetchone())}
        if action=='report':
            order=db.execute('select * from company_orders where id=? and token_hash=?',(p['order_id'],p['order_token_hash'])).fetchone()
            if not order or order['status'] not in ('ready','delivered','failed'):raise ValueError('問題報告の対象注文を確認できません')
            old=db.execute('select id,fingerprint from support_tickets where token_hash=? and request_key=?',(p['token_hash'],p['request_key'])).fetchone()
            if old:
                if old['fingerprint']!=p['fingerprint'] or not db.execute('select 1 from support_cases where ticket_id=? and order_id=?',(old['id'],order['id'])).fetchone():raise ValueError('受付キーが異なる内容で使用されています')
                return {'id':old['id']}
            if db.execute("select 1 from support_cases where order_id=? and state='pending'",(p['order_id'],)).fetchone():raise ValueError('この注文は確認中です')
            created=create_in(db,p)
            db.execute('insert into support_cases(ticket_id,order_id) values(?,?)',(created['id'],order['id']))
            db.execute("insert into support_case_events(ticket_id,kind) values(?,'reported')",(created['id'],))
            db.execute("insert into company_events(order_id,kind) values(?,'support_hold')",(order['id'],))
            return created
        if action=='get':
            row=db.execute('select c.* from support_cases c join support_tickets t on t.id=c.ticket_id where t.id=? and t.token_hash=?',(p['id'],p['token_hash'])).fetchone()
            if not row:return None
            return {**dict(row),'history':[dict(r) for r in db.execute('select kind,reason,created_at from support_case_events where ticket_id=? order by id',(row['ticket_id'],))]}
        if action=='list':return [{**dict(r),'ticket':visible(db.execute('select * from support_tickets where id=?',(r['ticket_id'],)).fetchone())} for r in db.execute("select * from support_cases order by (state='pending') desc,created_at,ticket_id limit 50")]
        if action=='resolve':
            if p.get('decision') not in ('confirmed_defect','not_confirmed') or not isinstance(p.get('reason'),str) or not 1<=len(p['reason'])<=4000:raise ValueError('判断と理由が必要です')
            case=db.execute('select * from support_cases where ticket_id=?',(p['id'],)).fetchone()
            if not case:raise ValueError('問題報告がありません')
            if case['state']!='pending':
                if case['state']==p['decision'] and case['reason']==p['reason']:return {'resolved':True,'decision':case['state']}
                raise ValueError('確定済みの判断は変更できません')
            order=db.execute('select * from company_orders where id=?',(case['order_id'],)).fetchone()
            if p['decision']=='confirmed_defect':
                if order['status'] not in ('ready','delivered','failed'):raise ValueError('注文状態を確認して再試行してください')
                db.execute("update company_orders set status='failed',attempts=3,lease=null,lease_until=null,error='Confirmed defect; delivery held',updated_at=CURRENT_TIMESTAMP where id=?",(order['id'],))
            db.execute('update support_cases set state=?,reason=?,resolved_at=CURRENT_TIMESTAMP where ticket_id=?',(p['decision'],p['reason'],case['ticket_id']))
            db.execute('insert into support_case_events(ticket_id,kind,reason) values(?,?,?)',(case['ticket_id'],p['decision'],p['reason']))
            db.execute('insert into company_events(order_id,kind) values(?,?)',(order['id'],'support_'+p['decision']))
            db.execute("update support_tickets set status='answered',reply=?,updated_at=CURRENT_TIMESTAMP where id=?",(p['reason'],case['ticket_id']))
            return {'resolved':True,'decision':p['decision'],'refund_requested':p['decision']=='confirmed_defect' and order['payment_status']=='paid'}
        raise ValueError('Unknown case action')
