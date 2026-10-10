import base64
import hashlib
import hmac
import io
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from company_x2.company import process_transaction
from company_x2.payments import Payments
from company_x2.server import handler_for
from company_x2.store import Store


class CompanyHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.store=Store(Path(self.directory.name)/'db')
        def opener(req,timeout):
            return io.BytesIO(json.dumps({'id':'cs_test_fixture','url':'https://checkout.stripe.com/c/pay/test','livemode':False}).encode())
        self.payments=Payments({'STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture',
                                'APP_PUBLIC_URL':'https://example.onrender.com'},opener)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.store,'admin',access_password='password',payments=self.payments))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.directory.cleanup()
    def call(self,path,data=None,owner='t'*32,auth=True,raw=None,headers=None,decode=True):
        # Existing flow fixtures represent low-risk synthetic input. Explicitly
        # supplied contexts (including None) are preserved for rejection tests.
        if path in ('/api/company/quote','/api/company/transactions') and isinstance(data,dict) and 'risk_context' not in data:
            data={**data,'risk_context':dict(sensitive_data='no',critical_use='no',extra_liability='no')}
        h={'Content-Type':'application/json','X-Order-Token':owner}
        if auth:h['Authorization']='Basic '+base64.b64encode(b'user:password').decode()
        h.update(headers or {})
        with urllib.request.urlopen(urllib.request.Request(self.base+path,
            data=raw if raw is not None else json.dumps(data).encode() if data is not None else None,headers=h),timeout=3) as response:
            body=response.read()
            return json.loads(body) if decode else body
    def order(self,mode='sandbox',key='k'*32):
        payload={'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':mode}
        plan=self.call('/api/company/quote',payload)['plan']
        payload.update(plan_sha256=plan['plan_sha256'],terms_accepted=True,request_key=key)
        return self.call('/api/company/transactions',payload)['id'],payload
    def test_http_contract_production_download_digest_and_receipt(self):
        self.assertIn(b'E20',self.call('/company',decode=False))
        order,payload=self.order()
        self.assertEqual(self.call('/api/company/transactions',payload)['id'],order)
        process_transaction(self.store)
        saved=self.call('/api/company/transactions/'+order)
        self.assertNotIn('content',saved['result']['artifact'])
        raw=self.call('/api/company/transactions/'+order+'/download',decode=False)
        self.assertEqual(json.loads(raw),[{'id':'001'}])
        digest=hashlib.sha256(raw).hexdigest()
        self.assertEqual(digest,saved['result']['download_sha256'])
        self.call('/api/company/receipt',{'id':order,'download_sha256':digest})
        self.assertEqual(self.call('/api/company/transactions/'+order)['status'],'delivered')
        for path in ('/company','/api/company/status','/api/company/transactions/'+order+'/download'):
            with self.assertRaises(urllib.error.HTTPError) as error:self.call(path,auth=False)
            self.assertEqual(error.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/company/transactions/'+order,owner='w'*32)
        self.assertEqual(error.exception.code,404)
    def test_signed_webhook_without_basic_auth_starts_only_paid_test_order(self):
        order,_=self.order('stripe_test')
        self.call('/api/company/checkout',{'id':order})
        self.assertFalse(process_transaction(self.store))
        event={'id':'evt_fixture','livemode':False,'type':'checkout.session.completed','data':{'object':{
            'id':'cs_test_fixture','livemode':False,'mode':'payment','status':'complete','payment_status':'paid',
            'amount_total':100,'currency':'jpy','metadata':{'cx2_order_id':order},'client_reference_id':order}}}
        raw=json.dumps(event).encode();timestamp=int(time.time())
        signature=hmac.new(b'whsec_fixture',str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        headers={'Stripe-Signature':f't={timestamp},v1={signature}'}
        self.assertTrue(self.call('/api/payments/webhook',raw=raw,headers=headers,auth=False)['verified'])
        self.call('/api/payments/webhook',raw=raw,headers=headers,auth=False)
        self.assertTrue(process_transaction(self.store));self.assertFalse(process_transaction(self.store))
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/payments/webhook',raw=raw+b' ',headers=headers,auth=False)
        self.assertEqual(error.exception.code,400)
        self.assertEqual(self.call('/api/company/status')['overview']['real_revenue_jpy'],0)
    def test_input_tampering_and_ai_without_consent_are_rejected(self):
        order,payload=self.order()
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/transactions',{**payload,'csv':'id\n999\n'})
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/ai',{'request':'convert'})
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/quote',{'service_key':[],'csv':'a\n1\n'})

    def test_external_signed_intake_download_and_receipt(self):
        from company_x2 import autonomy
        from company_x2.intake_access import issue
        contact='ot_'+'b'*32;source='https://github.com/example/tasks/issues/1'
        self.store.outreach_rpc('prepare',{'id':contact,'url':source,'issue_id':'65','author':'requester','message':'synthetic fixture'})
        self.store.outreach_rpc('claim');self.store.outreach_rpc('finish',{'id':contact,'comment_url':source+'#issuecomment-9'})
        self.store.outreach_rpc('observe',{'id':contact,'reply_id':42,'reply_text':autonomy.FREE+' '+autonomy.AI,'next_message':'fixture'})
        token,_=issue('password',contact_id=contact)
        headers={'X-Intake-Access':token}
        payload={'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'sandbox','source_url':'https://wrong.example/'}
        plan=self.call('/api/company/quote',payload,auth=False,headers=headers)['plan']
        payload.update(plan_sha256=plan['plan_sha256'],terms_accepted=True,request_key='linked-http-fixture')
        order=self.call('/api/company/transactions',payload,auth=False,headers=headers)['id']
        self.assertTrue(process_transaction(self.store))
        raw=self.call('/api/company/transactions/'+order+'/download',auth=False,headers=headers,decode=False)
        self.assertEqual(json.loads(raw),[{'id':'001'}])
        self.call('/api/company/receipt',{'id':order,'download_sha256':hashlib.sha256(raw).hexdigest()},auth=False,headers=headers)
        saved=self.call('/api/company/transactions/'+order,auth=False,headers=headers)
        self.assertEqual(saved['status'],'delivered')
        persisted=self.store.company_rpc('get',{'id':order,'token_hash':self.store.digest('t'*32)})
        self.assertEqual(persisted['source_url'],source)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/autonomy',auth=False,headers=headers)
        diagnosis=self.call('/api/company/autonomy')
        self.assertEqual(diagnosis['endpoint'],'E35');self.assertIn('attention',diagnosis['operations'])

