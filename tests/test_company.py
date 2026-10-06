import hashlib
import hmac
import io
import json
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from company_x2.ai_planner import AIPlanner
from company_x2.company import quote, validate_creation, process_transaction, rank_candidates, company_status
from company_x2.payments import Payments
from company_x2.store import Store

ENV = {'STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture','APP_PUBLIC_URL':'https://example.onrender.com'}


class CompanyTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.directory.name)/'db')
        self.token='t'*32
    def tearDown(self):
        self.directory.cleanup()
    def create(self, service='csv_to_json', mode='sandbox', key='k'*32):
        plan=quote(service,'id\n001\n001\n',mode)
        payload=validate_creation({'service_key':service,'csv':'id\n001\n001\n','payment_mode':mode,
            'request_key':key,'terms_accepted':True,'plan_sha256':plan['plan_sha256']},self.token)
        return self.store.company_rpc('create',payload),payload
    def saved(self,order):
        return self.store.company_rpc('get',{'id':order,'token_hash':self.store.digest(self.token)})
    def test_all_services_complete_persist_and_verify_receipt(self):
        for index,service in enumerate(('csv_exact_dedup','csv_trim','csv_to_json','csv_audit')):
            order,_=self.create(service,key=str(index)*32)
            process_transaction(Store(self.store.path))
            saved=self.saved(order)
            self.assertEqual(saved['status'],'ready')
            self.assertEqual(saved['revenue_jpy'],0)
            digest=saved['result']['download_sha256']
            with self.assertRaises(ValueError):
                self.store.company_rpc('receipt',{'id':order,'token_hash':self.store.digest(self.token),'download_sha256':'bad'})
            self.store.company_rpc('receipt',{'id':order,'token_hash':self.store.digest(self.token),'download_sha256':digest})
            self.store.company_rpc('receipt',{'id':order,'token_hash':self.store.digest(self.token),'download_sha256':digest})
            self.assertEqual(self.saved(order)['status'],'delivered')
            self.assertEqual(sum(e['kind']=='client_receipt_confirmed' for e in self.saved(order)['events']),1)
    def test_creation_rejects_changed_plan_owner_and_live_mode(self):
        order,payload=self.create()
        self.assertEqual(self.store.company_rpc('create',payload),order)
        with self.assertRaises(ValueError):
            self.store.company_rpc('create',{**payload,'token_hash':'a'*64})
        self.assertIsNone(self.store.company_rpc('get',{'id':order,'token_hash':'a'*64}))
        for mode in ('live','stripe_live'):
            with self.assertRaises(ValueError):quote('csv_to_json','a\n1\n',mode)
    def test_atomic_claim_and_expired_worker_retry_limit(self):
        order,_=self.create()
        with ThreadPoolExecutor(2) as pool:
            claims=list(pool.map(lambda _:self.store.company_rpc('claim'),range(2)))
        self.assertEqual(sum(c is not None for c in claims),1)
        first=next(c for c in claims if c)
        with self.store.connect() as db:db.execute('update company_orders set lease_until=0 where id=?',(order,))
        second=self.store.company_rpc('claim')
        with self.assertRaises(ValueError):self.store.company_rpc('finish',{'id':order,'lease':first['lease'],'error':'late'})
        with self.store.connect() as db:db.execute('update company_orders set lease_until=0,attempts=3 where id=?',(order,))
        self.assertIsNone(self.store.company_rpc('claim'))
        self.assertEqual(self.saved(order)['status'],'failed')
    def test_test_payment_unlocks_only_matching_order_and_is_idempotent(self):
        order,_=self.create(mode='stripe_test')
        self.assertFalse(process_transaction(self.store))
        self.store.company_rpc('session',{'id':order,'token_hash':self.store.digest(self.token),
            'session_id':'cs_test_fixture','session_url':'https://checkout.stripe.com/c/pay/fixture'})
        evidence={'id':order,'session_id':'cs_test_fixture','event_id':'evt_fixture','fingerprint':'a'*64,
                  'amount':100,'currency':'jpy','livemode':False,'payment_status':'paid'}
        for change in ({'livemode':True},{'amount':1},{'currency':'usd'},{'session_id':'cs_test_other'},{'payment_status':'unpaid'}):
            with self.assertRaises(ValueError):self.store.company_rpc('payment',{**evidence,**change})
        self.store.company_rpc('payment',evidence);self.store.company_rpc('payment',evidence)
        with self.assertRaises(ValueError):self.store.company_rpc('payment',{**evidence,'fingerprint':'b'*64})
        self.assertTrue(process_transaction(self.store))
        self.assertFalse(process_transaction(self.store))
        overview=self.store.company_rpc('overview')
        self.assertEqual(overview['test_payments_jpy'],100)
        self.assertEqual(overview['real_revenue_jpy'],0)
    def test_budget_atomic_month_day_and_no_double_reserve(self):
        payload={'request_hash':'a'*64,'month':'2026-10','day':'2026-10-06','reserve':100,'month_limit':100,'day_limit':100}
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.store.company_rpc('ai_reserve',payload),range(2)))
        self.assertEqual(sum(r['reserved'] for r in results),1)
        with self.assertRaises(ValueError):self.store.company_rpc('ai_reserve',{**payload,'request_hash':'b'*64})
        with self.assertRaises(ValueError):self.store.company_rpc('ai_reserve',{**payload,'request_hash':'c'*64,'day':'2026-10-07'})
        self.store.company_rpc('ai_finish',{'request_hash':'a'*64,'result':{'supported':False}})
        self.assertEqual(self.store.company_rpc('ai_reserve',payload)['result'],{'supported':False})
    def test_listing_ranking_never_grants_execution_or_payment_evidence(self):
        items=rank_candidates([{'external_id':'2','service_keys':['csv_trim'],'reward_mention':'$10','decision':'needs_review'},
                               {'external_id':'1','service_keys':[],'decision':'rejected'}])
        self.assertEqual(items[0]['external_id'],'2')
        self.assertFalse(items[0]['execution_allowed']);self.assertFalse(items[0]['auto_bid_allowed'])


