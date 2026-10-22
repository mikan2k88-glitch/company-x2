"""Synthetic owned-work coordinator driven by the loopback Chromium fixture."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from company_x2.autonomy import FREE, AI
from company_x2.store import Store
from company_x2 import template_customer
from company_x2.work_handoff import bind_request, process_request
from company_x2.intake_access import issue
from company_x2.delivery_evidence import deliver_owned_work
from company_x2.delivery_permission import Permit
from company_x2.delivery_journal import Journal
from company_x2.cloud_delivery_journal import CloudJournal


def emit(value):
    print(json.dumps(value),flush=True)


def main():
    postgres=os.environ.get('CX2_BROWSER_POSTGRES')=='1'
    schema='browser_owned_'+uuid.uuid4().hex
    dsn=os.environ.get('CX2_TEST_DSN','')
    def sql(query):
        result=subprocess.run(['psql',dsn,'-X','-A','-t','-v','ON_ERROR_STOP=1','-c',query],capture_output=True,text=True)
        if result.returncode:raise RuntimeError('Disposable database command failed')
        return result.stdout.strip()
    def rpc(action,payload):
        encoded=json.dumps(payload).replace("'","''")
        raw=sql(f"SELECT {schema}.journal('{action}','{encoded}'::jsonb)")
        return json.loads(raw) if raw else None
    if postgres:
        if urlparse(dsn).hostname not in ('localhost','127.0.0.1','::1'):
            raise ValueError('Disposable loopback database required')
        sql((Path(__file__).parent/'fixtures'/'delivery_rpc.sql').read_text().replace('__SCHEMA__',schema))
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'work.db')
            row=dict(id='ot_'+'a'*32,status='sent',reply_id='123',reply_text=FREE+' '+AI)
            store.outreach_rpc=lambda action:[row]
            client=type('SyntheticSource',(),{'observe':lambda _,contact:dict(row)})()
            data=dict(request_key='browser-owned-001',purpose='Prepare template',csv='sku\n001\n',
                columns=['SKU'],mapping={'SKU':'sku'},risk_context=dict(sensitive_data='no',critical_use='no',extra_liability='no'))
            owner='a'*40
            template_customer.request(store,data,owner)
            grant,_=issue('synthetic-only-signing-key',contact_id=row['id'])
            bind_request(store,grant,'synthetic-only-signing-key','123',client,owner,data['request_key'])
            record=template_customer.OwnedStore(store,owner).opportunities()[0]
            data.update(accepted=True,approval_sha256=record['approval_sha256'])
            work=process_request(store,grant,'synthetic-only-signing-key','123',client,owner,data)
            destination='https://synthetic.invalid/orders/1'
            permit=Permit('https://synthetic.invalid',destination,row['id'],'123',record['approval_sha256'],
                hashlib.sha256(work['csv'].encode()).hexdigest(),datetime.now(timezone.utc)+timedelta(minutes=5),'synthetic-fixture-only')
            journal=CloudJournal(rpc) if postgres else Journal(Path(tmp)/'journal.db')
            def send(target,artifact):
                emit(dict(event='send',destination=target,artifact=artifact.decode()))
                return json.loads(sys.stdin.readline())
            adapter=type('SyntheticBrowserBridge',(),{'send':staticmethod(send)})()
            def deliver():
                return deliver_owned_work(journal,permit,adapter,store,grant,'synthetic-only-signing-key',
                    '123',client,owner,data,is_stopped=lambda:False)
            result=deliver()
            assert result['state']=='confirmed'
            # New journal object verifies replay uses durable state rather than memory.
            journal=CloudJournal(rpc) if postgres else Journal(Path(tmp)/'journal.db')
            assert deliver()['replayed'] is True
            row['reply_text']='Consent withdrawn'
            try:deliver()
            except ValueError:pass
            else:raise AssertionError('Revoked consent was accepted')
            emit(dict(event='done',state=result['state'],backend='postgres' if postgres else 'sqlite'))
    finally:
        if postgres:sql(f'DROP SCHEMA {schema} CASCADE')


if __name__=='__main__':main()
