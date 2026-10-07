import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from company_x2.ai_planner import AIPlanner
from company_x2.store import Store

ENV = {'GEMINI_API_KEY':'private-fixture','AI_PROVIDER':'gemini','AI_ENABLED':'true',
       'AI_MONTHLY_BUDGET_MICRO_USD':'3000000','AI_DAILY_BUDGET_MICRO_USD':'100000'}
DECISION = {'service_key':'csv_to_json','single_supported_operation':True,
            'has_extra_conditions':False,'reason':'JSONへ変換します'}


def response(decision=None, finish='STOP'):
    return io.BytesIO(json.dumps({'candidates':[{'finishReason':finish,
        'content':{'parts':[{'text':json.dumps(DECISION if decision is None else decision)}]}}]}).encode())


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'db')
        self.calls = []
    def tearDown(self):
        self.tmp.cleanup()
    def analyze(self, opener, env=None, request='CSVをJSONに変換してください'):
        return AIPlanner(ENV if env is None else env, opener).analyze(self.store,request,'o'*32)
    def capture(self, req, timeout):
        self.calls.append(req)
        return response()
    def test_success_fixed_model_private_header_no_tools_and_cache(self):
        answer = self.analyze(self.capture)
        self.assertTrue(answer['supported'])
        self.assertFalse(answer['fallback_used'])
        self.assertEqual(answer['model'],'gemini-3.8-flash')
        self.assertEqual(self.analyze(self.capture),answer)
        self.assertEqual(len(self.calls),1)
        req = self.calls[0]
        self.assertIn('/gemini-3.8-flash:generateContent',req.full_url)
        self.assertNotIn('private-fixture',req.full_url)
        self.assertEqual(req.get_header('X-goog-api-key'),'private-fixture')
        body = json.loads(req.data)
        self.assertNotIn('tools',body)
        self.assertEqual(body['contents'][0]['parts'][0]['text'],'CSVをJSONに変換してください')
        self.assertEqual(body['generationConfig']['maxOutputTokens'],1024)
        self.assertEqual(body['generationConfig']['thinkingConfig']['thinkingLevel'],'low')
        self.assertEqual(self.store.company_rpc('overview')['ai_reserved_micro_usd'],answer['reserved_micro_usd'])
    def test_each_explicit_unavailable_error_falls_back_once(self):
        for code in (404,429,503):
            with self.subTest(code=code):
                calls=[]
                def opener(req,timeout):
                    calls.append(req)
                    if len(calls)==1:
                        raise urllib.error.HTTPError(req.full_url,code,'secret',{},None)
                    return response()
                answer = self.analyze(opener,request='JSON '+str(code))
                self.assertEqual(len(calls),2)
                self.assertEqual(answer['model'],'gemini-3.7-flash')
                self.assertTrue(answer['fallback_used'])
                self.assertEqual(answer['attempts'][0]['http_status'],code)
                self.assertEqual(self.analyze(opener,request='JSON '+str(code)),answer)
                self.assertEqual(len(calls),2)
    def test_auth_timeout_malformed_and_safety_never_fallback_or_retry(self):
        for kind in ('auth','timeout','malformed','safety','incomplete'):
            with self.subTest(kind=kind):
                calls=[]
                def opener(req,timeout):
                    calls.append(req)
                    if kind=='auth':raise urllib.error.HTTPError(req.full_url,401,'private-fixture',{},None)
                    if kind=='timeout':raise TimeoutError('private-fixture')
                    if kind=='malformed':return response({'service_key':'csv_to_json'})
                    return response(finish='SAFETY' if kind=='safety' else 'MAX_TOKENS')
                for _ in range(2):
                    with self.assertRaises(ValueError) as error:self.analyze(opener,{**ENV,'AI_DAILY_BUDGET_MICRO_USD':'1000000'},request='case '+kind)
                    self.assertNotIn('private-fixture',str(error.exception))
                self.assertEqual(len(calls),1)
    def test_both_models_unavailable_stops_and_records_attempts(self):
        calls=[]
        def opener(req,timeout):
            calls.append(req)
            raise urllib.error.HTTPError(req.full_url,503,'secret',{},None)
        for _ in range(2):
            with self.assertRaises(ValueError):self.analyze(opener)
        self.assertEqual(len(calls),2)
        with self.store.connect() as db:
            saved=json.loads(db.execute('select result from company_ai_calls').fetchone()[0])
        self.assertEqual(saved['state'],'failed')
        self.assertEqual(len(saved['attempts']),2)
    def test_budget_reserves_entire_chain_before_call(self):
        env={**ENV,'AI_DAILY_BUDGET_MICRO_USD':'1'}
        with self.assertRaises(ValueError):self.analyze(self.capture,env)
        self.assertEqual(self.calls,[])
    def test_concurrent_same_request_only_one_provider_call(self):
        def task(_):
            try:return self.analyze(self.capture)
            except ValueError:return None
        with ThreadPoolExecutor(2) as pool:list(pool.map(task,range(2)))
        self.assertEqual(len(self.calls),1)
    def test_multi_operation_refusal_is_not_retried(self):
        def opener(req,timeout):
            self.calls.append(req)
            return response({**DECISION,'has_extra_conditions':True})
        self.assertFalse(self.analyze(opener)['supported'])
        self.assertEqual(len(self.calls),1)
    def test_provider_selection_and_missing_key(self):
        self.assertEqual(AIPlanner({**ENV,'AI_PROVIDER':'openai'}).status()['provider'],'openai')
        self.assertFalse(AIPlanner({**ENV,'GEMINI_API_KEY':''}).status()['ready'])
        with self.assertRaises(ValueError):AIPlanner({'AI_PROVIDER':'unknown'})
