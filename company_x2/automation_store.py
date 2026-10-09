"""Atomic SQLite support automation snapshots and audit commits."""
import json
SCHEMA='''create table if not exists support_reviews(
 ticket_id text primary key references support_tickets(id),outcome text not null,
 reason text not null,version text not null,created_at text not null default CURRENT_TIMESTAMP);'''

def snapshot(row):
    return {'status':row['status'],'plan':json.loads(row['plan']),'result':json.loads(row['result']) if row['result'] else None}

def rpc(store,action,p):
    with store.connect() as db:
        db.execute('begin immediate')
        if action=='ping':return {'automation_schema_version':24}
        if action=='pending':
            result=[]
            for t in db.execute("select t.* from support_tickets t left join support_reviews r on r.ticket_id=t.id left join support_cases c on c.ticket_id=t.id where r.ticket_id is null and t.reply='' and ((c.ticket_id is null and t.status='open') or c.state='pending') order by t.created_at,t.id limit 10"):
                case=db.execute('select * from support_cases where ticket_id=?',(t['id'],)).fetchone()
                order=db.execute('select * from company_orders where id=?',(case['order_id'],)).fetchone() if case else None
                result.append({'ticket':{'id':t['id'],'kind':t['kind'],'message':t['message'],'reply':t['reply']},'order':snapshot(order) if order else None})
            return result
        if action=='get':
            return dict(row) if (row:=db.execute('select r.* from support_reviews r join support_tickets t on t.id=r.ticket_id where t.id=? and t.token_hash=?',(p['id'],p['token_hash'])).fetchone()) else None
        if action=='list':return [dict(r) for r in db.execute('select * from support_reviews order by created_at desc,ticket_id limit 100')]
        if action=='commit':
            if p.get('outcome') not in ('manual','answered','confirmed_defect') or p.get('version')!='support-auto-v1' or not isinstance(p.get('reason'),str) or not 1<=len(p['reason'])<=4000:raise ValueError('Automation decision rejected')
            t=db.execute('select * from support_tickets where id=?',(p['id'],)).fetchone()
            if not t or t['reply']!=p['expected_reply'] or db.execute('select 1 from support_reviews where ticket_id=?',(t['id'],)).fetchone():return False
            case=db.execute('select * from support_cases where ticket_id=?',(t['id'],)).fetchone()
            if case:
                o=db.execute('select * from company_orders where id=?',(case['order_id'],)).fetchone()
                if case['state']!='pending' or snapshot(o)!=p['expected'] or p['outcome']=='answered':return False
                if p['outcome']=='confirmed_defect':
                    if o['status'] not in ('ready','delivered'):return False
                    db.execute("update company_orders set status='failed',attempts=3,lease=null,lease_until=null,error='Confirmed defect; delivery held',updated_at=CURRENT_TIMESTAMP where id=?",(o['id'],))
                    db.execute("update support_cases set state='confirmed_defect',reason=?,resolved_at=CURRENT_TIMESTAMP where ticket_id=?",(p['reason'],t['id']))
                    db.execute("insert into support_case_events(ticket_id,kind,reason) values(?,'confirmed_defect',?)",(t['id'],p['reason']))
                    db.execute("insert into company_events(order_id,kind) values(?,'support_confirmed_defect')",(o['id'],))
                    db.execute("update support_tickets set reply=?,status='answered',updated_at=CURRENT_TIMESTAMP where id=?",(p['reason'],t['id']))
            elif p['outcome']=='confirmed_defect' or p['expected'] is not None:return False
            elif p['outcome']=='answered':
                if t['kind']!='question' or t['status']!='open':return False
                db.execute("update support_tickets set reply=?,status='answered',updated_at=CURRENT_TIMESTAMP where id=?",(p['reason'],t['id']))
            db.execute('insert into support_reviews(ticket_id,outcome,reason,version) values(?,?,?,?)',(t['id'],p['outcome'],p['reason'],p['version']))
            return True
        raise ValueError('Unknown automation action')
