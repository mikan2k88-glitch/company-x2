import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from company_x2.delivery_journal import Journal,identity


class JournalTests(unittest.TestCase):
    def test_confirmed_receipt_and_identity_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'journal')
            values=('contact','reply','plan','artifact','fixed-destination')
            key=identity(*values)
            for index in range(len(values)):
                changed=list(values);changed[index]+='-changed'
                self.assertNotEqual(identity(*changed),key)
            for invalid in ('',None,'a'*2049,'line\nbreak'):
                with self.assertRaises(ValueError):identity(invalid,*values[1:])
            lease=journal.claim(key,allowed=True)
            with self.assertRaises(ValueError):journal.finish(key,lease,'')
            journal.finish(key,lease,'synthetic-receipt-id')
            self.assertEqual(journal.state(key),{'state':'confirmed','has_receipt':True})
            self.assertIsNone(journal.claim(key,allowed=True))
            self.assertNotIn('lease',journal.state(key))

    def test_concurrent_claim_restart_and_uncertain_do_not_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal';journal=Journal(path)
            key=identity('contact','reply','plan','artifact','fixed-destination')
            with ThreadPoolExecutor(max_workers=2) as pool:
                leases=list(pool.map(lambda _:journal.claim(key,allowed=True),range(2)))
            self.assertEqual(sum(value is not None for value in leases),1)
            self.assertIsNone(Journal(path).claim(key,allowed=True))
            lease=next(value for value in leases if value)
            with self.assertRaises(ValueError):journal.finish(key,'wrong')
            journal.finish(key,lease)
            self.assertIsNone(Journal(path).claim(key,allowed=True))
            with self.assertRaises(ValueError):journal.finish(key,lease,'late-receipt')
            with self.assertRaises(ValueError):journal.claim(key)
