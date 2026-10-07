import unittest
from datetime import datetime, timezone
from urllib.parse import parse_qs
from company_x2.acquisition import organize, draft
from company_x2.payments import Payments
import test_company_http as http_tests


def lead(number='1', **changes):
    return {'source':'github_public_bounty','reason':'Supported CSV task','external_id':number,'url':'https://github.com/example/jobs/issues/'+number,
        'title':'Please convert the attached CSV data to JSON objects',
        'decision':'needs_review','service_keys':['csv_to_json'],'reward_mention':'$10',
        'source_updated_at':'2026-10-08T00:00:00Z',**changes}


class AcquisitionTests(unittest.TestCase):
    def test_groups_deduplicate_stale_unknown_and_never_promote_rejected(self):
        now=datetime(2026,10,8,12,tzinfo=timezone.utc)
        items=[lead(),lead('2'),lead('3',title='Old trim job',source_updated_at='2025-01-01T00:00:00Z'),
            lead('4',title='Date unknown job',source_updated_at=None),
            lead('5',title='Unsupported software job',decision='rejected'),
            lead('6',title='Assigned job',decision='blocked'),
            lead('7',title='Future timestamp job',source_updated_at='2099-01-01T00:00:00Z')]
        result=organize(items,now)
        self.assertEqual(result['summary'],{'review':1,'duplicate':1,'stale':1,'unknown_date':2,'unsupported':2})
        self.assertTrue(result['items'][0]['eligible_for_review'])
        self.assertTrue(all(not x['auto_bid_allowed'] and not x['execution_allowed'] for x in result['items']))
        duplicate=next(x for x in result['items'] if x['review_group']=='duplicate')
        self.assertEqual(duplicate['duplicate_of'],items[0]['url'])
    def test_same_url_short_title_duplicates_and_distinct_long_titles_survive(self):
        items=[lead(title='CSV'),lead(title='CSV'),lead('3',title='Distinct CSV to JSON export request from customer')]
        result=organize(items,datetime(2026,10,9,tzinfo=timezone.utc))
        self.assertEqual(result['summary']['duplicate'],1)
        self.assertEqual(result['summary']['review'],2)
    def test_draft_uses_saved_services_and_has_no_fabricated_price_or_rows(self):
        from datetime import timedelta
        item=lead(source_updated_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        result=draft([item],item['url'])
        self.assertTrue(result['draft_only'])
        self.assertFalse(result['reward_verified'])
        self.assertIsNone(result['options'][0]['live_quote_jpy'])
        self.assertNotIn('input_rows',result['options'][0])
        for change in ({'decision':'blocked'},{'source_updated_at':'2020-01-01T00:00:00Z'}):
            with self.assertRaises(ValueError):draft([{**item,**change}],item['url'])
        with self.assertRaises(ValueError):draft([item],'https://malicious.test/')
    def test_checkout_return_is_only_two_internal_paths(self):
        import io,json
        requests=[]
        def opener(req,timeout):
            requests.append(req)
            return io.BytesIO(json.dumps({'id':'cs_test_fixture','url':'https://checkout.stripe.com/c/pay/test','livemode':False}).encode())
        class Store:
            def company_rpc(self,*args):return True
        p=Payments({'STRIPE_SECRET_KEY':'sk_test_fixture','STRIPE_WEBHOOK_SECRET':'whsec_fixture','APP_PUBLIC_URL':'https://example.onrender.com'},opener)
        order={'id':'cx_fixture','status':'awaiting_payment','plan':{'payment_mode':'stripe_test','price_jpy':100,'service_name':'CSV'}}
        p.checkout(Store(),order,'a'*64,'/intake')
        body=parse_qs(requests[0].data.decode())
        self.assertEqual(body['success_url'],['https://example.onrender.com/intake?checkout=returned'])
        with self.assertRaises(ValueError):p.checkout(Store(),order,'a'*64,'https://malicious.test/')


class IntakeHTTPTests(unittest.TestCase):
    setUp = http_tests.CompanyHTTPTests.setUp
    tearDown = http_tests.CompanyHTTPTests.tearDown
    call = http_tests.CompanyHTTPTests.call
    order = http_tests.CompanyHTTPTests.order
    def test_intake_requires_auth_config_hides_admin_ledger_and_delivery_flow(self):
        self.assertIn('CSVの依頼受付',self.call('/intake',decode=False).decode())
        with self.assertRaises(Exception):self.call('/intake',auth=False)
        config=self.call('/api/intake/config')
        self.assertTrue(config['database_ready'])
        self.assertNotIn('overview',config)
        self.assertNotIn('ai',config)
        order,payload=self.order()
        process = __import__('company_x2.company',fromlist=['process_transaction']).process_transaction
        self.assertTrue(process(self.store))
        self.assertEqual(self.call('/api/company/transactions/'+order)['status'],'ready')
    def test_saved_lead_draft_and_unknown_source_rejected(self):
        from datetime import timedelta
        item=lead(source_updated_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat())
        lease=self.store.claim_scan()
        self.store.finish_scan(lease,items=[item],report={'collected':1},delay=3600)
        self.assertEqual(self.call('/api/company/candidates')['summary']['review'],1)
        result=self.call('/api/company/lead-draft',{'source_url':item['url'],'service_key':'fake'})
        self.assertEqual(result['options'][0]['service_key'],'csv_to_json')
        with self.assertRaises(Exception):self.call('/api/company/lead-draft',{'source_url':'https://github.com/example/jobs/issues/99'})
