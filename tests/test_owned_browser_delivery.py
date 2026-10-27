from datetime import datetime,timedelta,timezone
import sys
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
