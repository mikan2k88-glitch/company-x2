import hashlib
import tempfile
import unittest
from pathlib import Path
from company_x2.delivery_journal import Journal
from company_x2.delivery_experiment import deliver_once
from company_x2.staged_delivery import StagedAdapter


class StagedDeliveryTests(unittest.TestCase):
    def test_stop_or_changed_target_after_staging_prevents_commit_and_retry(self):
        for change in ('stop','destination','artifact'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                live=[True];commits=[]
                def stage(destination,artifact):
                    result=dict(destination=destination,artifact_sha256=hashlib.sha256(artifact).hexdigest())
                    if change=='stop':live[0]=False
                    else:result['destination' if change=='destination' else 'artifact_sha256']='changed'
                    return result
                backend=type('SyntheticBackend',(),{'stage':staticmethod(stage),
                    'commit':staticmethod(lambda staged:commits.append(staged))})()
                args=dict(contact='contact',reply='reply',plan='plan',destination='fixed',artifact=b'x',
                    approved_sha256=hashlib.sha256(b'x').hexdigest(),adapter=StagedAdapter(backend),authorize=lambda:live[0])
                journal=Journal(Path(tmp)/'journal')
                with self.assertRaises(ValueError):deliver_once(journal,**args)
                self.assertFalse(commits)
                live[0]=True
                self.assertEqual(deliver_once(journal,**args)['state'],'uncertain')
                self.assertFalse(commits)

    def test_valid_staged_commit_has_one_matching_receipt(self):
        commits=[]
        def stage(destination,artifact):
            return dict(destination=destination,artifact_sha256=hashlib.sha256(artifact).hexdigest())
        def commit(staged):
            commits.append(staged)
            return dict(id='synthetic-receipt',**staged)
        backend=type('SyntheticBackend',(),{'stage':staticmethod(stage),'commit':staticmethod(commit)})()
        with tempfile.TemporaryDirectory() as tmp:
            args=dict(contact='contact',reply='reply',plan='plan',destination='fixed',artifact=b'x',
                approved_sha256=hashlib.sha256(b'x').hexdigest(),adapter=StagedAdapter(backend),authorize=lambda:True)
            journal=Journal(Path(tmp)/'journal')
            self.assertEqual(deliver_once(journal,**args)['state'],'confirmed')
            self.assertTrue(deliver_once(journal,**args)['replayed'])
            self.assertEqual(len(commits),1)
