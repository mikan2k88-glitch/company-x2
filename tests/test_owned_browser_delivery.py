from datetime import datetime,timedelta,timezone
import sys
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from company_x2.delivery_permission import Permit
from company_x2.owned_browser_delivery import deliver_owned_browser


class OwnedBrowserEntryTests(unittest.TestCase):
    def setUp(self):
        self.permit=Permit('https://synthetic.invalid','https://synthetic.invalid/order/1',
            'contact','reply','a'*64,'b'*64,datetime.now(timezone.utc)+timedelta(minutes=1),'synthetic policy')

    def call(self,**kwargs):
        options=dict(node_executable=sys.executable,upload_url='https://synthetic.invalid/upload')
        options.update(kwargs)
        return deliver_owned_browser(None,self.permit,None,None,None,'reply',None,'owner',
            {'loopbackFixture':True,'node_executable':'customer-controlled'},**options)

    def test_disabled_stopped_and_foreign_upload_never_start_bridge(self):
        with patch('company_x2.owned_browser_delivery.BrowserBridge') as bridge:
            for options in ({},{'enabled':True},dict(enabled=True,is_stopped=lambda:False,
                    upload_url='https://foreign.invalid/upload')):
                with self.assertRaises(ValueError):self.call(**options)
            bridge.assert_not_called()

    def test_owned_coordinator_rejection_closes_lazy_bridge_without_spawn(self):
        with patch('company_x2.browser_bridge.subprocess.Popen') as spawn,patch(
                'company_x2.owned_browser_delivery.deliver_owned_work',side_effect=ValueError('No owned work')) as owned:
            with self.assertRaises(ValueError):self.call(enabled=True,is_stopped=lambda:False)
            backend=owned.call_args.args[2].backend
            self.assertEqual(backend.config,dict(enabled=True,pageUrl=self.permit.destination,
                uploadUrl='https://synthetic.invalid/upload',destination=self.permit.destination))
            self.assertIsNone(backend.process)
            spawn.assert_not_called()

    def test_real_owned_work_rechecks_consent_and_replays_without_commit(self):
        from company_x2.autonomy import FREE,AI
        from company_x2.store import Store
        from company_x2 import template_customer
        from company_x2.work_handoff import bind_request,process_request
        from company_x2.intake_access import issue
        from company_x2.delivery_journal import Journal
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'work.db')
            row=dict(id='ot_'+'a'*32,status='sent',reply_id='123',reply_text=FREE+' '+AI)
            store.outreach_rpc=lambda action:[row]
            client=type('SyntheticSource',(),{'observe':lambda _,contact:dict(row)})()
            data=dict(request_key='synthetic-owned-entry',purpose='Prepare template',csv='sku\n001\n',
                columns=['SKU'],mapping={'SKU':'sku'},risk_context=dict(
                    sensitive_data='no',critical_use='no',extra_liability='no'))
            owner='a'*40;key='synthetic-only-signing-key'
            template_customer.request(store,data,owner)
            grant,_=issue(key,contact_id=row['id'])
            bind_request(store,grant,key,'123',client,owner,data['request_key'])
            record=template_customer.OwnedStore(store,owner).opportunities()[0]
            data.update(accepted=True,approval_sha256=record['approval_sha256'])
            work=process_request(store,grant,key,'123',client,owner,data)
            digest=hashlib.sha256(work['csv'].encode()).hexdigest()
            permit=Permit(self.permit.origin,self.permit.destination,row['id'],'123',
                record['approval_sha256'],digest,self.permit.expires_at,'synthetic policy')
            for revoked in (False,True):
                with self.subTest(revoked=revoked),patch('company_x2.owned_browser_delivery.BrowserBridge') as factory:
                    bridge=factory.return_value.__enter__.return_value
                    def stage(destination,artifact):
                        self.assertEqual(artifact,work['csv'].encode())
                        if revoked:row['reply_text']='Consent withdrawn'
                        return dict(destination=destination,artifact_sha256=digest)
                    bridge.stage.side_effect=stage
                    bridge.commit.return_value=dict(id='synthetic-receipt',destination=permit.destination,artifact_sha256=digest)
                    journal=Journal(Path(tmp)/('revoked.db' if revoked else 'normal.db'))
                    def deliver():
                        return deliver_owned_browser(journal,permit,store,grant,key,'123',client,owner,data,
                            node_executable=sys.executable,upload_url=permit.origin+'/upload',
                            enabled=True,is_stopped=lambda:False)
                    if revoked:
                        with self.assertRaises(ValueError):deliver()
                        bridge.commit.assert_not_called()
                        row['reply_text']=FREE+' '+AI
                        self.assertEqual(deliver()['state'],'uncertain')
                    else:
                        self.assertEqual(deliver()['state'],'confirmed')
                        self.assertTrue(deliver()['replayed'])
                        bridge.commit.assert_called_once()
                    bridge.stage.assert_called_once()
