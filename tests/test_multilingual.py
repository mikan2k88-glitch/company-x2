import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import test_company_http as http_tests
from test_sales import listing
from company_x2.sales import proposal

class LanguageTests(unittest.TestCase):
    def test_english_proposal_does_not_claim_live_payment_or_send(self):
        item=listing();draft=proposal([item],item['url'],'en')
        self.assertIn('No real payment',draft['message'])
        self.assertIn('permission',draft['message'])
        self.assertFalse(draft['sent']);self.assertIsNone(draft['live_quote_jpy'])
        with self.assertRaises(ValueError):proposal([item],item['url'],'unsupported')

    @unittest.skipUnless(shutil.which('node'),'Node runtime required for customer UI test')
    def test_customer_ui_language_switching_and_csv_preservation(self):
        subprocess.run([shutil.which('node'),str(Path(__file__).with_name('customer_i18n.test.cjs'))],check=True)

class LanguageHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call

    def test_public_pages_and_language_invitation_preserve_access_scope(self):
        for route in ('/services?lang=en','/intake?lang=en','/customer-i18n.js'):
            body=self.call(route,auth=False,decode=False)
            self.assertIn(b'customer',body)
        link=self.call('/api/company/intake-link',{'service_key':'csv_to_json','language':'en'})
        self.assertEqual(parse_qs(urlparse(link['url']).query),{'lang':['en']})
        self.assertIn('access',parse_qs(urlparse(link['url']).fragment))
        import urllib.error
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/intake/config',auth=False)

    def test_checkout_forwards_selected_language_without_changing_price(self):
        plan=self.call('/api/company/quote',{'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_test'})['plan']
        order=self.call('/api/company/transactions',{'service_key':'csv_to_json','csv':'id\n001\n','payment_mode':'stripe_test',
            'plan_sha256':plan['plan_sha256'],'terms_accepted':True,'request_key':'l'*32})['id']
        seen=[]
        original=self.payments.api
        def api(path,fields=None,**kwargs):
            seen.append(fields);return original(path,fields,**kwargs)
        self.payments.api=api
        self.call('/api/company/checkout',{'id':order,'return_path':'/intake','locale':'en'})
        self.assertEqual(seen[0]['locale'],'en')
        self.assertEqual(seen[0]['line_items[0][price_data][unit_amount]'],100)
        self.assertIn('CSV to JSON',seen[0]['line_items[0][price_data][product_data][name]'])
