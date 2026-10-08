import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from company_x2.data_services import produce, verify
from company_x2.public_scout import normalize
from company_x2.server import handler_for
from company_x2.store import Store
from company_x2.worker import process_one


class DataServiceTests(unittest.TestCase):
    def test_json_keeps_strings_unicode_empty_and_quoted_newlines(self):
        text = '\ufeffid,note\n001,"東京,\n晴れ"\n002,\n'
        result = produce(text, 'csv_to_json')
        verify(text, 'csv_to_json', result)
        self.assertEqual(json.loads(result['artifact']['content']),
                         [{'id':'001','note':'東京,\n晴れ'}, {'id':'002','note':''}])
        self.assertEqual(result['artifact']['content_type'], 'application/json; charset=utf-8')

    def test_trim_preserves_internal_space_duplicates_order_and_formulas(self):
        text = ' name , value \n Alice , x y \n Alice , x y \nBob, =SUM(A1) \n'
        result = produce(text, 'csv_trim')
        verify(text, 'csv_trim', result)
        self.assertEqual(result['artifact']['content'], 'name,value\r\nAlice,x y\r\nAlice,x y\r\nBob,=SUM(A1)\r\n')
        self.assertEqual(result['removed_rows'], 0)
        self.assertGreater(result['changed_cells'], 0)
        with self.assertRaises(ValueError):
            produce('a, a\n1,2\n', 'csv_trim')

    def test_audit_counts_records_and_never_evaluates_or_includes_values(self):
        text = 'name,value\nA,\nA,\nB, -123\nC,=EXEC(secret)\n'
        result = produce(text, 'csv_audit')
        verify(text, 'csv_audit', result)
        report = json.loads(result['artifact']['content'])
        self.assertEqual(report['empty_cells'], 2)
        self.assertEqual(report['duplicate_rows'], 1)
        self.assertEqual(report['formula_like_cells'], 2)
        self.assertEqual(report['duplicate_record_sample'], [3])
        self.assertNotIn('EXEC', result['artifact']['content'])
        self.assertEqual(result['summary']['empty_cells'], 2)

    def test_empty_header_only_input_is_valid(self):
        for key in ('csv_trim','csv_to_json','csv_audit'):
            result = produce('a,b\n', key)
            verify('a,b\n', key, result)
            self.assertEqual(result['input_rows'], 0)

    def test_malformed_input_and_amplified_json_rejected(self):
        for text in ('a,a\n1,2\n', 'a,b\n1\n', 'a\n"unfinished', 'a,' * 201 + '\n'):
            for key in ('csv_trim','csv_to_json','csv_audit'):
                with self.assertRaises(Exception):
                    produce(text, key)
        with self.assertRaises(ValueError):
            produce('a' * 4000 + '\n' + 'x\n' * 3000, 'csv_to_json')

    def test_verifier_rejects_serialized_value_corruption(self):
        for key in ('csv_trim','csv_to_json','csv_audit'):
            result = produce('id\n001\n', key)
            result['artifact']['content'] = 'id\n999\n' if key == 'csv_trim' else (
                '[{"id":1}]' if key == 'csv_to_json' else result['artifact']['content'].replace('"row_count": 1','"row_count": 2'))
            with self.assertRaises(ValueError):
                verify('id\n001\n', key, result)

    def test_scout_maps_new_services_without_granting_permission(self):
        for title, body, key in [('Convert CSV to JSON $20', 'Preserve string values', 'csv_to_json'),
                                 ('CSV trim whitespace $20', 'Remove trailing spaces', 'csv_trim'),
                                 ('CSV data quality audit $20', 'Report missing values', 'csv_audit')]:
            item = normalize({'id':1,'title':title,'body':body,'state':'open',
                              'html_url':'https://github.com/x/y/issues/1','labels':[]}, 'now')
            self.assertIn(key, item['service_keys'])
            self.assertEqual(item['decision'], 'needs_review')
            self.assertFalse(item['automated_proposals_allowed'])

    def test_service_persists_and_idempotency_rejects_service_change(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'db'
            store = Store(path)
            key, token = 'k' * 32, 't' * 32
            order = store.submit('a\n001\n', key, token, 'csv_to_json')
            self.assertEqual(store.submit('a\n001\n', key, token, 'csv_to_json'), order)
            with self.assertRaises(ValueError):
                store.submit('a\n001\n', key, token, 'csv_trim')
            restarted = Store(path)
            process_one(restarted)
            saved = restarted.get(order, token)
            self.assertEqual(saved['service_key'], 'csv_to_json')
            self.assertEqual(json.loads(saved['result']['artifact']['content']), [{'a':'001'}])
            self.assertEqual(saved['revenue_jpy'], 0)

    def test_http_all_services_metadata_download_owner_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'db')
            server = ThreadingHTTPServer(('127.0.0.1',0),handler_for(store,'admin'))
            thread = threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            token = 't'*32
            def request(path, data=None, owner=token):
                return urllib.request.urlopen(urllib.request.Request(base+path,
                    data=json.dumps(data).encode() if data is not None else None,
                    headers={'Content-Type':'application/json','X-Order-Token':owner}),timeout=3)
            try:
                with request('/api/services') as response:
                    self.assertEqual(len(json.load(response)['items']),4)
                for index, service in enumerate(('csv_exact_dedup','csv_trim','csv_to_json','csv_audit')):
                    with self.assertRaises(urllib.error.HTTPError) as retired:
                        request('/api/orders',{'csv':'a\n001\n001\n','service_key':service,
                                 'request_key':str(index)*32,'terms_accepted':True})
                    self.assertEqual(retired.exception.code,410)
                    order=store.submit('a\n001\n001\n',str(index)*32,token,service)
                    process_one(store)
                    for path in ('/api/orders/'+order,'/api/orders/'+order+'/download'):
                        with self.assertRaises(urllib.error.HTTPError) as unchecked:
                            request(path)
                        self.assertEqual(unchecked.exception.code,410)
                    with self.assertRaises(urllib.error.HTTPError) as err:
                        request('/api/orders/'+order+'/download',owner='wrong')
                    self.assertEqual(err.exception.code,404)
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    request('/api/orders',{'csv':'a\n1\n','service_key':'run_code',
                                          'request_key':'z'*32,'terms_accepted':True})
                self.assertEqual(invalid.exception.code,410)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
