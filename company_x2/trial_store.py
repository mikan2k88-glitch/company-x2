"""Select only non-content metadata for public trial development reports."""
import json

def rpc(store,action,p):
    if action=='ping':return {'trial_schema_version':37}
    if action!='report' or not isinstance(p.get('ids'),list) or len(p['ids'])>300:raise ValueError('Invalid trial report')
    if not p['ids']:return []
    with store.connect() as db:
        rows=db.execute('select id,status,plan from company_orders where id in ('+','.join('?' for _ in p['ids'])+
          ") and source_url='' and datetime(created_at)>=datetime(?)",[*p['ids'],p['since']]).fetchall()
        result=[]
        for row in rows:
            plan=json.loads(row['plan'])
            if plan['payment_mode']!='sandbox':continue
            times=db.execute("select min(case when kind='processing_started' then julianday(created_at) end),min(case when kind='ready' then julianday(created_at) end) from company_events where order_id=?",(row['id'],)).fetchone()
            duration=max(0,(times[1]-times[0])*86400) if all(t is not None for t in times) else None
            result.append({'service_key':plan['service_key'],'status':row['status'],'processing_seconds':duration})
        return result
