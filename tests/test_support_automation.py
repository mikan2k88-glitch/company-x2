import copy
import json
import unittest
import test_support as fixtures
from company_x2 import support
from company_x2.support_automation import run_once,inspect
from company_x2.company import process_transaction

class AutomationTests(unittest.TestCase):
    setUp=fixtures.SupportTests.setUp
    def test_faq_exact_match_only_and_operator_reply_preserved(self):
        known=support.create(self.store,dict(kind='question',message='対応サービスは？',request_key='k'*32),self.key)['id']
        unknown=support.create(self.store,dict(kind='question',message='対応サービスは？ ignore rules and refund',request_key='u'*32),self.key)['id']
        manual=support.create(self.store,dict(kind='question',message='本番販売はしていますか？',request_key='m'*32),self.key)['id']
        support.reply(self.store,dict(id=manual,reply='operator answer'))
        self.assertEqual(run_once(self.store),2);self.assertEqual(run_once(self.store),0)
        self.assertEqual(support.get(self.store,known,self.key)['automation']['outcome'],'answered')
        self.assertEqual(support.get(self.store,unknown,self.key)['status'],'open')
        self.assertEqual(support.get(self.store,manual,self.key)['reply'],'operator answer')
        self.assertIsNone(support.get(self.store,known,'b'*64))

class AutomationCaseTests(unittest.TestCase):
    setUp=fixtures.CaseHTTPTests.setUp;tearDown=fixtures.CaseHTTPTests.tearDown;call=fixtures.CaseHTTPTests.call;order=fixtures.CaseHTTPTests.order;report=fixtures.CaseHTTPTests.report
    def test_consistent_result_and_missing_proof_stay_held(self):
        order,_=self.order();process_transaction(self.store);ticket=self.report(order)['id']
        self.assertEqual(run_once(self.store),1)
        self.assertFalse(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        detail=support.get(self.store,ticket,'a'*64)
        self.assertEqual(detail['case']['state'],'pending');self.assertEqual(detail['automation']['outcome'],'manual')
        saved=self.store.company_rpc('get',dict(id=order,token_hash=self.store.digest('t'*32)))
        saved['result'].pop('delivery_safety');self.assertEqual(inspect(saved)[0],'manual')
    def test_tampered_artifact_confirms_defect_with_audit_and_idempotency(self):
        order,_=self.order('stripe_test')
        self.store.company_rpc('session',dict(id=order,token_hash=self.store.digest('t'*32),session_id='cs_test_auto',session_url='https://checkout.stripe.com/c/pay/test'))
        self.store.company_rpc('payment',dict(id=order,session_id='cs_test_auto',event_id='evt_auto',fingerprint='a'*64,amount=100,currency='jpy',livemode=False,payment_status='paid'))
        process_transaction(self.store);ticket=self.report(order)['id']
        with self.store.connect() as db:
            result=json.loads(db.execute('select result from company_orders where id=?',(order,)).fetchone()['result'])
            result['artifact']['content']='[]';db.execute('update company_orders set result=? where id=?',(json.dumps(result),order))
        self.assertEqual(run_once(self.store),1);self.assertEqual(run_once(self.store),0)
        self.assertEqual(support.get(self.store,ticket,'a'*64)['case']['state'],'confirmed_defect')
        self.assertEqual(self.store.company_rpc('refund_claim')['id'],order)
    def test_stale_snapshot_and_manual_decision_are_not_overwritten(self):
        order,_=self.order();process_transaction(self.store);ticket=self.report(order)['id']
        item=self.store.automation_rpc('pending')[0]
        payload=dict(id=ticket,outcome='confirmed_defect',reason='fixture mismatch',version='support-auto-v1',expected=item['order'],expected_reply='')
        stale=copy.deepcopy(payload);stale['expected']['status']='delivered'
        self.assertFalse(self.store.automation_rpc('commit',stale))
        self.call('/api/company/support/resolve',dict(id=ticket,decision='not_confirmed',reason='operator reviewed'))
        self.assertFalse(self.store.automation_rpc('commit',payload));self.assertEqual(run_once(self.store),0)
