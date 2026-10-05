import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path

from company_x2.server import handler_for
from company_x2.store import Store
from company_x2.worker import process_one
from company_x2.scout import import_feed

TOKEN = 'customer-token-' + 'a' * 32
KEY = 'request-key-' + 'b' * 32


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'db.sqlite')

    def tearDown(self):
        self.temp.cleanup()

    def test_idempotent_submission_and_owner_isolation(self):
        order = self.store.submit('a\n1\n1\n', KEY, TOKEN)
        self.assertEqual(order, self.store.submit('a\n1\n1\n', KEY, TOKEN))
        with self.assertRaises(ValueError):
            self.store.submit('a\n2\n', KEY, TOKEN)
        self.assertIsNone(self.store.get(order, 'wrong'))
        self.assertTrue(process_one(self.store))
        self.assertFalse(process_one(self.store))
        saved = self.store.get(order, TOKEN)
        self.assertEqual(saved['status'], 'ready')
        self.assertEqual(saved['revenue_jpy'], 0)
        self.assertEqual(saved['result']['removed_rows'], 1)
        self.assertEqual(saved['result']['sha256'], self.store.digest(saved['result']['csv']))

    def test_restart_recovers_without_duplicate_completion(self):
        order = self.store.submit('a\n1\n', KEY, TOKEN)
        self.store.claim()
        restarted = Store(self.store.path)
        restarted.recover()
        process_one(restarted)
        self.assertEqual(restarted.get(order, TOKEN)['status'], 'ready')
        with self.assertRaises(ValueError):
            restarted.finish(order, result={})

    def test_concurrent_claim_is_exclusive(self):
        self.store.submit('a\n1\n', KEY, TOKEN)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.claim(), range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_invalid_csv_is_failed_and_never_paid(self):
        order = self.store.submit('a,b\n1\n', KEY, TOKEN)
        process_one(self.store)
        saved = self.store.get(order, TOKEN)
        self.assertEqual(saved['status'], 'failed')
        self.assertIsNone(saved['result'])
        self.assertEqual(saved['revenue_jpy'], 0)

    def test_discovery_requires_permissions_and_deduplicates(self):
        candidate = {'source': 'fixture', 'external_id': 'one', 'url': 'https://example.org/job',
                     'title': 'CSV task', 'service_key': 'csv_exact_dedup',
                     'budget_jpy': 1000, 'estimated_cost_jpy': 100}
        self.assertEqual(import_feed(self.store, [candidate])[0]['decision'], 'blocked')
        candidate['automated_proposals_allowed'] = True
        self.assertEqual(import_feed(self.store, [candidate])[0]['decision'], 'qualified')
        self.assertEqual(len(self.store.opportunities()), 1)
        # A malformed batch must not persist the valid first item.
        another = {**candidate, 'external_id': 'two'}
        with self.assertRaises(ValueError):
            import_feed(self.store, [another, {}])
        self.assertEqual(len(self.store.opportunities()), 1)

    def test_http_order_download_and_access_control(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(self.store, 'admin-secret'))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def request(path, data=None, token=TOKEN, headers=None):
            return urllib.request.urlopen(urllib.request.Request(base + path,
                data=json.dumps(data).encode() if data else None,
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', **(headers or {})}), timeout=3)
        try:
            with request('/') as response:
                self.assertIn(b'Company X2', response.read())
            with request('/api/orders', {'csv': 'a\n1\n1\n', 'request_key': KEY, 'terms_accepted': True}) as response:
                self.assertEqual(response.status, 202)
                order = json.load(response)['id']
            with self.assertRaises(urllib.error.HTTPError) as missing:
                request('/api/orders/' + order, token='wrong')
            self.assertEqual(missing.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as early:
                request('/api/orders/' + order + '/download')
            self.assertEqual(early.exception.code, 409)
            process_one(self.store)
            with request('/api/orders/' + order + '/download') as response:
                self.assertEqual(response.read().decode('utf-8-sig'), 'a\r\n1\r\n')
                self.assertIn('attachment', response.headers['Content-Disposition'])
            with self.assertRaises(urllib.error.HTTPError) as forbidden:
                request('/api/orders', {'csv': 'a'}, headers={'Origin': 'https://evil.example'})
            self.assertEqual(forbidden.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as admin:
                request('/api/opportunities')
            self.assertEqual(admin.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
