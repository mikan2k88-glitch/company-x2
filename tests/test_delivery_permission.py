import unittest
import hashlib
import tempfile
from pathlib import Path
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from company_x2.delivery_permission import Permit,require_delivery_permission
from company_x2.delivery_permission import deliver_permitted
from company_x2.delivery_journal import Journal


class PermissionTests(unittest.TestCase):
    def test_coordinator_stop_and_live_recheck_prevent_send(self):
        artifact=b'sku\n001\n';digest=hashlib.sha256(artifact).hexdigest();sends=[]
        permit=Permit('https://synthetic.invalid','https://synthetic.invalid/orders/1',
            'contact','reply','a'*64,digest,datetime.now(timezone.utc)+timedelta(minutes=5),'test-policy')
        current={key:getattr(permit,key) for key in ('contact_id','reply_id','plan_sha256','artifact_sha256','destination')}
        current.update(source_rechecked=True,inspection_passed=True,plan_accepted=True)
        def send(destination,data):
            sends.append(destination)
            return dict(id='synthetic-receipt',destination=destination,artifact_sha256=hashlib.sha256(data).hexdigest())
        adapter=type('SyntheticAdapter',(),{'send':staticmethod(send)})()
        with tempfile.TemporaryDirectory() as tmp:
            journal=Journal(Path(tmp)/'journal')
            with self.assertRaises(ValueError):deliver_permitted(journal,permit,artifact,adapter,lambda:current)
            self.assertFalse(sends)
            checks=iter([current,current,{**current,'plan_accepted':False}])
            with self.assertRaises(ValueError):deliver_permitted(journal,permit,artifact,adapter,lambda:next(checks),is_stopped=lambda:False)
            self.assertFalse(sends)
            # The interrupted claimed attempt is not automatically retried.
            result=deliver_permitted(journal,permit,artifact,adapter,lambda:current,is_stopped=lambda:False)
            self.assertEqual(result['state'],'uncertain');self.assertFalse(sends)
            permit=replace(permit,reply_id='new-reply');current['reply_id']='new-reply'
            self.assertEqual(deliver_permitted(journal,permit,artifact,adapter,lambda:current,is_stopped=lambda:False)['state'],'confirmed')
            self.assertEqual(len(sends),1)

    def test_default_stop_scope_changes_and_expiry_fail_closed(self):
        now=datetime.now(timezone.utc)
        permit=Permit('https://synthetic.invalid','https://synthetic.invalid/orders/1',
            'contact','reply','a'*64,'b'*64,now+timedelta(minutes=5),'operator-reviewed-test-policy')
        current={key:getattr(permit,key) for key in ('contact_id','reply_id','plan_sha256','artifact_sha256','destination')}
        current.update(source_rechecked=True,inspection_passed=True,plan_accepted=True)
        with self.assertRaises(ValueError):require_delivery_permission(permit,current,now=now)
        self.assertTrue(require_delivery_permission(permit,current,stopped=False,now=now))
        for key in current:
            with self.assertRaises(ValueError):require_delivery_permission(permit,{**current,key:'changed'},stopped=False,now=now)
        for changed in (replace(permit,expires_at=now),replace(permit,policy_evidence=''),
                        replace(permit,expires_at=None),replace(permit,artifact_sha256=None),
                        replace(permit,contact_id=''),replace(permit,origin='https://synthetic.invalid:bad'),
                        replace(permit,destination='https://other.invalid/orders/1'),
                        replace(permit,destination='https://synthetic.invalid/orders/1#other')):
            with self.assertRaises(ValueError):require_delivery_permission(changed,current,stopped=False,now=now)
