import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from company_x2.github_source import read_json, GitHubUnavailable
from company_x2.cloud_scout import run, QUERIES
from company_x2.agent_scout import state, summary, register
from company_x2.store import Store
from company_x2.supabase_store import NoRedirect


class GitHubSourceTests(unittest.TestCase):
    def test_rate_limit_is_safe_and_waits_until_reset(self):
        def failed(req,timeout):
            raise urllib.error.HTTPError(req.full_url,403,'private',
                {'X-RateLimit-Remaining':'0','Retry-After':'3600'},io.BytesIO(b'secret'))
        with self.assertRaises(GitHubUnavailable) as caught:
            read_json('https://api.github.com/search/issues?q=csv','search',opener=failed)
        err=caught.exception
        self.assertEqual(err.diagnostic()['reason'],'rate_limited')
        self.assertEqual(err.retry_after,3600)
        self.assertNotIn('private',str(err));self.assertNotIn('secret',str(err))

    def test_optional_token_never_redirects(self):
        def redirected(req,timeout):
            self.assertEqual(req.get_header('Authorization'),'Bearer dedicated-secret')
            NoRedirect().redirect_request(req,None,302,'redirect',{},'https://evil.example/')
        with patch.dict(os.environ,{'GITHUB_SCOUT_TOKEN':'dedicated-secret'}):
            with self.assertRaises(GitHubUnavailable) as caught:
                read_json('https://api.github.com/repos/example/jobs/issues/1','issue',opener=redirected)
        self.assertNotIn('dedicated-secret',str(caught.exception))
        self.assertEqual(caught.exception.reason,'connection_or_invalid_response')

    def test_failed_source_preserves_candidates_and_waits_without_retrying(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db')
            now=datetime(2026,10,8,1,tzinfo=timezone.utc)
            run(store,lambda q:[],now=now)
            before=state(store)
            failed_at=now+timedelta(hours=1)
            def failed(q):raise GitHubUnavailable('search','rate_limited',status=403,retry_after=3600)
            with self.assertRaises(GitHubUnavailable):run(store,failed,now=failed_at)
            after=state(store)
            for k in ('items','checkpoint','recent_runs','checked_at'):
                self.assertEqual(after[k],before[k])
            with self.assertRaises(GitHubUnavailable):
                run(store,lambda q:self.fail('cooldown searched'),now=failed_at+timedelta(minutes=1))
            self.assertEqual(summary(store)['last_success_at'],before['checked_at'])
            self.assertEqual(summary(store)['last_failure']['diagnostic']['http_status'],403)
            register(store,{'run_key':'attempt_20261008_02','urls':[],
                'checkpoint':{'next_query':before['checkpoint']['next_query'],'note':'retry next hour'}})
            self.assertEqual(state(store)['last_failure'],after['last_failure'])
            with self.assertRaises(ValueError):
                register(store,{'run_key':'attempt_20261008_03','urls':[],
                    'checkpoint':{'next_query':'advance without reading'}})
            run(store,lambda q:[],now=failed_at+timedelta(hours=1))
            self.assertIsNone(summary(store)['last_failure'])

    def test_failure_record_is_not_a_success(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db')
            register(store,{'run_key':'attempt_20261008_01','urls':[],'checkpoint':{}})
            self.assertIsNone(summary(store)['last_success_at'])
            self.assertTrue(summary(store)['attention_required'])

    def test_issue_failure_does_not_publish_partial_search(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'db')
            now=datetime(2026,10,8,1,tzinfo=timezone.utc)
            raw={'id':1,'html_url':'https://github.com/example/jobs/issues/1',
                 'title':'CSV to JSON $10','state':'open','body':''}
            def failed(url):raise GitHubUnavailable('issue','http_error',status=502)
            with self.assertRaises(GitHubUnavailable):
                run(store,lambda q:[raw],failed,now)
            self.assertEqual(state(store)['items'],[])
            self.assertIsNone(state(store)['checkpoint'])
            self.assertEqual(state(store)['last_failure']['diagnostic']['stage'],'issue')


import test_company_http as http_tests
class SourceHTTPTests(unittest.TestCase):
    setUp=http_tests.CompanyHTTPTests.setUp
    tearDown=http_tests.CompanyHTTPTests.tearDown
    call=http_tests.CompanyHTTPTests.call

    def test_source_failure_has_actionable_diagnostic_not_storage_error(self):
        with patch('company_x2.company_http.cloud_run',side_effect=GitHubUnavailable('search','incomplete_search')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.call('/api/company/agent-scout',{'action':'cloud_run'})
        self.assertEqual(caught.exception.code,503)
        payload=json.load(caught.exception)
        self.assertEqual(payload['diagnostic']['reason'],'incomplete_search')
        self.assertNotIn('Storage unavailable',payload['error'])
