import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from company_x2.store import Store
from company_x2.supabase_store import SupabaseStore
from datetime import datetime,timezone
from company_x2 import outreach
from company_x2.render_contact_experiment import run,FIXTURE,TITLE,REPO

URL='https://github.com/'+REPO+'/issues/123'
ENV={'RENDER':'true','CX2_CONTACT_EXPERIMENT_URL':URL,'OUTREACH_GITHUB_REPOS':REPO,'GITHUB_OUTREACH_LOGIN':'owner','GITHUB_OUTREACH_TOKEN':'fixture','OUTREACH_ENABLED':'false'}
class Client(outreach.GitHubContact):
 def __init__(self):super().__init__(ENV);self.comments=[];self.calls=[];self.issue={'id':55,'html_url':URL,'title':TITLE,'body':FIXTURE+'\n'+outreach.PERMISSION,'user':{'login':'owner'},'state':'open','labels':[],'updated_at':datetime.now(timezone.utc).isoformat()}
 def api(self,path,data=None):
  self.calls.append((path,data))
  if path=='/user':return {'login':'owner'}
  if path.endswith('/comments') and data:
   c={'id':len(self.comments)+1,'html_url':URL+'#issuecomment-'+str(len(self.comments)+1),'body':data['body'],'user':{'login':'owner'}};self.comments.append(c);return c
  if '?' in path:return self.comments.copy()
  return {**self.issue,'comments':len(self.comments)}
class ExperimentTests(unittest.TestCase):
 def test_persistent_mode_refuses_local_storage_before_network(self):
  c=Client()
  with self.assertRaises(ValueError):run({**ENV,'CX2_CONTACT_EXPERIMENT_STORAGE':'supabase'},c)
  self.assertEqual(c.calls,[])
 def test_persistent_reread_and_existing_pending_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'db'
   class Adapter(SupabaseStore):
    def __init__(self):self.backend=Store(path)
    def outreach_rpc(self,action,payload=None):return self.backend.outreach_rpc(action,payload)
   env={**ENV,'CX2_CONTACT_EXPERIMENT_STORAGE':'supabase'}
   with patch('company_x2.render_contact_experiment.build_store',lambda _:Adapter()):
    result=run(env,Client(),lambda _:None,Adapter())
   self.assertTrue(result['persisted_reread']);self.assertEqual(Adapter().outreach_rpc('list')[0]['status'],'sent')
   c=Client()
   with self.assertRaises(ValueError):run(env,c,lambda _:None,Adapter())
   self.assertFalse(any(data for _,data in c.calls))
 def test_disabled_never_calls_api(self):
  c=Client();self.assertEqual(run({},c)['status'],'disabled');self.assertEqual(c.calls,[])
 def test_other_repo_or_host_rejected_before_api(self):
  for url in ('https://github.com/other/repo/issues/1','https://evil.example/issues/1'):
   c=Client()
   with self.assertRaises(ValueError):run({**ENV,'CX2_CONTACT_EXPERIMENT_URL':url},c)
   self.assertEqual(c.calls,[])
 def test_marker_and_owner_required_before_write(self):
  for change in ({'body':outreach.PERMISSION},{'user':{'login':'stranger'}}):
   c=Client();c.issue.update(change)
   with self.assertRaises(ValueError):run(ENV,c)
   self.assertFalse(any(data for _,data in c.calls))
 def test_closed_fixture_never_reposted(self):
  c=Client();c.issue['state']='closed';self.assertEqual(run(ENV,c)['status'],'already_closed');self.assertFalse(any(data for _,data in c.calls))
 def test_real_path_flow_duplicate_reply_and_close(self):
  c=Client();closed=[];result=run(ENV,c,closed.append)
  self.assertEqual(result['status'],'passed');self.assertEqual(len(c.comments),2);self.assertTrue(result['reply_saved']);self.assertTrue(result['follow_up_draft_only']);self.assertEqual(len(closed),1);self.assertEqual(ENV['OUTREACH_ENABLED'],'false')
