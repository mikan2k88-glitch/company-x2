import unittest
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from company_x2.delivery_permission import Permit,require_delivery_permission


class PermissionTests(unittest.TestCase):
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
                        replace(permit,destination='https://other.invalid/orders/1'),
                        replace(permit,destination='https://synthetic.invalid/orders/1#other')):
            with self.assertRaises(ValueError):require_delivery_permission(changed,current,stopped=False,now=now)
