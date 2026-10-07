import base64
import io
import json
import threading
import unittest
import urllib.request
import urllib.error
import test_company_http as http_tests
from company_x2.server import handler_for
from company_x2.agent_client import request
from company_x2.agent_scout import summary

class AgentAccessTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call
    def test_scoped_bearer_and_status(self):
        self.server.RequestHandlerClass=handler_for(self.store,'admin',access_password='password',agent_token='a'*40)
        auth={'Authorization':'Bearer '+'a'*40}
        self.assertEqual(self.call('/api/company/agent-scout',auth=False,headers=auth)['items'],[])
        for path in ('/company','/api/company/status','/api/company/agent-scout/status'):
            with self.assertRaises(urllib.error.HTTPError):self.call(path,auth=False,headers=auth)
        with self.assertRaises(urllib.error.HTTPError):self.call('/api/company/agent-scout',auth=False,headers={'Authorization':'Bearer wrong'})
        self.assertTrue(self.call('/api/company/agent-scout/status')['attention_required'])
        self.call('/api/company/agent-scout',{'run_key':'hourly_empty_000001','urls':[],'checkpoint':{}},auth=False,headers=auth)
        self.assertFalse(self.call('/api/company/agent-scout/status')['attention_required'])
    def test_client_fixed_destination_and_bounded_output(self):
        def opener(req,timeout):
            self.assertEqual(req.full_url,'https://company-x2.onrender.com/api/company/agent-scout')
            self.assertEqual(req.get_header('Authorization'),'Bearer '+'a'*40)
            return io.BytesIO(b'{"items":[]}')
        self.assertEqual(request(opener=opener,token='a'*40),{'items':[]})
        with self.assertRaises(ValueError):request(token='short',opener=opener)
