"""Financial guard regressions; isolated from providers and live data."""
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.payment_reconciliation_service import PaymentReconciliationService


class ReconciliationSafetyTests(TestCase):
    def setUp(self):
        self.service = PaymentReconciliationService()
        self.service.payments = MagicMock()
        self.service._event = MagicMock()
        self.payment = SimpleNamespace(id=uuid4(), current_revision=1,
                                       total_amount=Decimal("500.00"))
        self.credit = SimpleNamespace(id=uuid4(), parse_status="READY", sender_verified=True,
            recipient_account_matches=True, consumed_at=None, matched_payment_id=None,
            amount=Decimal("500.00"), authentication_evidence={'verified': True, 'version': 'gmail-arc-v2'})
        self.db = MagicMock()
        self.db.get.return_value = None

    def match(self):
        return self.service._match(self.db, self.payment, "123456789012", uuid4())

    def test_duplicate_claim_never_approves(self):
        self.db.scalar.return_value = 2
        self.assertEqual(self.match(), "DUPLICATE_REFERENCE")
        self.service.payments.approve.assert_not_called()

    def test_consumed_credit_never_approves(self):
        self.credit.consumed_at = object()
        self.db.scalar.side_effect = [1, self.credit]
        self.assertEqual(self.match(), "DUPLICATE_REFERENCE")
        self.service.payments.approve.assert_not_called()

    def test_amount_mismatch_never_approves(self):
        self.credit.amount = Decimal("499.99")
        self.db.scalar.side_effect = [1, self.credit]
        self.assertEqual(self.match(), "AMOUNT_MISMATCH")
        self.service.payments.approve.assert_not_called()

    def test_untrusted_credit_never_approves(self):
        self.credit.sender_verified = False
        self.db.scalar.side_effect = [1, self.credit]
        self.assertEqual(self.match(), "UNTRUSTED_EMAIL")
        self.service.payments.approve.assert_not_called()

    def test_shadow_match_does_not_reserve_or_consume(self):
        self.db.scalar.side_effect = [1, self.credit]
        with patch("app.services.payment_reconciliation_service.get_settings",
                   return_value=SimpleNamespace(payment_auto_verify_enabled=False,
                                                payment_auto_verify_shadow_mode=True)):
            self.assertEqual(self.match(), "SHADOW_MATCH")
        self.assertIsNone(self.credit.matched_payment_id)
        self.assertIsNone(self.credit.consumed_at)
        self.service.payments.approve.assert_not_called()

    def test_permanent_claim_blocks_even_after_reversal(self):
        self.db.get.return_value = SimpleNamespace(payment_id=uuid4())
        self.assertEqual(self.match(), 'DUPLICATE_REFERENCE')
        self.service.payments.approve.assert_not_called()

    def test_verified_admin_approval_uses_same_checks(self):
        self.db.scalar.side_effect = [1, self.credit]
        result = self.service._match(self.db, self.payment, '123456789012', uuid4(), approve_verified=True)
        self.assertEqual(result, 'VERIFIED_APPROVED')
        self.assertEqual(self.service.payments.approve.call_args.kwargs['verification_method'], 'HDFC_EMAIL_ADMIN')
        self.assertIsNotNone(self.credit.consumed_at)

    def test_auto_mode_approves_exact_trusted_match(self):
        self.db.scalar.side_effect = [1, self.credit]
        with patch('app.services.payment_reconciliation_service.get_settings',
                   return_value=SimpleNamespace(payment_auto_verify_enabled=True, payment_auto_verify_shadow_mode=False)):
            self.assertEqual(self.match(), 'AUTO_APPROVED')
        self.assertIsNotNone(self.credit.consumed_at)
