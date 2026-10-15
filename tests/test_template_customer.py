import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from company_x2.store import Store
from company_x2 import template_customer as customer, public_intake


class CustomerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'db')
        self.owner = 'a' * 40
        self.other = 'b' * 40
        self.data = dict(request_key='customer-request-001', purpose='Prepare product template',
                         csv='sku,title\n001,Example\n', columns=['SKU'], mapping={'SKU': 'sku'},
                         risk_context=dict(sensitive_data='no', critical_use='no', extra_liability='no'))

    def tearDown(self):
        self.temp.cleanup()

    def test_owner_isolation_same_key_and_shared_quota(self):
        first = customer.request(self.store, self.data, self.owner)
        for key in ('owner_hash', 'source', 'external_id', 'client_key', 'experimental'):
            self.assertNotIn(key, first)
        customer.request(self.store, self.data, self.owner)
        second = customer.request(self.store, self.data, self.other)
        self.assertEqual(len(public_intake.load(self.store)['tickets']), 2)
        self.assertEqual(len([r for r in self.store.opportunities() if r.get('source') == customer.SOURCE]), 2)
        data = {**self.data, 'accepted': True, 'approval_sha256': first['approval_sha256']}
        artifact = customer.process(self.store, data, self.owner)
        with self.assertRaises(ValueError):
            customer.receive(self.store, dict(request_key=self.data['request_key'], accepted=True,
                             artifact_sha256=artifact['artifact_sha256']), self.other)
        self.assertEqual(second['status'], 'awaiting_consent')

    def test_stop_blocks_processing_but_allows_receipt(self):
        first = customer.request(self.store, self.data, self.owner)
        data = {**self.data, 'accepted': True, 'approval_sha256': first['approval_sha256']}
        artifact = customer.process(self.store, data, self.owner)
        with patch('company_x2.free_trial.require_open', side_effect=ValueError('closed')):
            self.assertEqual(customer.process(self.store, data, self.owner)['csv'], artifact['csv'])
            self.assertEqual(customer.receive(self.store, dict(request_key=self.data['request_key'],
                accepted=True, artifact_sha256=artifact['artifact_sha256']), self.owner)['status'], 'received')

    def test_unresolved_questions_do_not_consume_orders(self):
        preview = customer.request(self.store, {**self.data, 'mapping': {}}, self.owner)
        self.assertEqual(preview['status'], 'needs_information')
        self.assertFalse(preview['reserved'])
        self.assertEqual(len(public_intake.load(self.store)['tickets']), 0)
        self.assertFalse(customer.OwnedStore(self.store, self.owner).opportunities())
        customer.request(self.store, self.data, self.owner)
        self.assertEqual(len(public_intake.load(self.store)['tickets']), 1)

    def test_stop_blocks_new_processing(self):
        first = customer.request(self.store, self.data, self.owner)
        with patch('company_x2.free_trial.require_open', side_effect=ValueError('closed')):
            with self.assertRaises(ValueError):
                customer.process(self.store, {**self.data, 'accepted': True,
                    'approval_sha256': first['approval_sha256']}, self.owner)

    def test_storage_failure_and_invalid_key_do_not_execute(self):
        with self.assertRaises(ValueError):
            customer.request(self.store, {**self.data, 'request_key': 'short'}, self.owner)
        self.assertEqual(len(public_intake.load(self.store)['tickets']), 0)
        with patch.object(self.store, 'save_opportunity', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                customer.request(self.store, self.data, self.owner)
        self.assertFalse(customer.OwnedStore(self.store, self.owner).opportunities())

    def test_received_retrieval_preserves_receipt_and_hides_identifiers(self):
        first = customer.request(self.store, self.data, self.owner)
        data = {**self.data, 'accepted': True, 'approval_sha256': first['approval_sha256']}
        artifact = customer.process(self.store, data, self.owner)
        customer.receive(self.store, dict(request_key=self.data['request_key'], accepted=True,
            artifact_sha256=artifact['artifact_sha256']), self.owner)
        with patch('company_x2.free_trial.require_open', side_effect=ValueError('closed')):
            self.assertEqual(customer.process(self.store, data, self.owner)['csv'], artifact['csv'])
            with self.assertRaises(ValueError):
                customer.process(self.store, {**data, 'csv': 'sku,title\n002,Changed\n'}, self.owner)
        state = customer.status(self.store, self.owner)
        self.assertEqual(state['items'][0]['status'], 'received')
        self.assertEqual(customer.status(self.store, self.other)['items'], [])
        for forbidden in ('owner_hash', 'source', 'client_key', 'Example', self.owner):
            self.assertNotIn(forbidden, json.dumps(state))

    def test_previews_share_quote_counter_and_fail_closed(self):
        suggested = customer.suggestion(self.store, {**self.data, 'template_csv':'商品コード\n'}, self.owner)
        self.assertEqual(suggested['mapping'], {'商品コード':'sku'})
        customer.preview(self.store, self.data, self.owner)
        state = public_intake.load(self.store)
        self.assertEqual(state['quotes'], 2)
        self.assertEqual(len(state['tickets']), 0)
        state['quotes'] = public_intake.QUOTES_PER_DAY
        public_intake.save(self.store, state)
        with self.assertRaises(public_intake.LimitReached):
            customer.preview(self.store, self.data, self.owner)
        with patch.object(self.store, 'save_opportunity', side_effect=RuntimeError('unavailable')):
            state['quotes'] = 0
            with patch('company_x2.public_intake.load', return_value=state):
                with self.assertRaises(RuntimeError):
                    customer.preview(self.store, self.data, self.owner)

    def test_metrics_exclude_experiments_and_hold_stops_new_intake(self):
        for invalid in ('bad', '', '2026-10-12', None):
            self.assertTrue(customer.metrics(self.store, invalid)['new_intake_paused'])
        for index, state in enumerate(('ready','received','held')):
            self.store.save_opportunity(dict(source=customer.SOURCE, external_id=str(index),
                status=state, experimental=False, created_at='2026-10-12T00:00:00Z'), 'blocked', 'Test metadata')
        self.store.save_opportunity(dict(source='template_work_experiment',external_id='experiment',
            status='received',experimental=True,created_at='2026-10-12T00:00:00Z'),'blocked','Test metadata')
        value=customer.metrics(self.store,'2026-10-11T00:00:00Z')
        self.assertEqual(value['counts']['accepted'],3)
        self.assertTrue(value['new_intake_paused'])
        self.assertEqual(customer.metrics(self.store,'2026-10-13T00:00:00Z')['counts']['accepted'],0)

    def test_closed_trial_allows_existing_customer_access_renewal_only(self):
        first=customer.request(self.store,self.data,self.owner)
        customer.process(self.store,{**self.data,'accepted':True,
                         'approval_sha256':first['approval_sha256']},self.owner)
        with patch('company_x2.free_trial.policy',return_value={'enabled':True,'open':False}), \
             patch('company_x2.free_trial.require_open',side_effect=public_intake.LimitReached('closed')):
            public_intake.start(self.store,self.owner)
            with self.assertRaises(public_intake.LimitReached):
                public_intake.start(self.store,self.other)
