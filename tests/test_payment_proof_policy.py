from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.handlers import payments as payment_handlers
from app.models.enums import PaymentStatus
from app.services.payment_service import PaymentService


def test_admin_created_payment_is_not_auto_approved_before_proof(monkeypatch) -> None:
    actor_id = uuid4()
    payment_id = uuid4()
    payload = SimpleNamespace(allocations=[SimpleNamespace(member_id=actor_id)])
    user = SimpleNamespace(id=actor_id)
    captured: dict[str, object] = {}

    class Payments:
        def submit(self, db, submitted_by, submitted_payload):
            captured["submit"] = (db, submitted_by, submitted_payload)
            return SimpleNamespace(id=payment_id)

    class Audit:
        def record(self, db, **kwargs):
            captured["audit"] = kwargs

    monkeypatch.setattr(payment_handlers, "user_has_permission", lambda *_: True)
    handler = payment_handlers.PaymentHandler()
    handler.payments = Payments()
    handler.audit = Audit()

    result = handler.create(SimpleNamespace(), user, payload)

    assert result.id == payment_id
    assert captured["audit"]["after_data"] == {
        "revision": 1,
        "auto_approved": False,
        "proof_required": True,
    }


def test_manual_approval_rejects_payment_without_current_revision_proof() -> None:
    payment_id = uuid4()
    payment = SimpleNamespace(
        id=payment_id,
        status=PaymentStatus.PENDING_VERIFICATION,
        current_revision=1,
    )

    class Repository:
        def get_for_update(self, _db, requested_id):
            assert requested_id == payment_id
            return payment

    class Database:
        def scalar(self, _query):
            return None

    service = PaymentService(repository=Repository())
    with pytest.raises(HTTPException, match="screenshot is required") as error:
        service.approve(Database(), payment_id, uuid4())

    assert error.value.status_code == 409
