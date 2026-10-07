import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from company_x2.settings import build_store
from company_x2.store import Store
from company_x2.server import handler_for
from company_x2.supabase_store import SupabaseStore, StorageUnavailable


class CloudTests(unittest.TestCase):
    def test_render_never_falls_back_to_sqlite(self):
        for env in ({'RENDER': 'true'}, {'RENDER': 'true', 'STORAGE_BACKEND': 'sqlite'},
                    {'STORAGE_BACKEND': 'supabase', 'SUPABASE_URL': 'https://example.supabase.co'}):
            with self.assertRaises(ValueError):
                build_store(env)

    def test_new_secret_uses_apikey_without_bearer(self):
        seen = []
        def opener(req, timeout):
            seen.append(req)
            return io.BytesIO(b'{"schema_version":2}')
        store = SupabaseStore('https://example.supabase.co', 'sb_secret_test', opener=opener)
        self.assertTrue(store.ping())
        self.assertEqual(seen[0].get_header('Apikey'), 'sb_secret_test')
        self.assertIsNone(seen[0].get_header('Authorization'))

    def test_legacy_key_and_lease_are_forwarded(self):
        seen = []
        def opener(req, timeout):
            seen.append(req)
            return io.BytesIO(b'true')
        store = SupabaseStore('https://example.supabase.co', 'legacy-jwt', opener=opener)
        store.finish('one', result={'csv': 'a'}, lease='lease-one')
        self.assertEqual(seen[0].get_header('Authorization'), 'Bearer legacy-jwt')
        payload = json.loads(seen[0].data)
        self.assertEqual(payload['p_payload']['lease'], 'lease-one')

    def test_connection_errors_are_redacted(self):
        def opener(req, timeout):
            raise urllib.error.URLError('secret_customer_data')
        store = SupabaseStore('https://example.supabase.co', 'sb_secret_test', opener=opener)
        with self.assertRaises(StorageUnavailable) as error:
            store.ping()
        self.assertNotIn('secret_customer_data', str(error.exception))

    def test_publishable_key_and_unsafe_url_rejected(self):
        for url, key in [('http://example.com','sb_secret_test'),
                         ('https://example.com/path','sb_secret_test'),
                         ('https://example.com','sb_publishable_test')]:
            with self.assertRaises(ValueError):
                SupabaseStore(url, key)

    def test_new_services_use_separate_queue_and_legacy_orders_still_route(self):
        seen = []
        def opener(req, timeout):
            seen.append((req.full_url, json.loads(req.data)))
            action = json.loads(req.data)['p_action']
            return io.BytesIO(json.dumps('svc_one' if action == 'submit' else {
                'id':'old', 'status':'ready'} if action == 'get' else True).encode())
        store = SupabaseStore('https://example.supabase.co','sb_secret_test',opener=opener)
        store.submit('a\n001\n','k'*32,'t'*32,'csv_to_json')
        self.assertTrue(seen[-1][0].endswith('cx2_services'))
        self.assertEqual(seen[-1][1]['p_payload']['service_key'],'csv_to_json')
        store.finish('svc_one',result={},lease='lease')
        self.assertTrue(seen[-1][0].endswith('cx2_services'))
        store.submit('a\n001\n','x'*32,'t'*32)
        self.assertTrue(seen[-1][0].endswith('cx2_store'))
        saved = store.get('old','t'*32)
        self.assertEqual(saved['service_key'],'csv_exact_dedup')

    def test_missing_services_migration_keeps_legacy_worker_available(self):
        def opener(req, timeout):
            if req.full_url.endswith('cx2_services'):
                raise urllib.error.HTTPError(req.full_url,404,'missing',{},io.BytesIO())
            return io.BytesIO(b'null')
        store = SupabaseStore('https://example.supabase.co','sb_secret_test',opener=opener)
        self.assertIsNone(store.claim())
        with self.assertRaises(StorageUnavailable) as error:
            store.services_ready()
        self.assertIn('004_data_services.sql',str(error.exception))

    def test_http_diagnostics_retain_status_but_not_body_or_key(self):
        for status in (401, 403, 404, 429, 500):
            def opener(req, timeout):
                raise urllib.error.HTTPError(req.full_url, status, 'sensitive-body', {}, io.BytesIO(b'secret-customer'))
            store = SupabaseStore('https://example.supabase.co', 'sb_secret_private', opener=opener)
            with self.assertRaises(StorageUnavailable) as error:
                store.ping()
            self.assertIn(str(status), str(error.exception))
            self.assertNotIn('private', str(error.exception))
            self.assertNotIn('sensitive', str(error.exception))
            self.assertNotIn('secret-customer', str(error.exception))

    def test_render_host_password_and_order_token_coexist(self):
        import base64
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / 'db')
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(store, 'admin',
                allowed_hosts=['company-x2.onrender.com'], access_password='test-password'))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            headers = {'Host': 'company-x2.onrender.com'}
            try:
                with urllib.request.urlopen(urllib.request.Request(base+'/api/health',headers=headers)) as response:
                    self.assertEqual(json.load(response)['endpoint'], 'E11')
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    urllib.request.urlopen(urllib.request.Request(base+'/',headers=headers))
                self.assertEqual(unauthorized.exception.code, 401)
                headers.update({'Authorization':'Basic '+base64.b64encode(b'demo:test-password').decode(),
                    'X-Order-Token':'a'*32, 'Content-Type':'application/json', 'Origin':'https://company-x2.onrender.com'})
                body = json.dumps({'csv':'a\n1\n', 'request_key':'b'*32, 'terms_accepted':True}).encode()
                with urllib.request.urlopen(urllib.request.Request(base+'/api/orders',data=body,headers=headers)) as response:
                    self.assertEqual(response.status, 202)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
