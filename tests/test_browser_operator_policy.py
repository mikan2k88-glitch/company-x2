from dataclasses import replace
from datetime import datetime,timedelta,timezone
import unittest
from unittest.mock import patch
from company_x2.browser_operator_policy import BrowserPolicy,require_policy,deliver_with_policy
from company_x2.delivery_permission import Permit


class BrowserPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.permit=Permit('https://synthetic.invalid','https://synthetic.invalid/order/1',
            'contact','reply','a'*64,'b'*64,self.now+timedelta(minutes=5),'synthetic')
        self.policy=BrowserPolicy(self.permit.origin,self.permit.origin+'/upload',
            self.now+timedelta(minutes=1),'synthetic site review','synthetic account review','synthetic runtime review')

    def test_default_disabled_missing_evidence_foreign_route_and_expiry(self):
        enabled=replace(self.policy,enabled=True)
        for policy in (self.policy,replace(enabled,account_permission_evidence=''),
                replace(enabled,runtime_validation_evidence=' '),replace(enabled,upload_url='https://foreign.invalid/upload'),
                replace(enabled,expires_at=self.now),replace(enabled,expires_at=self.now.replace(tzinfo=None))):
            with self.subTest(policy=policy),self.assertRaises(ValueError):require_policy(policy,self.permit,now=self.now)
        self.assertTrue(require_policy(enabled,self.permit,now=self.now))

    def test_policy_is_rechecked_by_downstream_stop_callback(self):
        policy=replace(self.policy,enabled=True)
        def downstream(*args,**kwargs):
            self.assertFalse(kwargs['is_stopped']())
            with patch('company_x2.browser_operator_policy.require_policy',side_effect=ValueError('Expired')):
                with self.assertRaises(ValueError):kwargs['is_stopped']()
            return {'state':'synthetic'}
        with patch('company_x2.browser_operator_policy.deliver_owned_browser',side_effect=downstream) as delivery:
            args=(policy,None,self.permit,None,None,None,'reply',None,'owner',{})
            with self.assertRaises(ValueError):deliver_with_policy(*args,node_executable='unused')
            delivery.assert_not_called()
            self.assertEqual(deliver_with_policy(*args,node_executable='unused',is_stopped=lambda:False)['state'],'synthetic')
