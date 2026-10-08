import unittest
import urllib.error
import test_company_http as http_tests
from company_x2.intake_risk import assess
from company_x2.company import quote, validate_creation


SAFE = dict(sensitive_data='no', critical_use='no', extra_liability='no')


class IntakeRiskTests(unittest.TestCase):
    def test_unknown_is_not_approval_and_each_risk_is_rejected(self):
        self.assertEqual(assess()['decision'], 'needs_information')
        for key in SAFE:
            for value in ('yes', 'unknown'):
                context = {**SAFE, key: value}
                self.assertNotEqual(assess(context)['decision'], 'limited_scope')
                with self.assertRaises(ValueError):
                    quote('csv_to_json', 'id\n001\n', risk_context=context)

    def test_declarations_are_bound_to_order_hash(self):
        plan = quote('csv_to_json', 'id\n001\n', risk_context=SAFE)
        data = dict(service_key='csv_to_json', csv='id\n001\n', request_key='k'*32,
                    terms_accepted=True, plan_sha256=plan['plan_sha256'], risk_context=SAFE)
        saved = validate_creation(data, 't'*32)
        self.assertEqual(saved['plan']['intake_risk']['declarations'], SAFE)
        self.assertEqual(saved['plan']['intake_risk']['decision'], 'limited_scope')
        # Omitting previously checked declarations is not an API bypass.
        data.pop('risk_context')
        with self.assertRaises(ValueError):
            validate_creation(data, 't'*32)

    def test_forged_or_missing_answers_fail_closed(self):
        for value in ({}, 'approved', {**SAFE, 'extra_liability': False}, {**SAFE, 'approved': True}):
            with self.assertRaises(ValueError):
                assess(value)
        with self.assertRaises(ValueError):
            quote('csv_to_json', 'id\n001\n', 'stripe_live', 300, 'https://example.com/terms')


class IntakeRiskHTTPTests(unittest.TestCase):
    setUp = http_tests.CompanyHTTPTests.setUp
    tearDown = http_tests.CompanyHTTPTests.tearDown
    call = http_tests.CompanyHTTPTests.call

    def test_direct_api_cannot_skip_or_contradict_screening(self):
        chosen = dict(service_key='csv_to_json', csv='id\n001\n')
        for context in (None, {**SAFE, 'critical_use':'yes'}, {**SAFE, 'extra_liability':'unknown'}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.call('/api/company/quote', {**chosen, 'risk_context':context})
            self.assertEqual(error.exception.code,400)
        plan = self.call('/api/company/quote', {**chosen, 'risk_context':SAFE})['plan']
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call('/api/company/transactions', {**chosen, 'risk_context':None,
                'terms_accepted':True, 'plan_sha256':plan['plan_sha256'], 'request_key':'k'*32})
        self.assertEqual(error.exception.code,400)
        self.assertEqual(self.store.company_rpc('overview')['counts'],{})
