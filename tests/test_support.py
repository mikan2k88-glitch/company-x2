import tempfile
import unittest
import urllib.error
from pathlib import Path
from company_x2.store import Store
from company_x2 import support
from company_x2.company import process_transaction
import test_company_http as http_tests

class SupportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'db');self.key='a'*64
    def test_replay_owner_isolation_quota_and_durable_reply(self):
        data=dict(kind='question',message='サービスの範囲を確認したい',request_key='request-key-0001')
        ticket=support.create(self.store,data,self.key)['id']
        self.assertEqual(support.create(self.store,data,self.key)['id'],ticket)
        self.assertIsNone(support.get(self.store,ticket,'b'*64))
        with self.assertRaises(ValueError):support.create(self.store,{**data,'message':'different'},self.key)
        support.reply(self.store,{'id':ticket,'reply':'対応範囲は計画で確認してください'})
        self.assertEqual(support.get(Store(self.store.path),ticket,self.key)['status'],'answered')
        for n in (2,3):support.create(self.store,{**data,'request_key':'request-key-'+str(n).zfill(4)},self.key)
        with self.assertRaises(ValueError):support.create(self.store,{**data,'request_key':'request-key-0009'},self.key)
    def test_invalid_tokens_and_kinds_do_not_create_tickets(self):
        for kind in ([],None,'other'):
            with self.assertRaises(ValueError):support.create(self.store,dict(kind=kind,message='test',request_key='k'*32),self.key)
        with self.assertRaises(ValueError):support.create(self.store,dict(kind='question',message='test',request_key='k'*32),'short')
        self.assertEqual(self.store.support_rpc('list'),[])

class CaseHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call
    order=http_tests.CompanyHTTPTests.order
    def report(self,order,key='k'*32,owner='t'*32):
        return self.call('/api/support/tickets',dict(kind='defect',order_id=order,message='成果物の範囲を確認してください',request_key=key),auth=False,owner=owner,headers={'X-Support-Token':'a'*64})
    def test_report_holds_delivery_and_reply_alone_does_not_release(self):
        order,_=self.order();process_transaction(self.store)
        with self.assertRaises(urllib.error.HTTPError):self.report(order,owner='w'*32)
        self.assertTrue(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        ticket=self.report(order)['id'];self.assertEqual(self.report(order)['id'],ticket)
        self.assertFalse(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        with self.assertRaises(urllib.error.HTTPError) as error:self.call('/api/company/transactions/'+order+'/download')
        self.assertEqual(error.exception.code,409)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/support/resolve',dict(id=ticket,decision='not_confirmed',reason='確認済み'),auth=False)
        self.call('/api/company/support/reply',dict(id=ticket,reply='確認しています'))
        self.assertFalse(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        decision=dict(id=ticket,decision='not_confirmed',reason='範囲と成果物の検査記録が一致しました')
        self.call('/api/company/support/resolve',decision)
        self.call('/api/company/support/resolve',decision)
        self.assertTrue(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        detail=self.call('/api/support/tickets/'+ticket,auth=False,headers={'X-Support-Token':'a'*64})
        self.assertEqual([x['kind'] for x in detail['case']['history']],['reported','not_confirmed'])
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/support/tickets/'+ticket,auth=False,headers={'X-Support-Token':'b'*64})
    def test_confirmed_defect_enqueues_full_refund_only_for_paid_order(self):
        order,_=self.order('stripe_test')
        self.store.company_rpc('session',dict(id=order,token_hash=self.store.digest('t'*32),session_id='cs_test_fixture',session_url='https://checkout.stripe.com/c/pay/test'))
        self.store.company_rpc('payment',dict(id=order,session_id='cs_test_fixture',event_id='evt_support',fingerprint='a'*64,amount=100,currency='jpy',livemode=False,payment_status='paid'))
        process_transaction(self.store)
        ticket=self.report(order)['id']
        self.assertIsNone(self.store.company_rpc('refund_claim'))
        decision=dict(id=ticket,decision='confirmed_defect',reason='合意した範囲への不適合を検査で確認しました')
        self.assertTrue(self.call('/api/company/support/resolve',decision)['refund_requested'])
        self.call('/api/company/support/resolve',decision)
        self.assertEqual(self.store.company_rpc('refund_claim')['id'],order)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/support/resolve',{**decision,'decision':'not_confirmed'})
    def test_general_refund_message_never_places_order_on_hold(self):
        order,_=self.order();process_transaction(self.store)
        self.call('/api/support/tickets',dict(kind='refund',message='返金について質問',request_key='k'*32),auth=False,headers={'X-Support-Token':'a'*64})
        self.assertTrue(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        self.assertIsNone(self.store.company_rpc('refund_claim'))