class ProviderTests(unittest.TestCase):
    def event(self,order='cx_fixture'):
        return {'id':'evt_fixture','livemode':False,'type':'checkout.session.completed','data':{'object':{
            'id':'cs_test_fixture','livemode':False,'mode':'payment','status':'complete','payment_status':'paid',
            'amount_total':100,'currency':'jpy','metadata':{'cx2_order_id':order},'client_reference_id':order}}}
    def test_webhook_signature_exact_body_timestamp_rotation_and_live_rejection(self):
        payments=Payments(ENV)
        raw=json.dumps(self.event()).encode();timestamp=1000
        digest=hmac.new(b'whsec_fixture',b'1000.'+raw,hashlib.sha256).hexdigest()
        signature='t=1000,v1='+'0'*64+',v1='+digest
        self.assertEqual(payments.signed_event(raw,signature,now=1000)['id'],'evt_fixture')
        for body,header,now in [(raw+b' ',signature,1000),(raw,signature,1301),(raw,'t=1000,v1=bad',1000),
                               (raw,signature+',t=1000',1000)]:
            with self.assertRaises(ValueError):payments.signed_event(body,header,now=now)
        live=json.dumps({**self.event(),'livemode':True}).encode()
        digest=hmac.new(b'whsec_fixture',b'1000.'+live,hashlib.sha256).hexdigest()
        with self.assertRaises(ValueError):payments.signed_event(live,'t=1000,v1='+digest,now=1000)
    def test_checkout_idempotency_provider_url_and_test_only_keys(self):
        captured=[]
        def opener(request,timeout):
            captured.append(request)
            return io.BytesIO(json.dumps({'id':'cs_test_fixture','url':'https://checkout.stripe.com/c/pay/test','livemode':False}).encode())
        class Fake:
            def company_rpc(self,*args):return True
        order={'id':'cx_fixture','status':'awaiting_payment','plan':{'payment_mode':'stripe_test','price_jpy':100,'service_name':'CSV'}}
        payments=Payments(ENV,opener)
        self.assertEqual(payments.checkout(Fake(),order,'a'*64)['id'],'cs_test_fixture')
        self.assertEqual(captured[0].get_header('Idempotency-key'),'cx2-checkout-cx_fixture')
        self.assertNotIn('token',captured[0].data.decode())
        self.assertFalse(Payments({**ENV,'STRIPE_SECRET_KEY':'sk_live_notallowed'}).status()['ready'])
        self.assertFalse(Payments({**ENV,'APP_PUBLIC_URL':'https://user:pass@example.com'}).status()['ready'])
    def test_unpaid_or_irrelevant_webhooks_do_not_claim_payment(self):
        payments=Payments(ENV)
        class Fake:
            def company_rpc(self,*args):raise AssertionError('must not store')
        event=self.event();event['data']['object']['payment_status']='unpaid'
        self.assertTrue(payments.apply_event(Fake(),event)['ignored'])
        self.assertTrue(payments.apply_event(Fake(),{'type':'unrelated'})['ignored'])
    def test_provider_errors_do_not_expose_secret_or_customer_body(self):
        def opener(*args,**kwargs):raise RuntimeError('sk_test_secret customer email')
        with self.assertRaises(ValueError) as error:Payments(ENV,opener).api('checkout/sessions/test')
        self.assertNotIn('secret',str(error.exception));self.assertNotIn('email',str(error.exception))
    def test_ai_structured_request_cached_reservation_and_no_csv_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db');requests=[]
            decision={'service_key':'csv_to_json','single_supported_operation':True,'has_extra_conditions':False,'reason':'Single conversion'}
            def opener(req,timeout):
                requests.append(json.loads(req.data))
                return io.BytesIO(json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(decision)}]}]}).encode())
            ai=AIPlanner({'OPENAI_API_KEY':'test-key','AI_ENABLED':'true','AI_MONTHLY_BUDGET_MICRO_USD':'3000000',
                          'AI_DAILY_BUDGET_MICRO_USD':'100000'},opener)
            answer=ai.analyze(store,'Please convert my CSV to JSON','t'*32)
            self.assertTrue(answer['supported'])
            self.assertEqual(ai.analyze(store,'Please convert my CSV to JSON','t'*32),answer)
            self.assertEqual(len(requests),1);self.assertFalse(requests[0]['store']);self.assertNotIn('tools',requests[0])
            self.assertEqual(requests[0]['input'],'Please convert my CSV to JSON')
    def test_ai_invalid_or_timeout_retains_budget_and_never_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'db');calls=[]
            def opener(*args,**kwargs):calls.append(1);raise TimeoutError('secret')
            ai=AIPlanner({'OPENAI_API_KEY':'test','AI_ENABLED':'true','AI_MONTHLY_BUDGET_MICRO_USD':'3000000',
                          'AI_DAILY_BUDGET_MICRO_USD':'100000'},opener)
            for _ in range(2):
                with self.assertRaises(ValueError):ai.analyze(store,'Convert data','t'*32)
            self.assertEqual(len(calls),1)
            self.assertGreater(store.company_rpc('overview')['ai_reserved_micro_usd'],0)
    def test_ai_unconfigured_never_calls_provider(self):
        ai=AIPlanner({},lambda *a,**k:(_ for _ in ()).throw(AssertionError('network')))
        with self.assertRaises(ValueError):ai.analyze(None,'convert','t'*32)
