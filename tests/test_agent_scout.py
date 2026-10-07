import tempfile
import unittest
from pathlib import Path
from company_x2.store import Store
from company_x2.agent_scout import register,state,fetch_issue
from company_x2.supabase_store import StorageUnavailable

URL='https://github.com/example/jobs/issues/1'
def issue(url=URL):
    return {'id':123,'html_url':url,'title':'CSV to JSON bounty $10','body':'Convert CSV to JSON','state':'open','updated_at':'2026-10-07T00:00:00Z'}
class AgentScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db')
        self.data={'run_key':'hourly_20261008_01','urls':[URL], 'checkpoint':{'next_query':'csv bounty','note':'one source checked'}}
    def tearDown(self):self.temp.cleanup()
    def test_resume_replay_and_reclassification_survive_restart(self):
        register(self.store,self.data,lambda url:issue())
        restarted=Store(self.store.path)
        saved=state(restarted)
        self.assertEqual(saved['items'][0]['decision'],'needs_review')
        self.assertFalse(saved['items'][0]['proposal_sent'])
        self.assertEqual(saved['checkpoint'],self.data['checkpoint'])
        result=register(restarted,self.data,lambda url:self.fail('Replay fetched'))
        self.assertTrue(result['replayed'])
        with self.assertRaises(ValueError):register(restarted,{**self.data,'urls':[]})
    def test_failure_preserves_checkpoint_and_closed_issue_removes_saved_candidate(self):
        register(self.store,self.data,lambda url:issue())
        def failed(url):raise StorageUnavailable('offline')
        newer={**self.data,'run_key':'hourly_20261008_02','checkpoint':{'note':'new'}}
        with self.assertRaises(StorageUnavailable):register(self.store,newer,failed)
        self.assertEqual(state(self.store)['checkpoint'],self.data['checkpoint'])
        register(self.store,newer,lambda url:{**issue(),'state':'closed'})
        self.assertEqual(state(self.store)['items'],[])
    def test_new_run_upserts_same_url_and_rejects_arbitrary_hosts(self):
        register(self.store,self.data,lambda url:issue())
        register(self.store,{**self.data,'run_key':'hourly_20261008_02'},lambda url:{**issue(),'assignees':[{'login':'owner'}]})
        self.assertEqual(len(state(self.store)['items']),1)
        self.assertEqual(state(self.store)['items'][0]['decision'],'blocked')
        for url in ['http://127.0.0.1/','https://github.com/example/jobs/issues/1?secret=x']:
            with self.assertRaises(ValueError):register(self.store,{**self.data,'urls':[url]},lambda u:self.fail('Invalid URL fetched'))
    def test_remote_identity_mismatch_cannot_save(self):
        import io,json
        with self.assertRaises(StorageUnavailable):fetch_issue(URL,lambda *a,**k:io.BytesIO(json.dumps(issue('https://github.com/other/repo/issues/1')).encode()))

import test_company_http as http_tests
from unittest.mock import patch
class AgentHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call
    def test_authenticated_registration_context_and_company_draft(self):
        with self.assertRaises(Exception):self.call('/api/company/agent-scout',auth=False)
        from datetime import datetime,timezone
        raw={**issue(),'updated_at':datetime.now(timezone.utc).isoformat()}
        data={'run_key':'hourly_test_000001','urls':[URL],'checkpoint':{'note':'done'}}
        with patch('company_x2.agent_scout.urllib.request.build_opener') as mocked:
            import io,json
            mocked.return_value.open.return_value=io.BytesIO(json.dumps(raw).encode())
            self.assertTrue(self.call('/api/company/agent-scout',data)['saved'])
        self.assertEqual(self.call('/api/company/agent-scout')['checkpoint'],{'note':'done'})
        self.assertEqual(self.call('/api/company/candidates')['summary']['review'],1)
        self.assertEqual(self.call('/api/company/lead-draft',{'source_url':URL})['options'][0]['service_key'],'csv_to_json')
