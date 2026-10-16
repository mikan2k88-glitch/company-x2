import hashlib
import tempfile
import unittest
from pathlib import Path
from company_x2.delivery_journal import Journal
from company_x2.delivery_experiment import deliver_once


class DeliveryTests(unittest.TestCase):
    def test_crash_after_send_restart_never_sends_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'journal';journal=Journal(path);sends=[]
            def send(destination,artifact):
                sends.append(destination)
                raise KeyboardInterrupt('Synthetic crash after click')
            adapter=type('SyntheticSite',(),{'send':staticmethod(send)})()
            args=dict(contact='contact',reply='reply',plan='plan',destination='fixed-target',
                artifact=b'sku\n001\n',adapter=adapter,authorize=lambda:True)
            with self.assertRaises(KeyboardInterrupt):deliver_once(journal,**args)
            self.assertEqual(deliver_once(Journal(path),**args)['state'],'sending')
            self.assertEqual(len(sends),1)

    def test_verified_acknowledgement_and_stop_before_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'journal');sends=[]
            def send(destination,artifact):
                sends.append(destination)
                return dict(id='synthetic-receipt',destination=destination,artifact_sha256=hashlib.sha256(artifact).hexdigest())
            adapter=type('SyntheticSite',(),{'send':staticmethod(send)})()
            args=dict(contact='contact',reply='reply',plan='plan',destination='fixed-target',artifact=b'sku\n001\n',adapter=adapter)
            checks=iter([True,False])
            with self.assertRaises(ValueError):deliver_once(journal,**args,authorize=lambda:next(checks))
            self.assertFalse(sends)
            self.assertEqual(deliver_once(journal,**args,authorize=lambda:True)['state'],'uncertain')
            args['destination']='second-fixed-target'
            self.assertEqual(deliver_once(journal,**args,authorize=lambda:True)['state'],'confirmed')
            self.assertEqual(len(sends),1)
