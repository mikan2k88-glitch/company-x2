import hashlib
import hmac
import io
import json
import time
import unittest
import urllib.error
from urllib.parse import parse_qs, urlparse
from company_x2.payments import Payments
from company_x2.company import process_transaction
import test_company_http as http_tests

ENV={'STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture',
    'STRIPE_LIVE_SECRET_KEY':'sk_live_fixture','STRIPE_LIVE_WEBHOOK_SECRET':'whsec_live_fixture',
    'APP_PUBLIC_URL':'https://example.onrender.com','LIVE_PAYMENTS_ENABLED':'true',
    'LIVE_PRICE_JPY':'300','LIVE_SALES_TERMS_CONFIRMED':'true','SALES_TERMS_URL':'https://example.onrender.com/terms'}

class LiveHTTPTests(unittest.TestCase):
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call
    def setUp(self):
        http_tests.CompanyHTTPTests.setUp(self)
        self.seen=[]
        def opener(req,timeout):
            self.seen.append(req)
            return io.BytesIO(json.dumps({'id':'cs_live_fixture','url':'https://checkout.stripe.com/c/pay/live','livemode':True}).encode())
        self.payments.__dict__.update(Payments(ENV,opener).__dict__)

    def test_live_channel_payment_to_delivery_and_test_evidence_isolation(self):
        # Exercise the legacy live lifecycle in isolation. The production policy
        # gate is covered separately and cannot be enabled by environment values.
        self.payments.live_status=lambda store=None: {'ready':True,'mode':'stripe_live','price_jpy':300,
            'terms_url':ENV['SALES_TERMS_URL'],'schema_ready':True,'reasons':[]}
        link=self.call('/api/company/intake-link',{'service_key':'csv_to_json','payment_mode':'stripe_live'})
        access=parse_qs(urlparse(link['url']).fragment)['access'][0]
        def customer(path,data=None):return self.call(path,data,auth=False,headers={'X-Intake-Access':access})
        self.assertTrue(customer('/api/intake/config')['live_payments_ready'])
        chosen={'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_live',
            'risk_context':dict(sensitive_data='no',critical_use='no',extra_liability='no')}
        plan=customer('/api/company/quote',chosen)['plan']
        self.assertEqual(plan['price_jpy'],300);self.assertEqual(plan['sales_terms_url'],ENV['SALES_TERMS_URL'])
        payload={**chosen,'plan_sha256':plan['plan_sha256'],'terms_accepted':True,'request_key':'l'*32}
        order=customer('/api/company/transactions',payload)['id']
        self.assertFalse(process_transaction(self.store))
        customer('/api/company/checkout',{'id':order,'return_path':'/intake','locale':'en'})
        fields=parse_qs(self.seen[-1].data.decode())
        self.assertEqual(fields['line_items[0][price_data][unit_amount]'],['300'])
        self.assertNotIn('TEST',fields['line_items[0][price_data][product_data][name]'][0])
        self.assertEqual(self.seen[-1].get_header('Authorization'),'Bearer sk_live_fixture')
        session={'id':'cs_live_fixture','livemode':True,'mode':'payment','status':'complete','payment_status':'paid',
            'amount_total':300,'currency':'jpy','client_reference_id':order,'metadata':{'cx2_order_id':order}}
        def webhook(value,route='/api/payments/live-webhook'):
            raw=json.dumps({'id':'evt_e19live','type':'checkout.session.completed','livemode':True,'data':{'object':value}}).encode()
            stamp=int(time.time());signature=hmac.new(ENV['STRIPE_LIVE_WEBHOOK_SECRET'].encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
            return self.call(route,auth=False,raw=raw,headers={'Stripe-Signature':f't={stamp},v1={signature}'})
        for change in ({'livemode':False},{'amount_total':301},{'currency':'usd'},{'id':'cs_test_fixture'}):
            with self.assertRaises(urllib.error.HTTPError):webhook({**session,**change})
        with self.assertRaises(urllib.error.HTTPError):webhook(session,'/api/payments/webhook')
        self.assertFalse(process_transaction(self.store))
        # Disabling new sales does not block incoming evidence for existing orders.
        self.payments.live_enabled=False
        self.assertTrue(webhook(session)['verified']);self.assertTrue(webhook(session)['verified'])
        self.assertTrue(process_transaction(self.store))
        saved=customer('/api/company/transactions/'+order)
        self.assertEqual(saved['status'],'ready')
        overview=self.store.company_rpc('overview')
        self.assertEqual(overview['live_collected_jpy'],300);self.assertEqual(overview['test_payments_jpy'],0)
        self.assertEqual(overview['real_revenue_jpy'],0)
        customer('/api/company/receipt',{'id':order,'download_sha256':saved['result']['download_sha256']})
        self.assertEqual(self.store.company_rpc('overview')['real_revenue_jpy'],300)
        self.assertEqual(sum(x['kind']=='live_payment_verified' for x in customer('/api/company/transactions/'+order)['events']),1)

    def test_readiness_and_existing_test_invitation_cannot_charge_live(self):
        for key,value in [('LIVE_PAYMENTS_ENABLED','false'),('LIVE_PRICE_JPY',''),('LIVE_SALES_TERMS_CONFIRMED','false'),
            ('STRIPE_LIVE_SECRET_KEY','sk_test_wrong'),('STRIPE_LIVE_WEBHOOK_SECRET',''),('SALES_TERMS_URL','https://other.example/terms')]:
            self.assertFalse(Payments({**ENV,key:value}).live_status(self.store)['ready'])
        class MissingSchema:
            def company_rpc(self,*args):raise ValueError('missing')
        self.assertFalse(Payments(ENV).live_status(MissingSchema())['ready'])
        link=self.call('/api/company/intake-link',{'service_key':'csv_to_json'})
        grant=parse_qs(urlparse(link['url']).fragment)['access'][0]
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/quote',{'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_live'},auth=False,headers={'X-Intake-Access':grant})

    def test_live_provider_response_is_rejected_on_test_channel(self):
        with self.assertRaises(ValueError):self.payments.api('checkout/sessions')
