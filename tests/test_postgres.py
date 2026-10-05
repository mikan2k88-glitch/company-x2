"""Real SQL integration tests. CI provides a disposable PostgreSQL instance."""
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

DSN = os.environ.get('CX2_TEST_DSN')


@unittest.skipUnless(DSN and shutil.which('psql'), 'Disposable PostgreSQL not configured')
class PostgresTests(unittest.TestCase):
    @classmethod
    def sql(cls, query, *, check=True):
        return subprocess.run(['psql', DSN, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', query],
            capture_output=True, text=True, check=check)

    @classmethod
    def setUpClass(cls):
        cls.sql("create role anon; create role authenticated; create role service_role;")
        migration = Path('supabase/migrations/002_sandbox_rpc.sql').read_text()
        cls.sql(migration)
        cls.sql(Path('supabase/migrations/003_public_scout.sql').read_text())
        cls.sql(Path('supabase/migrations/004_data_services.sql').read_text())

    def setUp(self):
        self.sql('truncate company_x2.sandbox_events,company_x2.sandbox_orders cascade;')
        self.sql('truncate company_x2.service_events,company_x2.service_orders cascade;')
        self.sql("delete from company_x2.sandbox_opportunities; delete from company_x2.scout_state; insert into company_x2.scout_state(id) values(1);")

    def rpc(self, action, payload=None):
        data = json.dumps(payload or {}).replace("'", "''")
        response = self.sql(f"set role service_role; select coalesce(public.cx2_store('{action}','{data}'::jsonb),'null'::jsonb);")
        return json.loads(response.stdout.splitlines()[-1])

    def submit(self):
        return self.rpc('submit', {'input':'a\n1\n1\n', 'request_key':'request-key-123456',
            'request_hash':'a'*64, 'token_hash':'b'*64})

    def test_rpc_lifecycle_and_idempotency(self):
        self.assertEqual(self.rpc('ping'), {'schema_version':2})
        order = self.submit()
        self.assertEqual(order, self.submit())
        claim = self.rpc('claim')
        self.assertEqual(claim['id'], order)
        self.assertIsNone(self.rpc('claim'))
        self.rpc('finish', {'id':order,'lease':claim['lease'],'result':{'csv':'a\n1\n'}})
        saved = self.rpc('get', {'id':order,'token_hash':'b'*64})
        self.assertEqual(saved['status'], 'ready')
        self.assertEqual(saved['revenue_jpy'],0)
        self.assertIsNone(self.rpc('get', {'id':order,'token_hash':'c'*64}))

    def services_rpc(self, action, payload=None):
        data = json.dumps(payload or {}).replace("'", "''")
        response = self.sql(f"set role service_role; select coalesce(public.cx2_services('{action}','{data}'::jsonb),'null'::jsonb);")
        return json.loads(response.stdout.splitlines()[-1])

    def service_payload(self, key='service-request-123', service='csv_to_json'):
        return {'input':'a\n001\n','request_key':key,'request_hash':'a'*64,'token_hash':'b'*64,'service_key':service}

    def test_new_service_queue_preserves_type_and_cannot_be_claimed_by_legacy(self):
        payload = self.service_payload()
        order = self.services_rpc('submit',payload)
        self.assertTrue(order.startswith('svc_'))
        self.assertEqual(order,self.services_rpc('submit',payload))
        self.assertIsNone(self.rpc('claim'))
        claim = self.services_rpc('claim')
        self.assertEqual(claim['service_key'],'csv_to_json')
        self.assertIsNone(self.services_rpc('claim'))
        self.services_rpc('finish',{'id':order,'lease':claim['lease'],'result':{
            'artifact':{'content':'[{"a":"001"}]'},'service_key':'csv_to_json'}})
        saved = self.services_rpc('get',{'id':order,'token_hash':'b'*64})
        self.assertEqual(saved['status'],'ready')
        self.assertEqual(saved['service_key'],'csv_to_json')
        self.assertEqual(saved['revenue_jpy'],0)
        self.assertIsNone(self.services_rpc('get',{'id':order,'token_hash':'c'*64}))
        self.assertEqual(self.services_rpc('ping'),{'schema_version':4})

    def test_service_change_cross_queue_key_reuse_and_anonymous_access_rejected(self):
        self.submit()
        with self.assertRaises(subprocess.CalledProcessError):
            self.services_rpc('submit',self.service_payload(key='request-key-123456'))
        payload = self.service_payload()
        self.services_rpc('submit',payload)
        with self.assertRaises(subprocess.CalledProcessError):
            self.services_rpc('submit',{**payload,'service_key':'csv_trim'})
        with self.assertRaises(subprocess.CalledProcessError):
            self.rpc('submit',{'input':'a\n1\n','request_key':payload['request_key'],
                              'request_hash':'c'*64,'token_hash':'b'*64})
        self.assertNotEqual(self.sql("set role anon; select public.cx2_services('ping');",check=False).returncode,0)

    def test_new_service_expired_lease_and_retry_limit(self):
        order = self.services_rpc('submit',self.service_payload())
        first = self.services_rpc('claim')
        self.sql(f"update company_x2.service_orders set lease_until=now()-interval '1 second' where id='{order}';")
        second = self.services_rpc('claim')
        with self.assertRaises(subprocess.CalledProcessError):
            self.services_rpc('finish',{'id':order,'lease':first['lease'],'error':'late'})
        self.sql(f"update company_x2.service_orders set lease_until=now()-interval '1 second',attempts=3 where id='{order}';")
        self.assertIsNone(self.services_rpc('claim'))
        saved = self.services_rpc('get',{'id':order,'token_hash':'b'*64})
        self.assertEqual(saved['status'],'failed')
        self.assertEqual(saved['revenue_jpy'],0)

    def test_production_adapter_and_worker_complete_all_services_on_real_sql(self):
        import io
        from company_x2.supabase_store import SupabaseStore
        from company_x2.worker import process_one
        def opener(req, timeout):
            payload = json.loads(req.data)
            if req.full_url.endswith('cx2_services'):
                result = self.services_rpc(payload['p_action'],payload['p_payload'])
            else:
                result = self.rpc(payload['p_action'],payload['p_payload'])
            return io.BytesIO(json.dumps(result).encode())
        store = SupabaseStore('https://example.supabase.co','sb_secret_test',opener=opener)
        self.assertTrue(store.services_ready())
        orders = [(service,store.submit('id,value\n001, x \n001, x \n',str(index)*32,'t'*32,service))
                  for index,service in enumerate(('csv_exact_dedup','csv_trim','csv_to_json','csv_audit'))]
        for _ in orders:
            self.assertTrue(process_one(store))
        self.assertFalse(process_one(store))
        for service,order in orders:
            saved = store.get(order,'t'*32)
            self.assertEqual(saved['status'],'ready')
            self.assertEqual(saved['service_key'],service)
            self.assertEqual(saved['result']['service_key'],service)
            self.assertIn('download_sha256',saved['result'])
            self.assertEqual(saved['revenue_jpy'],0)

    def test_concurrent_legacy_and_new_queue_cannot_share_request_key(self):
        from concurrent.futures import ThreadPoolExecutor
        payload = self.service_payload(key='concurrent-key-1234')
        def submit(new):
            try:
                return self.services_rpc('submit',payload) if new else self.rpc('submit',payload)
            except subprocess.CalledProcessError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(submit,[True,False,True,False]))
        self.assertEqual(len(set(value for value in ids if value)),1)
        count = self.sql("select (select count(*) from company_x2.service_orders)+(select count(*) from company_x2.sandbox_orders);")
        self.assertEqual(int(count.stdout.strip()),1)

    def test_expired_lease_cannot_finish(self):
        order = self.submit()
        first = self.rpc('claim')
        self.sql(f"update company_x2.sandbox_orders set lease_until=now()-interval '1 second' where id='{order}';")
        second = self.rpc('claim')
        self.assertNotEqual(first['lease'],second['lease'])
        with self.assertRaises(subprocess.CalledProcessError):
            self.rpc('finish', {'id':order,'lease':first['lease'],'result':{}})
        self.rpc('finish', {'id':order,'lease':second['lease'],'result':{'csv':'a'}})

    def test_anonymous_role_cannot_execute(self):
        result = self.sql("set role anon; select public.cx2_store('ping');",check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('permission denied', result.stderr)

    def scout_rpc(self, action, payload=None):
        data = json.dumps(payload or {}).replace("'", "''")
        response = self.sql(f"set role service_role; select coalesce(public.cx2_scout('{action}','{data}'::jsonb),'null'::jsonb);")
        return json.loads(response.stdout.splitlines()[-1])

    def test_scout_lease_atomic_save_schedule_and_failure(self):
        lease = self.scout_rpc('claim')
        self.assertIsNone(self.scout_rpc('claim'))
        candidate = {'source':'github_public_bounty','external_id':'123','title':'CSV','decision':'blocked','reason':'unknown'}
        with self.assertRaises(subprocess.CalledProcessError):
            self.scout_rpc('finish', {'lease':lease,'items':[candidate,candidate],'report':{}})
        self.assertEqual(self.scout_rpc('snapshot')['status'], 'running')
        self.assertEqual(self.scout_rpc('snapshot')['items'], [])
        self.scout_rpc('finish', {'lease':lease,'items':[candidate],'report':{'collected':1}})
        self.assertEqual(len(self.scout_rpc('snapshot')['items']),1)
        self.assertIsNone(self.scout_rpc('claim'))
        self.sql("update company_x2.scout_state set next_run_at=now()-interval '1 second';")
        second = self.scout_rpc('claim')
        self.scout_rpc('finish', {'lease':second,'error':'Source unavailable','delay':300})
        saved = self.scout_rpc('snapshot')
        self.assertEqual(saved['status'],'retry_wait')
        self.assertIsNotNone(saved['last_success_at'])
        self.assertEqual(len(saved['items']),1)

    def test_scout_expired_worker_and_anonymous_cannot_publish(self):
        first = self.scout_rpc('claim')
        self.sql("update company_x2.scout_state set lease_until=now()-interval '1 second';")
        second = self.scout_rpc('claim')
        with self.assertRaises(subprocess.CalledProcessError):
            self.scout_rpc('finish', {'lease':first,'items':[],'report':{}})
        self.scout_rpc('finish', {'lease':second,'items':[],'report':{}})
        self.assertNotEqual(self.sql("set role anon; select public.cx2_scout('snapshot');",check=False).returncode,0)
        # The existing order RPC still uses schema 2.
        self.assertEqual(self.rpc('ping'), {'schema_version':2})
