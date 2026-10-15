import unittest
from company_x2.autonomy import FREE, AI
from company_x2.work_handoff import verified_contact, recheck_contact, invited_contact
from company_x2.intake_access import issue


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
