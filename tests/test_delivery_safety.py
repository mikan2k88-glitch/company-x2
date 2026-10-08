import hashlib
import json
import unittest
import urllib.error
from company_x2.company import process_transaction, quote
from company_x2.delivery_safety import inspect_input
import test_company_http as http_tests

SAFE=dict(sensitive_data='no',critical_use='no',extra_liability='no')


class ContentSafetyTests(unittest.TestCase):
    def test_contact_credentials_formula_and_control_values_are_rejected(self):
        for text in ('email\nx\n','id\nuser@example.com\n','id\nsk_live_example123456\n',
                     'id\n=HYPERLINK("bad")\n','id\n\t+cmd\n','id\n\x00\n','住所\nx\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                inspect_input(text)
        self.assertEqual(inspect_input('id\n001\n')['input_sha256'],hashlib.sha256(b'id\n001\n').hexdigest())


class DeliverySafetyHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call
    order=http_tests.CompanyHTTPTests.order

    def test_approved_output_is_available_but_changed_artifact_is_held(self):
        order,_=self.order()
        self.assertTrue(process_transaction(self.store))
        self.assertTrue(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        with self.store.connect() as db:
            row=db.execute('select result from company_orders where id=?',(order,)).fetchone()
            result=json.loads(row['result'])
            result['artifact']['content']='[{"id":"changed"}]'
            db.execute('update company_orders set result=? where id=?',(json.dumps(result),order))
        self.assertFalse(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('/api/company/transactions/'+order+'/download')
        self.assertEqual(error.exception.code,409)
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/company/receipt',{'id':order,'download_sha256':result['download_sha256']})
        self.assertEqual(self.call('/api/company/transactions/'+order)['status'],'ready')

    def test_input_changed_after_acceptance_never_gets_a_deliverable(self):
        order,_=self.order()
        with self.store.connect() as db:
            db.execute('update company_orders set input=? where id=?',('id\n=bad\n',order))
        for _ in range(3):
            process_transaction(self.store)
        saved=self.call('/api/company/transactions/'+order)
        self.assertFalse(saved['delivery_allowed'])
        self.assertIsNone(saved['result'])
        with self.assertRaises(urllib.error.HTTPError):
            self.call('/api/company/transactions/'+order+'/download')

    def test_legacy_unchecked_plan_cannot_be_delivered(self):
        order,_=self.order()
        process_transaction(self.store)
        with self.store.connect() as db:
            row=db.execute('select plan from company_orders where id=?',(order,)).fetchone()
            plan=json.loads(row['plan']);plan.pop('input_safety')
            db.execute('update company_orders set plan=? where id=?',(json.dumps(plan),order))
        self.assertFalse(self.call('/api/company/transactions/'+order)['delivery_allowed'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('/api/company/transactions/'+order+'/download')
        self.assertEqual(error.exception.code,409)

    def test_false_declaration_does_not_override_input_scan(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('/api/company/quote',dict(service_key='csv_to_json',csv='email\nuser@example.com\n',risk_context=SAFE))
        self.assertEqual(error.exception.code,400)
