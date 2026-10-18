import unittest
from company_x2.cloud_delivery_journal import CloudJournal


class CloudContractTests(unittest.TestCase):
    def test_claim_shapes_fail_closed_and_stop_avoids_rpc(self):
        calls=[]
        journal=CloudJournal(lambda action,data:calls.append(action))
        with self.assertRaises(ValueError):journal.claim('a'*64)
        self.assertFalse(calls)
        for invalid in (False,{}, {'lease':'short'}, {'lease':'b'*64,'extra':'secret'}):
            with self.assertRaises(ValueError):CloudJournal(lambda a,d:invalid).claim('a'*64,allowed=True)
        self.assertEqual(CloudJournal(lambda a,d:{'lease':'b'*64}).claim('a'*64,allowed=True),'b'*64)

    def test_ambiguous_finish_and_leaked_state_are_rejected(self):
        with self.assertRaises(ValueError):CloudJournal(lambda a,d:None).finish('a'*64,'b'*64)
        with self.assertRaises(ValueError):CloudJournal(lambda a,d:{'state':'sending','has_receipt':False,'lease':'secret'}).state('a'*64)
