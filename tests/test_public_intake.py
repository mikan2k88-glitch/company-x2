import hashlib
import tempfile
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from company_x2 import public_intake as public
from company_x2.company import quote, process_transaction
from company_x2.intake_access import public_issue, public_valid, public_permits
from company_x2.store import Store
from company_x2.supabase_store import StorageUnavailable
import test_company_http as http_tests

def request(key):
    risk=dict(sensitive_data='no',critical_use='no',extra_liability='no')
    plan=quote('csv_to_json','id\n001\n',risk_context=risk)
    return {'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'sandbox',
        'risk_context':risk,'plan_sha256':plan['plan_sha256'],'terms_accepted':True,'request_key':key}

class PublicQuotaTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.path=Path(self.directory.name)/'db';self.store=Store(self.path)
    def tearDown(self):self.directory.cleanup()

    def test_concurrent_global_limit_and_restart(self):
        def create(n):
            try:return public.create(self.store,request(str(n).zfill(32)),str(n).zfill(32))
            except public.LimitReached:return None
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(create,range(16)))
        self.assertEqual(sum(bool(x) for x in results),10)
        other=Store(self.path)
        with self.assertRaises(public.LimitReached):public.create(other,request('z'*32),'z'*32)
        self.assertEqual(public.summary(other)['totals']['accepted'],10)

    def test_owner_limit_replay_cross_day_and_conflicts(self):
        payload=request('a'*32);owner='o'*32
        with patch.object(public,'day',return_value='2026-10-09'):
            order=public.create(self.store,payload,owner)
            self.assertEqual(public.create(self.store,payload,owner),order)
            public.create(self.store,request('b'*32),owner)
            with self.assertRaises(public.LimitReached):public.create(self.store,request('c'*32),owner)
        with patch.object(public,'day',return_value='2026-10-10'):
            self.assertEqual(public.create(self.store,payload,owner),order)
            self.assertEqual(public.summary(self.store)['totals']['reserved'],2)
            with self.assertRaises(ValueError):public.create(self.store,payload,'x'*32)

    def test_fail_closed_limits_and_no_customer_data_in_metrics(self):
        with patch.object(self.store,'save_opportunity',side_effect=StorageUnavailable('offline')):
            with self.assertRaises(StorageUnavailable):public.create(self.store,request('a'*32),'o'*32)
        self.assertEqual(self.store.company_rpc('overview')['counts'],{})
        with self.assertRaises(ValueError):public.check_input({'csv':'a\n'+'x\n'*1001})
        with self.assertRaises(ValueError):public.check_input({'csv':'a'*50001})
        with self.assertRaises(ValueError):public.check_input({'csv':'a\n','payment_mode':'stripe_test'})
        with patch.object(self.store,'opportunities',return_value=[{}]*100):
            with self.assertRaises(public.LimitReached):public.start(self.store,'o'*32)
        for n in range(30):public.start(self.store,'o'*32)
        with self.assertRaises(public.LimitReached):public.start(self.store,'o'*32)

    def test_public_plan_and_minute_rate_limits(self):
        from collections import deque
        with patch.object(public,'REQUESTS',deque()),patch.object(public.time,'monotonic',return_value=10):
            for _ in range(120):public.check_rate()
            with self.assertRaises(public.LimitReached):public.check_rate()
            with patch.object(public.time,'monotonic',return_value=71):public.check_rate()
        for _ in range(60):public.reserve_quote(self.store,{'csv':'id\n001\n'})
        with self.assertRaises(public.LimitReached):public.reserve_quote(self.store,{'csv':'id\n001\n'})

    def test_grant_bound_to_owner_expiry_and_scope(self):
        token,expiry=public_issue('secret','o'*32,now=100)
        self.assertTrue(public_valid(token,'secret','o'*32,now=100))
        self.assertFalse(public_valid(token,'secret','x'*32,now=100))
        self.assertFalse(public_valid(token+'x','secret','o'*32,now=100))
        self.assertFalse(public_valid(token,'secret','o'*32,now=expiry))
        for path in ('/api/company/checkout','/api/company/ai','/api/company/intake-link','/api/company/agent-scout'):
            self.assertFalse(public_permits('POST',path))

class PublicHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call

    def test_trial_info_and_content_free_private_report(self):
        from test_free_trial import settings
        with patch.dict('os.environ',settings()):
            info=self.call('/api/public/trial',auth=False)
            self.assertEqual(info['orders_per_day'],3);self.assertTrue(info['open'])
            access=self.call('/api/public/start',{},auth=False)['access']
            headers={'X-Intake-Access':access}
            data=request('trial-http-request-key')
            order=self.call('/api/company/transactions',data,auth=False,headers=headers)['id']
            process_transaction(self.store)
            report=self.call('/api/company/free-trial')
            self.assertEqual(report['totals']['ready'],1)
            self.assertNotIn(order,str(report));self.assertEqual(set(report['services']),{'csv_to_json'})
            with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/free-trial',auth=False,headers=headers)

    def test_public_start_to_verified_delivery_without_admin_or_invitation(self):
        self.call('/api/public/visit',{'request_key':'v'*32},auth=False)
        self.call('/api/public/visit',{'request_key':'v'*32},auth=False)
        start=self.call('/api/public/start',{},auth=False)
        def customer(path,data=None,owner='t'*32):
            return self.call(path,data,auth=False,owner=owner,headers={'X-Intake-Access':start['access']})
        config=customer('/api/intake/config')
        self.assertTrue(config['public_free']);self.assertFalse(config['payments_ready'])
        for path,data in [('/api/company/sales',None),('/api/company/public-intake',None),
            ('/api/company/checkout',{}),('/api/company/ai',{}),('/api/company/intake-link',{})]:
            with self.assertRaises(urllib.error.HTTPError):customer(path,data)
        with self.assertRaises(urllib.error.HTTPError):customer('/api/intake/config',owner='x'*32)
        data=request('r'*32)
        plan=customer('/api/company/quote',{k:v for k,v in data.items() if k in ('csv','service_key','payment_mode')})['plan']
        data['plan_sha256']=plan['plan_sha256']
        order=customer('/api/company/transactions',data)['id']
        self.assertEqual(customer('/api/company/transactions',data)['id'],order)
        self.assertTrue(process_transaction(self.store))
        result=customer('/api/company/transactions/'+order)
        self.assertEqual(result['status'],'ready')
        artifact=self.call('/api/company/transactions/'+order+'/download',auth=False,decode=False,headers={'X-Intake-Access':start['access']})
        digest=hashlib.sha256(artifact).hexdigest();self.assertEqual(digest,result['result']['download_sha256'])
        customer('/api/company/receipt',{'id':order,'download_sha256':digest})
        customer('/api/company/receipt',{'id':order,'download_sha256':digest})
        counts=self.call('/api/company/public-intake')['totals']
        self.assertEqual(counts['visits'],1);self.assertEqual(counts['accepted'],1);self.assertEqual(counts['delivered'],1)

    def test_public_limits_are_enforced_on_api_not_only_ui(self):
        access=self.call('/api/public/start',{},auth=False)['access']
        def customer(path,data):return self.call(path,data,auth=False,headers={'X-Intake-Access':access})
        with self.assertRaises(urllib.error.HTTPError):customer('/api/company/quote',{'service_key':'csv_trim','csv':'a\n','payment_mode':'stripe_test'})
        for n in range(2):customer('/api/company/transactions',request(str(n).zfill(32)))
        with self.assertRaises(urllib.error.HTTPError) as error:customer('/api/company/transactions',request('q'*32))
        self.assertEqual(error.exception.code,429)
