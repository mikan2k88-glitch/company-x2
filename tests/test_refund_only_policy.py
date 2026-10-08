import unittest
from company_x2.payments import Payments


class RefundOnlyPolicyTests(unittest.TestCase):
    def test_even_fully_configured_live_sales_are_closed(self):
        class Store:
            def company_rpc(self, action, payload=None):
                return {'live_schema_version': 19} if action == 'live_ping' else {'refund_schema_version': 20}
        payments = Payments({
            'STRIPE_LIVE_SECRET_KEY': 'sk_live_fixture',
            'STRIPE_LIVE_WEBHOOK_SECRET': 'whsec_fixture',
            'APP_PUBLIC_URL': 'https://example.com',
            'LIVE_PAYMENTS_ENABLED': 'true',
            'LIVE_PRICE_JPY': '300',
            'LIVE_SALES_TERMS_CONFIRMED': 'true',
            'SALES_TERMS_URL': 'https://example.com/sales-policy',
        })
        status = payments.live_status(Store())
        self.assertFalse(status['ready'])
        self.assertIn('返金以外の責任', status['reasons'][0])
        with self.assertRaises(ValueError):
            payments.checkout(Store(), {'id': 'blocked', 'plan': {'payment_mode': 'stripe_live'}}, 'owner')
