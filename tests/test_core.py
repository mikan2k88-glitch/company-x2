import csv
import unittest
from company_x2.csv_service import deduplicate_csv
from company_x2.workflow import Job, State, advance

class CoreTests(unittest.TestCase):
    def test_csv_preserves_quoted_fields_and_order(self):
        result = deduplicate_csv('name,note\nA,"x,y"\nA,"x,y"\nB,z\n')
        self.assertEqual(result["output_rows"], 2)
        self.assertEqual(result["removed_rows"], 1)
        self.assertIn('A,"x,y"', result["csv"])

    def test_csv_rejects_malformed_records(self):
        for text in ["a,b\n1\n", "a,a\n1,2\n", 'a\n"unterminated']:
            with self.assertRaises((ValueError, csv.Error)):
                deduplicate_csv(text)

    def test_no_skipping_or_mock_revenue(self):
        job = Job("one", price_jpy=1000, cost_limit_jpy=100)
        with self.assertRaises(ValueError):
            advance(job, State.PAID, evidence={"mode": "live", "capture_confirmed": True})
        with self.assertRaises(ValueError):
            advance(job, State.QUALIFIED, evidence={"mode": "mock", "real_opportunity": True,
                                                  "supported_service": True})

    def test_full_evidence_chain(self):
        job = Job("one", price_jpy=1000, cost_limit_jpy=100)
        chain = [(State.QUALIFIED, "real_opportunity"), (State.AGREED, "customer_agreement"),
                 (State.AUTHORIZED, "authorization_confirmed"), (State.PRODUCED, "artifact_saved"),
                 (State.VERIFIED, "quality_passed"), (State.DELIVERED, "delivery_confirmed"),
                 (State.PAID, "capture_confirmed")]
        for target, key in chain:
            job = advance(job, target, evidence={"mode": "live", key: True, "supported_service": True})
        with self.assertRaises(ValueError):
            advance(job, State.CANCELLED, evidence={"payment_released": True})

    def test_budget_and_cancel_guards(self):
        with self.assertRaises(ValueError):
            advance(Job("bad", price_jpy=100, cost_limit_jpy=100), State.QUALIFIED,
                    evidence={"mode": "live", "real_opportunity": True, "supported_service": True})
        with self.assertRaises(ValueError):
            advance(Job("one"), State.CANCELLED, evidence={})

if __name__ == "__main__":
    unittest.main()
