import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from company_x2.store import Store
from company_x2.owned_work import SOURCE,scope
from company_x2.supabase_store import SupabaseStore,StorageUnavailable


class OwnedLookupTests(unittest.TestCase):
    def test_customer_replay_status_and_receipt_never_use_global_list(self):
        from unittest.mock import patch
        from company_x2 import template_customer
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');owner='t'*40
            data=dict(request_key='synthetic-replay-001',purpose='Prepare template',csv='sku\n001\n',
                columns=['SKU'],mapping={'SKU':'sku'},risk_context=dict(
                    sensitive_data='no',critical_use='no',extra_liability='no'))
            record=template_customer.request(store,data,owner)
            data.update(accepted=True,approval_sha256=record['approval_sha256'])
            result=template_customer.process(store,data,owner)
            with store.connect() as db:db.execute("update opportunities set created_at='2000-01-01'")
            for n in range(120):store.save_opportunity(dict(source='other',external_id=str(n)),'blocked','synthetic')
            with patch.object(store,'opportunities',side_effect=AssertionError('Global list must not be used')):
                self.assertEqual(template_customer.status(store,owner)['items'][0]['status'],'ready')
                self.assertEqual(template_customer.status(store,'u'*40)['items'],[])
                self.assertEqual(template_customer.request(store,data,owner)['status'],'ready')
                self.assertEqual(template_customer.process(store,data,owner)['csv'],result['csv'])
                self.assertEqual(template_customer.receive(store,dict(request_key=data['request_key'],accepted=True,
                    artifact_sha256=result['artifact_sha256']),owner)['status'],'received')

    def test_old_owned_record_survives_global_limit_and_owner_isolation(self):
        owner='a'*64;key='synthetic-work-001'
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db')
            row=dict(source=SOURCE,external_id=scope(owner,key),owner_hash=owner,client_key=key,status='ready')
            store.save_opportunity(row,'blocked','metadata')
            with store.connect() as db:
                db.execute("update opportunities set created_at='2000-01-01'")
            for n in range(120):store.save_opportunity(dict(source='other',external_id=str(n)),'blocked','synthetic')
            self.assertFalse(any(r.get('owner_hash')==owner for r in store.opportunities()))
            self.assertEqual(store.customer_work(owner,key)[0]['client_key'],key)
            self.assertEqual(len(store.customer_work(owner)),1)
            self.assertEqual(store.customer_work('b'*64,key),[])
            with self.assertRaises(ValueError):store.customer_work(owner,"' OR true")

    def test_cloud_scope_validation_and_missing_rpc_do_not_fallback(self):
        calls=[]
        def opener(req,timeout):
            calls.append(req.full_url)
            return io.BytesIO(b'[]')
        store=SupabaseStore('https://example.supabase.co','sb_secret_synthetic',opener=opener)
        self.assertEqual(store.customer_work('a'*64,'synthetic-work-001'),[])
        self.assertTrue(calls[0].endswith('/cx2_owned_work'))
        with self.assertRaises(ValueError):store.customer_work('invalid')
        self.assertEqual(len(calls),1)
        def missing(req,timeout):raise urllib.error.HTTPError(req.full_url,404,'missing',{},io.BytesIO(b'private'))
        store.opener=missing
        with self.assertRaisesRegex(StorageUnavailable,'20261028135635'):store.customer_work('a'*64)
        store.opener=lambda req,timeout:io.BytesIO(json.dumps([dict(source=SOURCE,owner_hash='b'*64)]).encode())
        with self.assertRaises(ValueError):store.customer_work('a'*64)
