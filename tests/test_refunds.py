import io
import json
import tempfile
import hashlib
import hmac
import time
import urllib.error
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

from company_x2.store import Store
from company_x2.company import quote,validate_creation,process_transaction
from company_x2.payments import Payments
from company_x2.refunds import process_one,webhook
from test_live_payments import ENV
import test_company_http as http_tests


class RefundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db');self.posts=[];self.history=[];self.response_status='pending'
        self.payments=Payments(ENV,self.opener)
        self.order=self.create()
    def create(self,mode='stripe_test',key='k'*32):
        price=300 if mode=='stripe_live' else None
        terms=ENV['SALES_TERMS_URL'] if price else None
        risk=dict(sensitive_data='no',critical_use='no',extra_liability='no')
        plan=quote('csv_to_json','id\n001\n',mode,price,terms,risk)
        payload=validate_creation({'csv':'id\n001\n','service_key':'csv_to_json','payment_mode':mode,
            'risk_context':risk,'request_key':key,'terms_accepted':True,'plan_sha256':plan['plan_sha256']},'t'*32,price,terms)
        order=self.store.company_rpc('create',payload)
        session='cs_live_fixture' if price else 'cs_test_fixture'
        self.store.company_rpc('session',{'id':order,'token_hash':payload['token_hash'],'session_id':session,'session_url':'https://checkout.stripe.com/c/pay/test'})
        self.session={'id':session,'livemode':bool(price),'amount_total':plan['price_jpy'],'currency':'jpy','mode':'payment',
            'status':'complete','payment_status':'paid','client_reference_id':order,'metadata':{'cx2_order_id':order},'payment_intent':'pi_fixture'}
        self.payments.reconcile_session(self.store,self.session,'evt_fixture')
        return order
    def refund(self,status='pending',amount=None,refund_id='re_fixture'):
        # Stripe Refund objects have no livemode attribute.
        return {'object':'refund','id':refund_id,'payment_intent':'pi_fixture',
            'currency':'jpy','amount':self.session['amount_total'] if amount is None else amount,'status':status}
    def opener(self,req,timeout):
        path=urlparse(req.full_url).path
        if path.startswith('/v1/checkout/sessions/'):
            value=self.session
        elif path.startswith('/v1/payment_intents/'):
            value={'id':'pi_fixture','livemode':self.session['livemode'],'currency':'jpy','amount_received':self.session['amount_total'],
                'status':'succeeded','latest_charge':{'id':'ch_fixture','livemode':self.session['livemode'],
                    'payment_intent':'pi_fixture','disputed':False,'amount_refunded':sum(x['amount'] for x in self.history if x['status']=='succeeded')}}
        elif path=='/v1/refunds' and req.data is not None:
            self.posts.append(req);value=self.refund(self.response_status);self.history=[value]
        elif path=='/v1/refunds':
            value={'object':'list','has_more':False,'data':self.history}
        elif path.startswith('/v1/refunds/'):
            value=self.history[0]
        else:raise AssertionError(req.full_url)
        return io.BytesIO(json.dumps(value).encode())
    def failed(self):
        with self.store.connect() as db:db.execute("update company_orders set status='failed' where id=?",(self.order,))
    def due(self):
        with self.store.connect() as db:db.execute("update company_refund_jobs set checked_at=datetime('now','-61 seconds')")
    def saved(self):
        return self.store.company_rpc('get',{'id':self.order,'token_hash':self.store.digest('t'*32)})
    def test_pending_to_success_replay_and_no_second_refund(self):
        self.failed();self.assertTrue(process_one(self.payments,self.store))
        self.assertEqual(self.saved()['refund']['state'],'pending')
        self.assertEqual(self.saved()['refund']['refunded_jpy'],0)
        self.assertEqual(self.posts[0].get_header('Idempotency-key'),'cx2-refund-'+self.order)
        self.assertEqual(self.posts[0].get_header('Authorization'),'Bearer sk_test_fixture')
        self.history=[self.refund('succeeded')];self.due()
        process_one(self.payments,self.store);self.assertEqual(len(self.posts),1)
        self.assertEqual(self.store.company_rpc('overview')['test_refunded_jpy'],100)
        event={'livemode':False,'data':{'object':{'id':'re_fixture'}}}
        webhook(self.payments,self.store,event);webhook(self.payments,self.store,event)
        self.assertEqual(sum(e['kind']=='refund_succeeded' for e in self.saved()['events']),1)
    def test_lost_response_and_restart_reconcile_provider_history(self):
        self.failed();original=self.payments.api
        def lost(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path=='refunds':raise ValueError('lost response')
            return result
        with patch.object(self.payments,'api',side_effect=lost):
            with self.assertRaises(ValueError):process_one(self.payments,self.store)
        self.due();process_one(Payments(ENV,self.opener),self.store)
        self.assertEqual(len(self.posts),1);self.assertEqual(self.saved()['refund']['state'],'pending')
    def test_deadline_from_payment_and_ready_exclusion(self):
        self.assertFalse(process_one(self.payments,self.store))
        with self.store.connect() as db:db.execute("update company_payment_events set created_at=datetime('now','-25 hours')")
        claim=self.store.company_rpc('claim');self.assertTrue(process_one(self.payments,self.store))
        with self.assertRaises(ValueError):self.store.company_rpc('finish',{'id':self.order,'lease':claim['lease'],'error':'late'})
    def test_ready_without_receipt_is_not_refunded(self):
        process_transaction(self.store)
        with self.store.connect() as db:db.execute("update company_payment_events set created_at=datetime('now','-25 hours')")
        self.assertFalse(process_one(self.payments,self.store));self.assertFalse(self.posts)
    def test_retry_exhaustion_retains_input_until_last_attempt(self):
        with patch('company_x2.company.produce',side_effect=ValueError('fixture failure')):
            for attempt in range(3):
                self.assertTrue(process_transaction(self.store))
                self.assertEqual(self.saved()['status'],'queued' if attempt<2 else 'failed')
        self.assertTrue(process_one(self.payments,self.store))
    def test_reservation_exclusive_and_free_unpaid_excluded(self):
        self.failed()
        with ThreadPoolExecutor(2) as pool:claims=list(pool.map(lambda _:self.store.company_rpc('refund_claim'),range(2)))
        self.assertEqual(sum(x is not None for x in claims),1)
    def test_failed_and_partial_refund_require_review(self):
        for status,amount in [('failed',100),('requires_action',100),('succeeded',20)]:
            with self.subTest(status=status):
                with self.store.connect() as db:
                    db.execute('delete from company_refunds');db.execute('delete from company_refund_jobs')
                self.failed();self.history=[self.refund(status,amount)]
                process_one(self.payments,self.store)
                self.assertEqual(self.saved()['refund']['state'],'review');self.assertFalse(self.posts)
    def test_cross_mode_amount_and_identity_rejected(self):
        evidence={'refund_id':'re_fixture','payment_intent':'pi_fixture','amount':100,'currency':'jpy','status':'succeeded','livemode':False}
        for change in ({'livemode':True},{'currency':'usd'},{'amount':101},{'amount':True},{'refund_id':'bad'}):
            with self.assertRaises(ValueError):self.store.company_rpc('refund_update',{**evidence,**change})
        self.assertFalse(self.store.company_rpc('refund_update',{**evidence,'payment_intent':'pi_otherapp'}))
        self.store.company_rpc('refund_update',evidence)
        with self.assertRaises(ValueError):self.store.company_rpc('refund_update',{**evidence,'refund_id':'re_second'})
        self.store.company_rpc('refund_update',{**evidence,'status':'pending'})
        self.assertEqual(self.saved()['refund']['state'],'succeeded')
    def test_live_disabled_sales_still_refunds_verified_order(self):
        with self.store.connect() as db:
            db.execute('delete from company_payment_bindings');db.execute('delete from company_payment_events')
            db.execute('delete from company_events');db.execute('delete from company_orders')
        self.order=self.create('stripe_live');self.payments.live_enabled=False;self.response_status='succeeded'
        self.failed();process_one(self.payments,self.store)
        self.assertEqual(self.posts[0].get_header('Authorization'),'Bearer sk_live_fixture')
        self.assertEqual(self.store.company_rpc('overview')['live_refunded_jpy'],300)
        self.assertEqual(self.store.company_rpc('overview')['test_refunded_jpy'],0)
    def test_wrong_provider_mode_does_not_refund(self):
        self.failed();self.session['livemode']=True
        with self.assertRaises(ValueError):process_one(self.payments,self.store)
        self.assertFalse(self.posts)

    def test_old_paid_ready_order_backfills_binding_and_manual_refund(self):
        process_transaction(self.store)
        with self.store.connect() as db:
            db.execute('delete from company_payment_bindings')
            db.execute("update company_orders set updated_at=datetime('now','-61 seconds')")
        self.history=[self.refund('succeeded')]
        self.assertTrue(process_one(self.payments,self.store))
        self.assertFalse(self.posts);self.assertEqual(self.saved()['refund']['refunded_jpy'],100)
        with self.assertRaises(ValueError):self.store.company_rpc('receipt',{'id':self.order,
            'token_hash':self.store.digest('t'*32),'download_sha256':self.saved()['result']['download_sha256']})


class RefundHTTPTests(unittest.TestCase):
    call=http_tests.CompanyHTTPTests.call
    tearDown=http_tests.CompanyHTTPTests.tearDown
    def setUp(self):
        http_tests.CompanyHTTPTests.setUp(self)
        chosen={'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_test'}
        plan=self.call('/api/company/quote',chosen)['plan']
        self.order=self.call('/api/company/transactions',{**chosen,'request_key':'r'*32,
            'terms_accepted':True,'plan_sha256':plan['plan_sha256']})['id']
        self.call('/api/company/checkout',{'id':self.order})
        self.session={'id':'cs_test_fixture','livemode':False,'amount_total':100,'currency':'jpy','mode':'payment',
            'status':'complete','payment_status':'paid','client_reference_id':self.order,
            'metadata':{'cx2_order_id':self.order},'payment_intent':'pi_http'}
        self.payments.reconcile_session(self.store,self.session,'evt_http')
        process_transaction(self.store)
        self.refund={'object':'refund','id':'re_http','payment_intent':'pi_http','amount':100,'currency':'jpy','status':'pending'}
        def opener(req,timeout):
            value=self.refund if '/refunds/' in req.full_url else {'id':'pi_http','livemode':False}
            return io.BytesIO(json.dumps(value).encode())
        self.payments.opener=opener
    def send(self,route='/api/payments/webhook',signature=True):
        raw=json.dumps({'id':'evt_refundHTTP','livemode':False,'type':'refund.updated',
            'data':{'object':{'id':'re_http','status':'pending'}}}).encode()
        stamp=int(time.time());digest=hmac.new(b'whsec_fixture',str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        return self.call(route,auth=False,raw=raw,headers={'Stripe-Signature':f't={stamp},v1={digest}' if signature else 'bad'})
    def test_signed_refund_latest_state_download_denial_and_duplicate(self):
        self.assertTrue(self.send()['refund_verified'])
        with self.assertRaises(urllib.error.HTTPError) as exc:self.call('/api/company/transactions/'+self.order+'/download')
        self.assertEqual(exc.exception.code,409)
        self.refund['status']='succeeded'
        self.send();self.send()
        self.assertEqual(self.call('/api/company/transactions/'+self.order)['refund']['state'],'succeeded')
        self.assertEqual(self.call('/api/company/status')['overview']['test_refunded_jpy'],100)
    def test_bad_signature_wrong_channel_and_wrong_amount_rejected(self):
        with self.assertRaises(urllib.error.HTTPError):self.send(signature=False)
        with self.assertRaises(urllib.error.HTTPError):self.send('/api/payments/live-webhook')
        self.refund['amount']=101
        with self.assertRaises(urllib.error.HTTPError):self.send()
