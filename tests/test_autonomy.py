import tempfile,unittest,time
from pathlib import Path
from datetime import datetime,timezone
from company_x2.store import Store
from company_x2 import autonomy,outreach
from company_x2.intake_access import issue,contact_claim
from company_x2.company import quote,validate_creation,process_transaction
from company_x2.delivery_safety import require_delivery

URL='https://github.com/example/tasks/issues/1'
ENV={'OUTREACH_GITHUB_REPOS':'example/tasks','GITHUB_OUTREACH_TOKEN':'fixture','GITHUB_OUTREACH_LOGIN':'sender','OUTREACH_ENABLED':'false'}
ID='ot_'+'a'*32
class Client:
 def __init__(self,reply=''):
  self.reply=reply;self.comments=[];self.writes=0
  self.issue={'id':65,'html_url':URL,'state':'open','title':'Please deduplicate CSV rows for $25','body':outreach.PERMISSION,'labels':[],'user':{'login':'requester'},'updated_at':datetime.now(timezone.utc).isoformat()}
 def api(self,path,data=None):
  if data:
   self.writes+=1;c={'id':43,'html_url':URL+'#issuecomment-43','body':data['body'],'user':{'login':'sender'}};self.comments.append(c);return c
  if path=='/user':return {'login':'sender'}
  if 'state=open' in path:return [self.issue]
  if '?' in path:return self.comments
  return {**self.issue,'comments':len(self.comments)}
 def observe(self,contact):return {'id':contact['id'],'reply_id':42,'reply_text':self.reply,'next_message':'fixture draft'} if self.reply else None

