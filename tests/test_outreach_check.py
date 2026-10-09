import unittest,urllib.error
from company_x2.outreach_check import check

ENV={'GITHUB_OUTREACH_TOKEN':'secret-fixture','GITHUB_OUTREACH_LOGIN':'fixture','OUTREACH_GITHUB_REPOS':'example/tasks'}

class Client:
    def __init__(self,user='fixture',error=None):self.calls=[];self.user=user;self.error=error
    def api(self,path,data=None):
        if data is not None:raise AssertionError('Must never write')
        self.calls.append(path)
        if self.error:raise self.error
        if path=='/user':return {'login':self.user}
        return {'full_name':'example/tasks','has_issues':True,'permissions':{'push':False}}

class OutreachCheckTests(unittest.TestCase):
    def test_missing_configuration_does_not_call_github(self):
        for env in ({},{**ENV,'GITHUB_OUTREACH_LOGIN':'bad/name'},{**ENV,'OUTREACH_GITHUB_REPOS':'https://bad'}):
            client=Client();self.assertFalse(check(env,client)['connection_ok']);self.assertEqual(client.calls,[])
    def test_read_only_check_works_while_sending_disabled(self):
        client=Client();result=check(ENV,client)
        self.assertTrue(result['connection_ok']);self.assertFalse(result['sending_enabled'])
        self.assertEqual(client.calls,['/user','/repos/example/tasks'])
        self.assertNotIn('secret-fixture',str(result))
    def test_identity_failure_stops_repository_reads(self):
        client=Client(user='someone-else');self.assertFalse(check(ENV,client)['connection_ok']);self.assertEqual(client.calls,['/user'])
    def test_errors_do_not_expose_credentials_or_response(self):
        for error in (TimeoutError('secret-fixture'),urllib.error.HTTPError('https://api.github.com',401,'secret-fixture',{},None)):
            result=check(ENV,Client(error=error));self.assertFalse(result['connection_ok']);self.assertNotIn('secret-fixture',str(result))
    def test_archived_repository_fails_connection(self):
        client=Client();original=client.api
        client.api=lambda path,data=None:original(path,data) if path=='/user' else {'full_name':'example/tasks','has_issues':True,'archived':True}
        self.assertFalse(check(ENV,client)['connection_ok'])
