import hashlib
import json
import os
import io
import queue
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import MagicMock,patch
from company_x2.browser_bridge import BrowserBridge
from company_x2.delivery_experiment import deliver_once
from company_x2.delivery_journal import Journal
from company_x2.staged_delivery import StagedAdapter


class BridgeTests(unittest.TestCase):
    def test_disabled_and_unpinned_runtime_rejected(self):
        with self.assertRaises(ValueError):BrowserBridge('node',{})
        with self.assertRaises(ValueError):BrowserBridge('node',{'enabled':True},enabled=True)

    def test_worker_loss_malformed_output_and_timeout_hold_without_retry(self):
        artifact=b'Synthetic file';destination='https://synthetic.invalid/order/1'
        staged=dict(event='staged',destination=destination,artifact_sha256=hashlib.sha256(artifact).hexdigest())
        for mode in ('loss','malformed','timeout'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                process=MagicMock();process.poll.return_value=0
                process.stdout=io.BytesIO((json.dumps(staged)+'\n').encode() if mode!='malformed' else b'x'*4097)
                config=dict(enabled=True,pageUrl=destination,uploadUrl='https://synthetic.invalid/upload',destination=destination)
                journal=Journal(Path(tmp)/'journal')
                args=dict(contact='contact',reply='reply',plan='plan',destination=destination,artifact=artifact,
                          approved_sha256=hashlib.sha256(artifact).hexdigest(),authorize=lambda:True)
                with patch('company_x2.browser_bridge.subprocess.Popen',return_value=process) as spawn:
                    with BrowserBridge(sys.executable,config,enabled=True) as bridge:
                        if mode=='timeout':bridge.messages.get=MagicMock(side_effect=queue.Empty)
                        with self.assertRaises(ValueError):deliver_once(journal,**args,adapter=StagedAdapter(bridge))
                    with BrowserBridge(sys.executable,config,enabled=True) as bridge:
                        self.assertEqual(deliver_once(journal,**args,adapter=StagedAdapter(bridge))['state'],'uncertain')
                    self.assertEqual(spawn.call_count,1)
                    self.assertNotIn(artifact.decode(),str(spawn.call_args.args))
                    self.assertNotIn('OPENAI_API_KEY',spawn.call_args.kwargs['env'])
                    self.assertNotIn('NODE_OPTIONS',spawn.call_args.kwargs['env'])
                process.stdin.close.assert_called()

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
