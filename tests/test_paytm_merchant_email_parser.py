from decimal import Decimal
from unittest import TestCase

from app.engines.payment_verification.paytm_merchant_email_parser import (
    merchant_names_match,
    parse_paytm_merchant_payment,
)


PAYTM_EMAIL = """
Payment Received
₹ 4
Rupees Four only
From
BHIM UPI kayeXX@axl
In Account of
KAYEF AHAMAD
Sep 14, 2026, 7:36 AM
Order ID: T2609140736451903593643
"""


class PaytmMerchantEmailParserTests(TestCase):
    def test_parses_authenticated_merchant_payment_fields(self):
        parsed = parse_paytm_merchant_payment(PAYTM_EMAIL)

        self.assertTrue(parsed.valid)
        self.assertEqual(parsed.amount, Decimal("4"))
        self.assertEqual(parsed.sender_name, "BHIM UPI")
        self.assertEqual(parsed.sender_vpa, "kayexx@axl")
        self.assertEqual(parsed.merchant_name, "KAYEF AHAMAD")
        self.assertEqual(parsed.paytm_order_id, "T2609140736451903593643")
        self.assertEqual(parsed.transaction_at.isoformat(), "2026-09-14T02:06:00+00:00")

    def test_merchant_name_requires_an_exact_normalized_match(self):
        self.assertTrue(merchant_names_match("Kayef  Ahamad", "KAYEF AHAMAD"))
        self.assertFalse(merchant_names_match("Different Merchant", "KAYEF AHAMAD"))

    def test_missing_order_id_is_not_a_valid_payment_notification(self):
        parsed = parse_paytm_merchant_payment(PAYTM_EMAIL.replace("Order ID: T2609140736451903593643", ""))
        self.assertFalse(parsed.valid)
        self.assertEqual(parsed.error_code, "MISSING_ORDER_ID")
