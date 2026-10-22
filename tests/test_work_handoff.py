import unittest
import tempfile
from pathlib import Path
from company_x2.autonomy import FREE, AI
from company_x2.work_handoff import verified_contact, recheck_contact, invited_contact
from company_x2.intake_access import issue
from company_x2.work_handoff import bind_request, process_request
from company_x2 import template_customer
from company_x2.store import Store
from company_x2.delivery_evidence import prepare_delivery


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.row=dict(id='ot_'+'a'*32,status='sent',reply_id='123',reply_text=FREE+' '+AI)
        self.store=type('FakeStore',(),{'outreach_rpc':lambda _,action:[self.row]})()

    def test_minimal_verified_manifest_is_not_delivery_permission(self):
        value=verified_contact(self.store,self.row['id'],'123')
        self.assertFalse(value['external_delivery_allowed'])
        self.assertNotIn('reply_text',value)
        self.assertEqual(value['status'],'awaiting_work_plan')

    def test_changed_reply_or_added_conditions_are_held(self):
        with self.assertRaises(ValueError):verified_contact(self.store,self.row['id'],'124')
        self.row['reply_text']+=' and deliver to a different account'
        with self.assertRaises(ValueError):verified_contact(self.store,self.row['id'],'123')

    def test_unsent_and_invalid_identity_are_rejected(self):
        self.row['status']='draft'
        with self.assertRaises(ValueError):verified_contact(self.store,self.row['id'],'123')
        with self.assertRaises(ValueError):verified_contact(self.store,'other','123')

    def test_live_recheck_fails_closed_on_missing_changed_and_revoked_reply(self):
        client=type('Client',(),{})()
        for observed in (None, {'id':self.row['id'],'reply_id':'124','reply_text':FREE+' '+AI},
                         {'id':self.row['id'],'reply_id':'123','reply_text':'Consent withdrawn'},
                         {'id':'ot_'+'b'*32,'reply_id':'123','reply_text':FREE+' '+AI}):
            client.observe=lambda contact:observed
            with self.assertRaises(ValueError):recheck_contact(self.store,self.row['id'],'123',client)
        client.observe=lambda contact:{'id':self.row['id'],'reply_id':'123','reply_text':FREE+' '+AI}
        self.assertTrue(recheck_contact(self.store,self.row['id'],'123',client)['source_rechecked'])

    def test_invitation_identity_is_derived_from_signed_claim(self):
        client=type('Client',(),{'observe':lambda _,contact:{'id':contact['id'],
            'reply_id':'123','reply_text':FREE+' '+AI}})()
        grant,_=issue('test-key',contact_id=self.row['id'])
        self.assertEqual(invited_contact(self.store,grant,'test-key','123',client)['contact_id'],self.row['id'])
        other,_=issue('test-key',contact_id='ot_'+'b'*32)
        unbound,_=issue('test-key')
        expired,_=issue('test-key',now=1,contact_id=self.row['id'])
        for invalid in (other,unbound,expired,grant+'tampered'):
            with self.assertRaises(ValueError):invited_contact(self.store,invalid,'test-key','123',client)

    def test_binding_requires_reserved_owner_plan_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'db');store.outreach_rpc=lambda action:[self.row]
            client=type('Client',(),{'observe':lambda _,contact:dict(id=contact['id'],reply_id='123',reply_text=FREE+' '+AI)})()
            data=dict(request_key='handoff-request-001',purpose='Prepare template',csv='sku\n001\n',
                columns=['SKU'],mapping={'SKU':'sku'},risk_context=dict(sensitive_data='no',critical_use='no',extra_liability='no'))
            owner='a'*40;template_customer.request(store,data,owner)
            grant,_=issue('test-key',contact_id=self.row['id'])
            with self.assertRaises(ValueError):process_request(store,grant,'test-key','123',client,owner,data)
            for _ in range(2):
                self.assertEqual(bind_request(store,grant,'test-key','123',client,owner,data['request_key'])['status'],'awaiting_plan_consent')
            with self.assertRaises(ValueError):bind_request(store,grant,'test-key','123',client,'b'*40,data['request_key'])
            record=template_customer.OwnedStore(store,owner).opportunities()[0]
            self.assertEqual(record['handoff']['reply_id'],'123')
            self.assertNotIn('handoff',template_customer.status(store,owner)['items'][0])
            data.update(accepted=True,approval_sha256=record['approval_sha256'])
            with self.assertRaises(ValueError):template_customer.process(store,data,owner)
            result=process_request(store,grant,'test-key','123',client,owner,data)
            self.assertIn('001',result['csv'])
            prepared=prepare_delivery(store,grant,'test-key','123',client,owner,
                {**data,'inspection_passed':False},destination='https://synthetic.invalid/orders/1')
            self.assertTrue(prepared['evidence']['inspection_passed'])
            self.assertEqual(prepared['artifact'],result['csv'].encode())
            with self.assertRaises(ValueError):prepare_delivery(store,grant,'test-key','123',client,'b'*40,data,
                destination='https://synthetic.invalid/orders/1')
            with self.assertRaises(ValueError):prepare_delivery(store,grant,'test-key','123',client,owner,
                {**data,'csv':'sku\n002\n','inspection_passed':True},destination='https://synthetic.invalid/orders/1')
            self.row['reply_text']='Consent withdrawn'
            with self.assertRaises(ValueError):process_request(store,grant,'test-key','123',client,owner,data)
