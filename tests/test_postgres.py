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
        result = subprocess.run(['psql', DSN, '-X', '-A', '-t', '-v', 'ON_ERROR_STOP=1', '-c', query],
            capture_output=True, text=True, check=False)
        if check and result.returncode:
            raise subprocess.CalledProcessError(result.returncode, 'psql', output=result.stdout, stderr=result.stderr)
        return result

    @classmethod
    def setUpClass(cls):
        cls.sql("create role anon; create role authenticated; create role service_role;")
        migration = Path('supabase/migrations/002_sandbox_rpc.sql').read_text()
        cls.sql(migration)
        cls.sql(Path('supabase/migrations/003_public_scout.sql').read_text())
        cls.sql(Path('supabase/migrations/004_data_services.sql').read_text())
        cls.sql(Path('supabase/migrations/009_company.sql').read_text())
        cls.sql(Path('supabase/migrations/009_company.sql').read_text())
        cls.sql(Path('supabase/migrations/019_live_payments.sql').read_text())
        cls.sql(Path('supabase/migrations/019_live_payments.sql').read_text())

    def setUp(self):
        self.sql('truncate company_x2.company_payment_events,company_x2.company_events,company_x2.company_orders,company_x2.company_ai_calls cascade;')
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

    def company_rpc(self, action, payload=None):
        data=json.dumps(payload or {}).replace("'","''")
        response=self.sql(f"set role service_role; select coalesce(public.cx2_company('{action}','{data}'::jsonb),'null'::jsonb);")
        return json.loads(response.stdout.splitlines()[-1])

    def company_create(self, mode='sandbox', key='company-request-key'):
        from company_x2.company import quote,validate_creation
        plan=quote('csv_to_json','id\n001\n',mode)
        payload=validate_creation({'csv':'id\n001\n','service_key':'csv_to_json','payment_mode':mode,
            'terms_accepted':True,'request_key':key,'plan_sha256':plan['plan_sha256']},'t'*32)
        return self.company_rpc('create',payload),payload

    def test_company_real_sql_adapter_production_receipt_and_permissions(self):
        import io
        from company_x2.company import process_transaction
        from company_x2.supabase_store import SupabaseStore
        def opener(req,timeout):
            payload=json.loads(req.data)
            result=self.company_rpc(payload['p_action'],payload['p_payload'])
            return io.BytesIO(json.dumps(result).encode())
        store=SupabaseStore('https://example.supabase.co','sb_secret_fixture',opener=opener)
        self.assertEqual(store.company_rpc('ping'),{'schema_version':9})
        order,payload=self.company_create()
        self.assertEqual(self.company_rpc('create',payload),order)
        self.assertTrue(process_transaction(store));self.assertFalse(process_transaction(store))
        saved=store.company_rpc('get',{'id':order,'token_hash':store.digest('t'*32)})
        self.assertEqual(saved['status'],'ready')
        self.assertEqual(json.loads(saved['result']['artifact']['content']),[{'id':'001'}])
        self.assertIsNone(store.company_rpc('get',{'id':order,'token_hash':'a'*64}))
        store.company_rpc('receipt',{'id':order,'token_hash':store.digest('t'*32),'download_sha256':saved['result']['download_sha256']})
        self.assertEqual(store.company_rpc('get',{'id':order,'token_hash':store.digest('t'*32)})['status'],'delivered')
        self.assertEqual(store.company_rpc('overview')['real_revenue_jpy'],0)
        for role in ('anon','authenticated'):
            self.assertNotEqual(self.sql(f"set role {role}; select public.cx2_company('overview');",check=False).returncode,0)
            self.assertNotEqual(self.sql(f"set role {role}; select * from company_x2.company_orders;",check=False).returncode,0)

    def test_company_payment_mismatch_replay_and_unpaid_queue(self):
        order,payload=self.company_create('stripe_test')
        self.assertIsNone(self.company_rpc('claim'))
        self.company_rpc('session',{'id':order,'token_hash':payload['token_hash'],
            'session_id':'cs_test_fixture','session_url':'https://checkout.stripe.com/c/pay/test'})
        evidence={'id':order,'session_id':'cs_test_fixture','event_id':'evt_fixture','fingerprint':'a'*64,
                  'amount':100,'currency':'jpy','livemode':False,'payment_status':'paid'}
        for change in ({'amount':1},{'livemode':True},{'currency':'usd'},{'session_id':None}):
            with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('payment',{**evidence,**change})
        self.company_rpc('payment',evidence);self.company_rpc('payment',evidence)
        with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('payment',{**evidence,'fingerprint':'b'*64})
        self.assertEqual(self.company_rpc('claim')['id'],order)
        self.assertIsNone(self.company_rpc('claim'))
        self.assertEqual(self.company_rpc('overview')['test_payments_jpy'],100)
        self.assertEqual(self.company_rpc('overview')['real_revenue_jpy'],0)

    def test_live_payment_mode_price_and_receipt_ledger(self):
        from company_x2.company import quote,validate_creation
        plan=quote('csv_to_json','id\n001\n','stripe_live',300,'https://example.com/terms')
        payload=validate_creation({'csv':'id\n001\n','service_key':'csv_to_json','payment_mode':'stripe_live',
            'terms_accepted':True,'request_key':'live-key-1234567890','plan_sha256':plan['plan_sha256']},'t'*32,300,'https://example.com/terms')
        order=self.company_rpc('create',payload)
        self.assertEqual(self.company_rpc('live_ping'),{'live_schema_version':19})
        with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('session',{'id':order,'token_hash':payload['token_hash'],
            'session_id':'cs_test_wrong','session_url':'https://checkout.stripe.com/c/pay/test'})
        self.company_rpc('session',{'id':order,'token_hash':payload['token_hash'],'session_id':'cs_live_fixture','session_url':'https://checkout.stripe.com/c/pay/live'})
        proof={'id':order,'session_id':'cs_live_fixture','event_id':'evt_livesql','fingerprint':'a'*64,
            'amount':300,'currency':'jpy','livemode':True,'payment_status':'paid'}
        for change in ({'amount':299},{'livemode':False},{'currency':'usd'}):
            with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('payment',{**proof,**change})
        self.company_rpc('payment',proof);self.company_rpc('payment',proof)
        self.assertEqual(self.company_rpc('overview')['live_collected_jpy'],300)
        self.assertEqual(self.company_rpc('overview')['test_payments_jpy'],0)
        self.assertEqual(self.company_rpc('overview')['real_revenue_jpy'],0)
        from company_x2.company import process_transaction
        from company_x2.supabase_store import SupabaseStore
        import io,json
        def opener(req,timeout):
            body=json.loads(req.data);return io.BytesIO(json.dumps(self.company_rpc(body['p_action'],body['p_payload'])).encode())
        store=SupabaseStore('https://example.supabase.co','sb_secret_test',opener=opener)
        self.assertTrue(process_transaction(store))
        saved=self.company_rpc('get',{'id':order,'token_hash':payload['token_hash']})
        self.company_rpc('receipt',{'id':order,'token_hash':payload['token_hash'],'download_sha256':saved['result']['download_sha256']})
        self.assertEqual(self.company_rpc('overview')['real_revenue_jpy'],300)

    def test_company_budget_concurrency_and_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        payload={'request_hash':'a'*64,'month':'2026-10','day':'2026-10-06','reserve':100,'month_limit':100,'day_limit':100}
        with ThreadPoolExecutor(2) as pool:
            answers=list(pool.map(lambda _:self.company_rpc('ai_reserve',payload),range(2)))
        self.assertEqual(sum(a['reserved'] for a in answers),1)
        with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('ai_reserve',{**payload,'request_hash':'b'*64})
        self.company_rpc('ai_finish',{'request_hash':'a'*64,'result':{'supported':False}})
        self.assertEqual(self.company_rpc('ai_reserve',payload)['result'],{'supported':False})
        order,_=self.company_create()
        first=self.company_rpc('claim')
        self.sql(f"update company_x2.company_orders set lease_until=now()-interval '1 second' where id='{order}';")
        second=self.company_rpc('claim')
        self.assertNotEqual(first['lease'],second['lease'])
        with self.assertRaises(subprocess.CalledProcessError):self.company_rpc('finish',{'id':order,'lease':first['lease'],'error':'late'})
        self.sql(f"update company_x2.company_orders set lease_until=now()-interval '1 second',attempts=3 where id='{order}';")
        self.assertIsNone(self.company_rpc('claim'))
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
