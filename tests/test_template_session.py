import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from company_x2.store import Store
from company_x2.template_work import safe_request
from company_x2 import template_session as session


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'db'
        self.store = Store(self.path)
        self.data = {'request_key': 'experiment-key-001', 'purpose': 'Prepare private purpose marker',
                     'csv': 'sku,title\n001,content-marker\n', 'columns': ['SKU'], 'mapping': {'SKU': 'sku'},
                     'risk_context': dict(sensitive_data='no', critical_use='no', extra_liability='no')}

    def tearDown(self):
        self.tmp.cleanup()

    def test_restart_idempotence_privacy_and_receipt(self):
        first = session.request(self.store, self.data)
        self.assertEqual(session.request(self.store, self.data)['approval_sha256'], first['approval_sha256'])
        self.data.update(accepted=True, approval_sha256=first['approval_sha256'])
        result = session.process(self.store, self.data)
        restarted = Store(self.path)
        self.assertEqual(session.process(restarted, self.data)['csv'], result['csv'])
        receipt = dict(request_key=self.data['request_key'], accepted=True, artifact_sha256=result['artifact_sha256'])
        self.assertEqual(session.receive(restarted, receipt)['status'], 'received')
        self.assertEqual(session.receive(restarted, receipt)['status'], 'received')
        stored = json.dumps(restarted.opportunities())
        self.assertNotIn('content-marker', stored)
        self.assertNotIn('private purpose marker', stored)
        self.assertFalse(session.summary(restarted)['real_customer_evidence'])

    def test_processing_restart_is_held_without_reexecution(self):
        first = session.request(self.store, self.data)
        first['status'] = 'processing'
        session.save(self.store, first)
        self.data.update(accepted=True, approval_sha256=first['approval_sha256'])
        with self.assertRaises(ValueError):
            session.process(Store(self.path), self.data)

    def test_changed_plan_and_forged_receipt_rejected(self):
        first = session.request(self.store, self.data)
        with self.assertRaises(ValueError):
            session.request(self.store, {**self.data, 'purpose': 'different'})
        with self.assertRaises(ValueError):
            session.receive(self.store, {'request_key': self.data['request_key'], 'accepted': True})

    def test_storage_failure_prevents_execution(self):
        first = session.request(self.store, self.data)
        self.data.update(accepted=True, approval_sha256=first['approval_sha256'])
        with patch.object(self.store, 'save_opportunity', side_effect=RuntimeError('storage unavailable')):
            with self.assertRaises(RuntimeError):
                session.process(self.store, self.data)
        self.assertEqual(session.summary(self.store)['counts']['awaiting_consent'], 1)