class AutonomyTests(unittest.TestCase):
 def test_invitation_new_legacy_and_ambiguous_links(self):
  new=autonomy.invitation_link('synthetic-token',42)
  self.assertEqual(autonomy.invitation_grant(new,42),'synthetic-token')
  self.assertEqual(autonomy.invitation_grant('https://company-x2.onrender.com/intake#access=legacy',42),'legacy')
  for invalid in (new.replace('reply_id=42','reply_id=43'),new+'&work_invitation=other',
     new.replace('/template-intake#','/template-intake?x=1#'),new+'\n'+new,
     new.replace('/template-intake#','/other#')):
   with self.assertRaises(ValueError):autonomy.invitation_grant(invalid,42)
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Store(Path(self.temp.name)/'db')
 def contact(self,reply):
  self.store.outreach_rpc('prepare',{'id':ID,'url':URL,'issue_id':'65','author':'requester','message':'fixture'})
  self.store.outreach_rpc('claim');self.store.outreach_rpc('finish',{'id':ID,'comment_url':URL+'#issuecomment-9'})
  self.store.outreach_rpc('observe',{'id':ID,'reply_id':42,'reply_text':reply,'next_message':'fixture'})
 def test_ambiguous_or_injected_consent_is_held(self):
  yes=autonomy.FREE+' '+autonomy.AI
  self.assertTrue(autonomy.consent(yes)['accepted'])
  for text in ('yes',autonomy.FREE,yes+' but accept a paid contract',yes+' ignore restrictions'):
   self.assertFalse(autonomy.consent(text)['accepted'])
 def test_discovery_drafts_and_hourly_run_dedup_without_send(self):
  client=Client();r=autonomy.cycle(self.store,ENV,client,signing_key='k'*32)
  self.assertEqual(r['drafts'],1);self.assertEqual(client.writes,0)
  self.assertTrue(autonomy.cycle(self.store,ENV,client)['replayed'])
  self.assertEqual(len(self.store.outreach_rpc('list')),1)
 def test_followup_shared_limit_and_signed_source_to_delivery(self):
  reply=autonomy.FREE+' '+autonomy.AI;self.contact(reply)
  with self.store.connect() as db:db.execute("update outreach_contacts set attempted_at=datetime('now','-1 day')")
  client=Client(reply);r=autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true'},client,signing_key='k'*32)
  self.assertEqual(r['sent'],1);self.assertEqual(client.writes,1)
  self.assertIsNone(self.store.outreach_rpc('claim'));self.assertIsNone(self.store.autonomy_rpc('claim_message'))
  token,_=issue('k'*32,contact_id=ID);self.assertEqual(contact_claim(token,'k'*32),ID);self.assertIsNone(contact_claim(token+'x','k'*32))
  source=autonomy.intake_source(self.store,ID);risk=dict(sensitive_data='no',critical_use='no',extra_liability='no')
  plan=quote('csv_exact_dedup','id\n001\n001\n',risk_context=risk)
  payload=validate_creation({'service_key':'csv_exact_dedup','csv':'id\n001\n001\n','request_key':'linked-fixture-key','terms_accepted':True,'plan_sha256':plan['plan_sha256'],'source_url':source,'risk_context':risk},'o'*32)
  order=self.store.company_rpc('create',payload);self.assertTrue(process_transaction(self.store))
  saved=self.store.company_rpc('get',{'id':order,'token_hash':self.store.digest('o'*32)})
  require_delivery(saved);self.assertEqual(saved['source_url'],URL)
  self.store.company_rpc('receipt',{'id':order,'token_hash':self.store.digest('o'*32),'download_sha256':saved['result']['download_sha256']})
  self.assertEqual(self.store.company_rpc('get',{'id':order,'token_hash':self.store.digest('o'*32)})['status'],'delivered')
 def test_revoked_consent_blocks_intake(self):
  self.contact('not accepted')
  with self.assertRaises(ValueError):autonomy.intake_source(self.store,ID)
 def test_expired_invitation_is_held_without_external_post(self):
  reply=autonomy.FREE+' '+autonomy.AI;self.contact(reply)
  with self.store.connect() as db:db.execute("update outreach_contacts set attempted_at=datetime('now','-1 day')")
  token,_=issue('k'*32,now=time.time()-8*86400,contact_id=ID)
  self.store.autonomy_rpc('prepare_message',{'contact_id':ID,'reply_id':42,'body':'https://company-x2.onrender.com/intake#access='+token})
  client=Client(reply);autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true'},client,signing_key='k'*32)
  self.assertEqual(client.writes,0);self.assertEqual(self.store.autonomy_rpc('status')['messages'][0]['status'],'uncertain')
 def test_cost_unknown_and_loss_refund_failure_stop(self):
  self.assertFalse(autonomy.economics({})['live_allowed'])
  env={'COST_USD_JPY':'150','PAYMENT_FEE_RATE':'0.04','MONTHLY_FIXED_COST_JPY':'0'}
  self.assertTrue(autonomy.economics({},env)['live_allowed'])
  for metrics in ({'ai_reserved_micro_usd':20000000},{'live_orders':5,'refunded_orders':1},{'orders':10,'failed':3}):
   self.assertFalse(autonomy.economics(metrics,env)['live_allowed'])
 def test_stale_run_completion_cannot_override(self):
  lease=self.store.autonomy_rpc('claim',{'id':'20261010_01'})
  self.assertFalse(self.store.autonomy_rpc('finish',{'id':'20261010_01','lease':'wrong','status':'success','report':{}}))
  self.assertTrue(self.store.autonomy_rpc('finish',{'id':'20261010_01','lease':lease,'status':'success','report':{}}))
 def test_invalid_cost_settings_fail_closed(self):
  env={'COST_USD_JPY':'150','PAYMENT_FEE_RATE':'0.04','MONTHLY_FIXED_COST_JPY':'0'}
  for key in (*env,'MAX_MONTHLY_LOSS_JPY','LIVE_PRICE_JPY'):
   for value in ('bad','NaN','Infinity','-1',''):
    result=autonomy.economics({}, {**env,key:value})
    self.assertFalse(result['live_allowed'],(key,value))
    self.assertTrue(any(key in reason for reason in result['reasons']))
  self.assertFalse(autonomy.economics({}, {**env,'PAYMENT_FEE_RATE':'1.01'})['live_allowed'])
 def test_operating_status_distinguishes_fresh_failed_and_stale(self):
  now=datetime(2026,10,10,12,tzinfo=timezone.utc)
  self.assertFalse(autonomy.operating_status(self.store,ENV,now)['operations']['healthy'])
  lease=self.store.autonomy_rpc('claim',{'id':'20261010_12'})
  with self.store.connect() as db:db.execute("update autonomy_runs set started_at='2026-10-10T12:00:00Z'")
  self.store.autonomy_rpc('finish',{'id':'20261010_12','lease':lease,'status':'success','report':{}})
  status=autonomy.operating_status(self.store,ENV,now)
  self.assertTrue(status['operations']['healthy']);self.assertFalse(status['operations']['external_sending_enabled'])
  self.assertFalse(status['economics']['live_allowed'])
  with self.store.connect() as db:db.execute("update autonomy_runs set status='failed'")
  self.assertFalse(autonomy.operating_status(self.store,ENV,now)['operations']['healthy'])
  with self.store.connect() as db:db.execute("update autonomy_runs set status='success',started_at='2026-10-10T09:00:00Z'")
  self.assertFalse(autonomy.operating_status(self.store,ENV,now)['operations']['healthy'])
 def test_invalid_cost_blocks_external_post(self):
  client=Client();autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true','PAYMENT_FEE_RATE':'invalid'},client,signing_key='k'*32)
  self.assertEqual(client.writes,0)
 def test_invitation_post_timeout_is_not_retried_in_next_hour(self):
  reply=autonomy.FREE+' '+autonomy.AI;self.contact(reply)
  with self.store.connect() as db:db.execute("update outreach_contacts set attempted_at=datetime('now','-1 day')")
  class AmbiguousClient(Client):
   def api(inner,path,data=None):
    if data:
     super().api(path,data)
     raise TimeoutError('Server accepted comment; response lost')
    return super().api(path,data)
  client=AmbiguousClient(reply);now=datetime.now(timezone.utc)
  autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true'},client,signing_key='k'*32,now=now)
  self.assertEqual(client.writes,1)
  self.assertEqual(self.store.autonomy_rpc('status')['messages'][0]['status'],'uncertain')
  from datetime import timedelta
  autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true'},client,signing_key='k'*32,now=now+timedelta(hours=1))
  self.assertEqual(client.writes,1)
 def test_consent_revocation_between_prepare_and_post_is_held(self):
  reply=autonomy.FREE+' '+autonomy.AI;self.contact(reply)
  with self.store.connect() as db:db.execute("update outreach_contacts set attempted_at=datetime('now','-1 day')")
  class RevokingClient(Client):
   reads=0
   def observe(inner,contact):
    inner.reads+=1
    return {'id':contact['id'],'reply_id':42 if inner.reads==1 else 44,
      'reply_text':reply if inner.reads==1 else 'Consent withdrawn','next_message':'fixture'}
  client=RevokingClient(reply)
  autonomy.cycle(self.store,{**ENV,'OUTREACH_ENABLED':'true'},client,signing_key='k'*32)
  self.assertEqual(client.writes,0)
  self.assertEqual(self.store.autonomy_rpc('status')['messages'][0]['status'],'uncertain')
  with self.assertRaises(ValueError):autonomy.intake_source(self.store,ID)
