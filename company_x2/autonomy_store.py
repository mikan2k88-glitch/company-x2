"""SQLite counterpart of the private E34 coordinator RPC."""
import json,uuid
SCHEMA='''create table if not exists autonomy_runs(id text primary key,lease text not null,status text not null default 'processing',report text,started_at text not null default CURRENT_TIMESTAMP);create table if not exists autonomy_messages(id text primary key,contact_id text unique not null,reply_id integer not null,body text not null,status text not null default 'draft',attempted_at text,comment_url text);'''
def rpc(store,action,p):
 with store.connect() as db:
  db.execute('begin immediate')
  if action=='ping':return {'autonomy_schema_version':34}
  if action=='claim':
   lease=uuid.uuid4().hex
   return lease if db.execute('insert or ignore into autonomy_runs(id,lease) values(?,?)',(p['id'],lease)).rowcount else None
  if action=='finish':return bool(db.execute("update autonomy_runs set status=?,report=? where id=? and lease=? and status='processing'",(p['status'],json.dumps(p['report']),p['id'],p['lease'])).rowcount)
  if action=='status':return {'runs':[{**dict(r),'report':json.loads(r['report']) if r['report'] else None} for r in db.execute('select id,status,report,started_at from autonomy_runs order by started_at desc,id desc limit 24')], 'messages':[dict(r) for r in db.execute('select id,contact_id,reply_id,status,comment_url from autonomy_messages limit 50')]}
  if action=='prepare_message':
   return bool(db.execute('insert or ignore into autonomy_messages(id,contact_id,reply_id,body) values(?,?,?,?)',('am_'+p['contact_id'],p['contact_id'],p['reply_id'],p['body'])).rowcount)
  if action=='claim_message':
   if db.execute("select 1 from outreach_contacts where attempted_at>=date('now') union all select 1 from autonomy_messages where attempted_at>=date('now')").fetchone():return None
   row=db.execute("select * from autonomy_messages where status='draft' order by id limit 1").fetchone()
   if not row:return None
   db.execute("update autonomy_messages set status='sending',attempted_at=CURRENT_TIMESTAMP where id=?",(row['id'],));return dict(row)
  if action in ('finish_message','uncertain_message'):
   return bool(db.execute("update autonomy_messages set status=?,comment_url=? where id=? and status='sending'",('sent' if action=='finish_message' else 'uncertain',p.get('url'),p['id'])).rowcount)
  if action=='metrics':
   orders=[dict(r) for r in db.execute("select status,payment_status,plan,id from company_orders where created_at>=date('now','start of month')")]
   live=[r for r in orders if json.loads(r['plan'])['payment_mode']=='stripe_live' and r['payment_status']=='paid'];ids={r['id'] for r in live}
   refunds=[dict(r) for r in db.execute("select * from company_refunds where status='succeeded'") if r['order_id'] in ids]
   return {'orders':len(orders),'failed':sum(r['status']=='failed' for r in orders),'live_orders':len(live),'live_revenue_jpy':sum(json.loads(r['plan'])['price_jpy'] for r in live),'live_refunds_jpy':sum(r['amount'] for r in refunds),'refunded_orders':len({r['order_id'] for r in refunds}),'ai_reserved_micro_usd':db.execute("select coalesce(sum(reserve),0) from company_ai_calls where month=strftime('%Y-%m','now')").fetchone()[0]}
  raise ValueError('Unknown autonomy action')
