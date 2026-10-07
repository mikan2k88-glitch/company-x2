import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from company_x2.store import Store
from company_x2.agent_scout import state
from company_x2.cloud_scout import run,search,QUERIES
from company_x2.supabase_store import StorageUnavailable
URL='https://github.com/example/jobs/issues/1'
def issue():return {'id':123,'html_url':URL,'title':'CSV to JSON bounty $10','body':'Convert CSV to JSON','state':'open','updated_at':'2026-10-07T00:00:00Z'}
class CloudScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'db');self.now=datetime(2026,10,8,1,tzinfo=timezone.utc)
    def tearDown(self):self.temp.cleanup()
    def test_rotation_durable_candidates_and_hour_replay(self):
        queries=[]
        def fetch(q):queries.append(q);return [issue()]
        first=run(self.store,fetch,lambda url:issue(),self.now)
        self.assertEqual(first['collected'],1)
        self.assertEqual(len(state(self.store)['items']),1)
        self.assertTrue(run(self.store,lambda q:self.fail('replay searched'),now=self.now)['replayed'])
        run(self.store,fetch,lambda url:issue(),self.now+timedelta(hours=1))
        self.assertEqual(queries,[QUERIES[1],QUERIES[2]])
        self.assertFalse(state(self.store)['items'][0]['proposal_sent'])
    def test_failed_run_does_not_advance_checkpoint(self):
        run(self.store,lambda q:[],now=self.now)
        before=state(self.store)
        def failed(q):raise StorageUnavailable('offline')
        with self.assertRaises(StorageUnavailable):run(self.store,failed,now=self.now+timedelta(hours=1))
        self.assertEqual(state(self.store),before)
    def test_closed_recheck_removes_candidate(self):
        run(self.store,lambda q:[issue()],lambda url:issue(),self.now)
        run(self.store,lambda q:[],lambda url:{**issue(),'state':'closed'},self.now+timedelta(hours=1))
        self.assertEqual(state(self.store)['items'],[])
    def test_search_rejects_partial_results(self):
        import io,json
        with self.assertRaises(StorageUnavailable):search(QUERIES[0],lambda *a,**k:io.BytesIO(json.dumps({'items':[],'incomplete_results':True}).encode()))
