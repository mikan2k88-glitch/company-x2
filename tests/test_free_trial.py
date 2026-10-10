import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from company_x2 import free_trial,public_intake
from company_x2.store import Store
from company_x2.company import quote,process_transaction

def settings():
 now=datetime.now(timezone.utc)
 return {'FREE_TRIAL_ENABLED':'true','FREE_TRIAL_START':(now-timedelta(minutes=1)).isoformat(),
   'FREE_TRIAL_END':(now+timedelta(days=13)).isoformat()}

def payload(key):
 risk=dict(sensitive_data='no',critical_use='no',extra_liability='no')
 text='id\nDEVELOPMENT_MUST_NOT_COPY_THIS_CELL\n'
 plan=quote('csv_to_json',text,risk_context=risk)
 return {'service_key':'csv_to_json','csv':text,'payment_mode':'sandbox','risk_context':risk,
   'plan_sha256':plan['plan_sha256'],'terms_accepted':True,'request_key':key}

class TrialTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=Store(Path(self.tmp.name)/'db')
 def test_strict_period_and_three_order_limit(self):
  for env in ({'FREE_TRIAL_ENABLED':'true'}, {**settings(),'FREE_TRIAL_END':'bad'},
    {**settings(),'FREE_TRIAL_START':'2026-01-01T00:00:00Z'}):
   self.assertFalse(free_trial.policy(env)['open'])
  with patch.dict('os.environ',settings()):
   for n in range(3):public_intake.create(self.store,payload(str(n).zfill(32)),str(n).zfill(32))
   with self.assertRaises(public_intake.LimitReached):public_intake.create(self.store,payload('q'*32),'q'*32)
   self.assertEqual(free_trial.report(self.store)['totals']['accepted'],3)
 def test_private_report_contains_no_customer_content(self):
  with patch.dict('os.environ',settings()):
   order=public_intake.create(self.store,payload('x'*32),'o'*32);process_transaction(self.store)
   data=free_trial.report(self.store);text=json.dumps(data)
   self.assertEqual(data['totals']['ready'],1)
   self.assertNotIn('DEVELOPMENT_MUST_NOT_COPY_THIS_CELL',text);self.assertNotIn(order,text)
   self.assertNotIn(self.store.digest('o'*32),text);self.assertIsNotNone(data['services']['csv_to_json']['average_processing_seconds'])
 def test_expired_trial_preserves_download_renewal_and_replay(self):
  with patch.dict('os.environ',settings()):
   p=payload('x'*32);order=public_intake.create(self.store,p,'o'*32);process_transaction(self.store)
  now=datetime.now(timezone.utc);expired={'FREE_TRIAL_ENABLED':'true',
   'FREE_TRIAL_START':(now-timedelta(days=2)).isoformat(),'FREE_TRIAL_END':(now-timedelta(days=1)).isoformat()}
  with patch.dict('os.environ',expired):
   public_intake.start(self.store,'o'*32)
   self.assertEqual(public_intake.create(self.store,p,'o'*32),order)
   with self.assertRaises(public_intake.LimitReached):public_intake.start(self.store,'n'*32)
   with self.assertRaises(public_intake.LimitReached):public_intake.reserve_quote(self.store,p)
   public_intake.delivered(self.store,order,'o'*32)
 def test_failures_hold_new_intake_without_reusing_customer_csv(self):
  with patch.dict('os.environ',settings()):
   for n in range(3):public_intake.create(self.store,payload(str(n).zfill(32)),str(n).zfill(32))
   with self.store.connect() as db:db.execute("update company_orders set status='failed',error='DO_NOT_EXPOSE_THIS_ERROR'")
   data=free_trial.report(self.store);self.assertTrue(data['new_intake_paused'])
   self.assertNotIn('DO_NOT_EXPOSE_THIS_ERROR',json.dumps(data))
   with self.assertRaises(public_intake.LimitReached):public_intake.reserve_quote(self.store,payload('q'*32))
 def test_hourly_development_snapshot_is_content_free(self):
  from test_autonomy import Client,ENV
  from company_x2 import autonomy
  env=settings()
  with patch.dict('os.environ',env):
   public_intake.create(self.store,payload('x'*32),'o'*32);process_transaction(self.store)
   run=autonomy.cycle(self.store,{**ENV,**env},Client(),signing_key='k'*32)
   self.assertEqual(run['free_trial']['totals']['ready'],1)
   saved=self.store.autonomy_rpc('status')['runs'][0]['report']
   self.assertNotIn('DEVELOPMENT_MUST_NOT_COPY_THIS_CELL',json.dumps(saved))
