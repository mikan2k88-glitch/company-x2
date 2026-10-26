import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from company_x2.browser_bridge import BrowserBridge
from company_x2.delivery_experiment import deliver_once
from company_x2.delivery_journal import Journal
from company_x2.staged_delivery import StagedAdapter


class BridgeTests(unittest.TestCase):
    def test_disabled_and_unpinned_runtime_rejected(self):
        with self.assertRaises(ValueError):BrowserBridge('node',{})
        with self.assertRaises(ValueError):BrowserBridge('node',{'enabled':True},enabled=True)

    @unittest.skipUnless(os.environ.get('CX2_TEST_REAL_BROWSER')=='1','Explicit isolated browser test only')
    def test_real_private_worker_stop_then_single_delivery(self):
        artifact=b'SKU\r\n001\r\n';destination='https://synthetic.invalid/order/1';uploads=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                self.wfile.write(b'''<input type="file" id="artifact"><button id="deliver">Deliver</button>
                <script>document.querySelector('#deliver').onclick=async()=>{await fetch('/deliver',{
                method:'POST',body:await document.querySelector('#artifact').files[0].arrayBuffer()});};</script>''')
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));uploads.append(body)
                receipt=dict(id='synthetic-receipt',destination=destination,artifact_sha256=hashlib.sha256(body).hexdigest())
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps(receipt).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        config=dict(enabled=True,pageUrl=origin+'/',uploadUrl=origin+'/deliver',destination=destination,loopbackFixture=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                args=dict(contact='contact',reply='reply',plan='plan',destination=destination,artifact=artifact,
                          approved_sha256=hashlib.sha256(artifact).hexdigest())
                with BrowserBridge(os.environ['CX2_TEST_NODE'],config,enabled=True) as bridge:
                    checks=iter([True,True,False])
                    with self.assertRaises(ValueError):deliver_once(Journal(Path(tmp)/'stopped'),**args,
                        adapter=StagedAdapter(bridge),authorize=lambda:next(checks))
                self.assertEqual(uploads,[])
                journal=Journal(Path(tmp)/'normal')
                with BrowserBridge(os.environ['CX2_TEST_NODE'],config,enabled=True) as bridge:
                    self.assertEqual(deliver_once(journal,**args,adapter=StagedAdapter(bridge),authorize=lambda:True)['state'],'confirmed')
                self.assertEqual(uploads,[artifact])
                with BrowserBridge(os.environ['CX2_TEST_NODE'],config,enabled=True) as bridge:
                    self.assertTrue(deliver_once(journal,**args,adapter=StagedAdapter(bridge),authorize=lambda:True)['replayed'])
                    self.assertIsNone(bridge.process)
        finally:server.shutdown();server.server_close();thread.join()
