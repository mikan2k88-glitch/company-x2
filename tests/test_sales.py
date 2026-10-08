import hashlib
import hmac
import json
import time
import unittest
import urllib.error
from urllib.parse import urlparse,parse_qs
from datetime import datetime,timezone
from company_x2.sales import assess,proposal
from company_x2.intake_access import issue,valid,permits,LIFETIME
from company_x2.company import process_transaction
import test_company_http as http_tests

def listing(**changes):
    return {'url':'https://github.com/example/jobs/issues/1','title':'Please convert CSV to JSON for $10',
        'description':'Please convert my CSV to JSON objects.','external_id':'1','decision':'needs_review',
        'service_keys':['csv_to_json'],'reward_mention':'$10','source_updated_at':datetime.now(timezone.utc).isoformat(),**changes}

class SalesTests(unittest.TestCase):
    def test_examples_are_not_customer_orders(self):
        for data in [listing(title='docs(cli): Serbian quickstart (US$25 bounty proposal)',description='Writing sample: CSV audit. Requested reward, not a funded offer.'),
            listing(title='B2B monetization gaps',description='CSV audit. $112M earnings of competitors.'),
            listing(title='CSV deduplication work offer',description='This is a seller work offer. I will deliver for 2 USDC.')]:
            self.assertFalse(assess([data])['items'][0]['sales_candidate'])
            with self.assertRaises(ValueError):proposal([data],data['url'])

    def test_scope_candidate_requires_terms_and_has_no_live_price(self):
        data=listing();report=assess([data])
        self.assertEqual(report['summary']['scope_candidate'],1)
        draft=proposal([data],data['url'])
        self.assertFalse(draft['sent']);self.assertIsNone(draft['live_quote_jpy'])
        self.assertIn('AI',draft['message']);self.assertGreaterEqual(len(draft['missing_evidence']),5)
        self.assertFalse(report['items'][0]['auto_contact_allowed'])

    def test_deadline_evidence_and_estimate(self):
        now=datetime(2026,10,8,tzinfo=timezone.utc)
        data=listing(description='Please convert CSV to JSON.\nDeadline: 2026-10-09\nPayment: $10 after delivery\nAI work allowed',source_updated_at=now.isoformat())
        facts=assess([data],now)['items'][0]['sales_evidence']
        self.assertEqual(facts['deadline_date'],'2026-10-09')
        self.assertFalse(facts['verified'])
        self.assertIn('$10',facts['quotes']['payment_terms'])
        estimate=proposal([listing()],data['url'])['estimate']
        self.assertIsNone(estimate['live_amount'])
        self.assertFalse(estimate['deadline_committed'])
        self.assertEqual(estimate['options'][0]['service_key'],'csv_to_json')
        expired=assess([dict(data,description='Please convert CSV to JSON. Deadline: 2026-10-07')],now)
        self.assertEqual(expired['summary']['scope_candidate'],0)
        self.assertTrue(expired['items'][0]['sales_evidence']['deadline_expired'])

    def test_ambiguous_deadline_and_duplicates(self):
        data=listing(description='Please convert CSV to JSON. Deadline: next week. AI prohibited.')
        report=assess([data,data])
        self.assertEqual(report['evaluated_count'],2)
        self.assertEqual(report['summary']['scope_candidate'],1)
        self.assertEqual(report['summary']['excluded'],1)
        self.assertIsNone(report['items'][0]['sales_evidence']['deadline_date'])
        self.assertFalse(report['items'][0]['auto_contact_allowed'])
        self.assertTrue(report['exclusion_reasons'])

    def test_grant_expiry_tampering_rotation_and_scopes(self):
        token,expiry=issue('secret-key',now=100)
        self.assertTrue(valid(token,'secret-key',now=100))
        self.assertFalse(valid(token,'secret-key',now=expiry))
        self.assertFalse(valid(token+'x','secret-key',now=100))
        self.assertFalse(valid(token,'rotated-key',now=100))
        for path in ('/company','/api/company/sales','/api/company/intake-link','/api/company/ai','/api/company/agent-scout'):
            self.assertFalse(permits('POST',path))

class CustomerFlowTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call

    def test_customer_test_payment_to_delivery_without_admin_password(self):
        link=self.call('/api/company/intake-link',{'service_key':'csv_to_json'})
        grant=parse_qs(urlparse(link['url']).fragment)['access'][0]
        def customer(path,data=None,owner='c'*32):
            return self.call(path,data,auth=False,owner=owner,headers={'X-Intake-Access':grant})
        self.assertTrue(customer('/api/intake/config')['database_ready'])
        for path,data in [('/api/company/status',None),('/api/company/sales',None),
            ('/api/company/ai',{'request':'analyze','ai_terms_accepted':True}),
            ('/api/company/intake-link',{'service_key':'csv_trim'})]:
            with self.assertRaises(urllib.error.HTTPError):customer(path,data)
        inputs={'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_test'}
        plan=customer('/api/company/quote',inputs)['plan']
        payload={**inputs,'plan_sha256':plan['plan_sha256'],'terms_accepted':True,'request_key':'r'*32}
        order=customer('/api/company/transactions',payload)['id']
        self.assertEqual(customer('/api/company/transactions',payload)['id'],order)
        customer('/api/company/checkout',{'id':order,'return_path':'/intake'})
        self.assertFalse(process_transaction(self.store))
        event={'id':'evt_intakescope','livemode':False,'type':'checkout.session.completed','data':{'object':{
            'id':'cs_test_fixture','livemode':False,'mode':'payment','status':'complete','payment_status':'paid',
            'amount_total':100,'currency':'jpy','metadata':{'cx2_order_id':order},'client_reference_id':order}}}
        raw=json.dumps(event).encode();timestamp=int(time.time())
        signature=hmac.new(b'whsec_fixture',str(timestamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
        try:
            self.call('/api/payments/webhook',raw=raw,auth=False,headers={'Stripe-Signature':f't={timestamp},v1={signature}'})
        except urllib.error.HTTPError as exc:
            self.fail(exc.read().decode())
        self.assertTrue(process_transaction(self.store))
        with self.assertRaises(urllib.error.HTTPError):customer('/api/company/transactions/'+order,owner='o'*32)
        saved=customer('/api/company/transactions/'+order)
        artifact=self.call('/api/company/transactions/'+order+'/download',auth=False,owner='c'*32,
            headers={'X-Intake-Access':grant},decode=False)
        self.assertEqual(json.loads(artifact),[{'id':'001'}])
        digest=hashlib.sha256(artifact).hexdigest();self.assertEqual(digest,saved['result']['download_sha256'])
        customer('/api/company/receipt',{'id':order,'download_sha256':digest})
        self.assertEqual(customer('/api/company/transactions/'+order)['status'],'delivered')

    def test_invalid_invite_and_live_payment_cannot_be_used(self):
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.call('/api/intake/config',auth=False,headers={'X-Intake-Access':'wrong'})
        self.assertEqual(denied.exception.code,401)
        link=self.call('/api/company/intake-link',{'service_key':'csv_trim'})
        grant=parse_qs(urlparse(link['url']).fragment)['access'][0]
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/company/quote',{'service_key':'csv_trim','csv':'id\n1\n','payment_mode':'live'},
                auth=False,headers={'X-Intake-Access':grant})

