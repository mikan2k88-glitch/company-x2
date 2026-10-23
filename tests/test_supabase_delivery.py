import io
import json
import unittest
import urllib.error
from company_x2.supabase_store import SupabaseStore,StorageUnavailable


class SupabaseDeliveryTests(unittest.TestCase):
    def test_dedicated_transport_and_malformed_claim_never_falls_back(self):
        seen=[]
        def opener(req,timeout):
            body=json.loads(req.data);seen.append((req.full_url,body))
            result={'delivery_schema_version':1} if body['p_action']=='ping' else {'lease':'invalid'}
            return io.BytesIO(json.dumps(result).encode())
        store=SupabaseStore('https://example.supabase.co','sb_secret_synthetic',opener=opener)
        journal=store.delivery_journal()
        with self.assertRaises(ValueError):journal.claim('a'*64,allowed=True)
        self.assertEqual([body['p_action'] for _,body in seen],['ping','claim'])
        self.assertTrue(all(url.endswith('/cx2_delivery') for url,_ in seen))
        self.assertEqual(seen[-1][1]['p_payload'],{'identity':'a'*64})

    def test_missing_rpc_and_wrong_schema_fail_closed(self):
        def missing(req,timeout):
            raise urllib.error.HTTPError(req.full_url,404,'missing',{},io.BytesIO(b'synthetic-private-body'))
        store=SupabaseStore('https://example.supabase.co','sb_secret_synthetic',opener=missing)
        with self.assertRaises(StorageUnavailable) as error:store.delivery_journal()
        self.assertIn('20261023114445_delivery_journal.sql',str(error.exception))
        self.assertNotIn('synthetic-private-body',str(error.exception))
        store.opener=lambda req,timeout:io.BytesIO(b'{"delivery_schema_version":2}')
        with self.assertRaises(StorageUnavailable):store.delivery_journal()
