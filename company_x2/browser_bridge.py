"""Explicit internal fixed-browser child process; no public route enables it."""
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading


class BrowserBridge:
    def __init__(self,node_executable,config,*,enabled=False,timeout=25):
        if enabled is not True:raise ValueError('Browser delivery disabled')
        node=Path(node_executable)
        if not node.is_absolute() or not node.is_file():raise ValueError('Pinned Node executable required')
        if not isinstance(config,dict) or config.get('enabled') is not True:
            raise ValueError('Operator browser configuration required')
        if not 1<=timeout<=60:raise ValueError('Bounded worker timeout required')
        self.node=str(node);self.config=dict(config);self.timeout=timeout
        self.process=None;self.messages=queue.Queue(maxsize=3);self.staged=None;self.committed=False

    def __enter__(self):return self
    def __exit__(self,*_):self.close()

    def _reader(self):
        try:
            for _ in range(3):
                line=self.process.stdout.readline(4097)
                if not line or len(line)>4096 or not line.endswith(b'\n'):raise ValueError()
                self.messages.put_nowait(json.loads(line))
        except Exception:
            try:self.messages.put_nowait({'event':'error'})
            except queue.Full:pass

    def _exchange(self,payload):
        try:
            raw=(json.dumps(payload)+'\n').encode()
            if len(raw)>75000:raise ValueError()
            self.process.stdin.write(raw);self.process.stdin.flush()
            result=self.messages.get(timeout=self.timeout)
            if not isinstance(result,dict) or result.get('event')=='error':raise ValueError()
            return result
        except Exception:
            self.close();raise ValueError('Browser worker unavailable; hold without retry') from None

    def stage(self,destination,artifact):
        if self.process or not isinstance(artifact,bytes) or not 0<len(artifact)<=50000:
            raise ValueError('One bounded artifact per worker required')
        # Do not inherit application tokens, provider keys or NODE_OPTIONS.
        names=('PATH','SystemRoot','WINDIR','USERPROFILE','HOME','TEMP','TMP','NODE_PATH','PLAYWRIGHT_BROWSERS_PATH')
        env={name:os.environ[name] for name in names if name in os.environ}
        env['CX2_BROWSER_WORKER']='1'
        worker=Path(__file__).parent/'browser'/'worker.cjs'
        try:
            self.process=subprocess.Popen([self.node,str(worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            threading.Thread(target=self._reader,daemon=True).start()
            result=self._exchange(dict(command='stage',config=self.config,destination=destination,
                                       artifact_base64=base64.b64encode(artifact).decode('ascii')))
            expected=dict(event='staged',destination=destination,artifact_sha256=hashlib.sha256(artifact).hexdigest())
            if result!=expected:raise ValueError('Worker stage evidence differs')
            self.staged={key:result[key] for key in ('destination','artifact_sha256')}
            return dict(self.staged)
        except Exception:
            self.close();raise ValueError('Browser staging unavailable') from None

    def commit(self,staged):
        if self.staged is None or staged!=self.staged or self.committed:
            raise ValueError('Verified single commit required')
        self.committed=True
        try:
            result=self._exchange(dict(command='commit',staged=self.staged))
            receipt=result.get('receipt')
            if (set(result)!={'event','receipt'} or result['event']!='receipt' or not isinstance(receipt,dict)
                    or receipt.get('destination')!=self.staged['destination']
                    or receipt.get('artifact_sha256')!=self.staged['artifact_sha256']
                    or not isinstance(receipt.get('id'),str) or not 1<=len(receipt['id'])<=200):
                raise ValueError('Browser receipt unavailable')
            return receipt
        finally:self.close()

    def close(self):
        if self.process:
            process=self.process
            if process.stdin and not process.stdin.closed:process.stdin.close()
            if process.poll() is None:
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:process.wait(timeout=2)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
            for pipe in (process.stdin,process.stdout):
                if pipe:pipe.close()
