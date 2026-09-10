"""Exercise both real approval paths and reversal, rolling back every write.

Run from bnc-be: python -m scripts.check_verified_approval PAY-XXXXXXXXXX
No network delivery jobs are run. This must never commit.
"""
import sys
from unittest.mock import patch
from sqlalchemy import select, func
from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.models.backup import GoogleConnection
from app.models.payments import Payment
from app.models.fund import FundEntry
from app.models.verification import PaymentUtrClaim
from app.services.gmail_verification_oauth_service import PURPOSE
from app.services.payment_reconciliation_service import PaymentReconciliationService
from app.services.payment_service import PaymentService


def main(payment_no: str):
    for human in (True, False):
        with SessionLocal() as db:
            try:
                payment = db.scalar(select(Payment).where(Payment.payment_no == payment_no))
                assert payment and payment.status.value == 'PENDING_VERIFICATION', 'Needs an existing pending payment'
                connection = db.scalar(select(GoogleConnection).where(GoogleConnection.purpose == PURPOSE))
                before = db.scalar(select(func.count()).select_from(FundEntry))
                mode = get_settings().model_copy(update={
                    'payment_auto_verify_enabled': not human,
                    'payment_auto_verify_shadow_mode': human,
                })
                with patch('app.services.payment_reconciliation_service.get_settings', return_value=mode):
                    result = PaymentReconciliationService().reconcile_payment(
                        db, payment.id, connection.connected_by, approve_verified=human)
                assert result == ('VERIFIED_APPROVED' if human else 'AUTO_APPROVED'), result
                db.flush()
                assert payment.status.value == 'APPROVED'
                assert db.scalar(select(func.count()).select_from(FundEntry)) == before + 1
                claim = db.get(PaymentUtrClaim, payment.auto_verified_reference)
                assert claim and claim.payment_id == payment.id
                assert PaymentReconciliationService().reconcile_payment(db, payment.id, connection.connected_by) == 'NOT_PENDING'
                PaymentService().reverse(db, payment.id, connection.connected_by, 'Rollback-only verification check')
                db.flush()
                assert payment.status.value == 'REVERSED'
                assert db.scalar(select(func.count()).select_from(FundEntry)) == before + 2
                assert db.get(PaymentUtrClaim, payment.auto_verified_reference) is not None
                print(('ADMIN' if human else 'AUTO') + ': approval, duplicate prevention and reversal passed; rolling back')
            finally:
                db.rollback()
    with SessionLocal() as db:
        status = db.scalar(select(Payment.status).where(Payment.payment_no == payment_no))
        assert status.value == 'PENDING_VERIFICATION'
        print('Confirmed payment remains pending; no approvals or reversals persisted')


if __name__ == '__main__':
    main(sys.argv[1])
