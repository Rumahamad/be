from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import current_user
from app.api.v1 import payments as payments_api
from app.db.session import get_db
from app.main import app
from app.models.enums import PaymentStatus
from app.models.identity import User
from app.models.payments import Payment
from app.services.email_service import EmailDeliveryError
from app.services.receipt_delivery_service import ReceiptDeliveryResult, ReceiptDeliveryService


class FakeProvider:
    name = "TEST_EMAIL"

    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.messages = []

    def send(self, email):
        if self.error:
            raise EmailDeliveryError(self.error)
        self.messages.append(email)
        return "provider-message-1"


class FakeDb:
    def __init__(self, payment, recipient) -> None:
        self.payment = payment
        self.recipient = recipient

    def get(self, model, object_id):
        if model is Payment and object_id == self.payment.id:
            return self.payment
        if model is User and object_id == self.recipient.id:
            return self.recipient
        return None


def make_delivery_service(monkeypatch, provider):
    payment_id = uuid4()
    recipient_id = uuid4()
    actor = SimpleNamespace(id=uuid4())
    payment = SimpleNamespace(
        id=payment_id,
        payment_no="PAY-TEST",
        status=PaymentStatus.APPROVED,
        submitted_by=recipient_id,
    )
    recipient = SimpleNamespace(
        id=recipient_id,
        email="member@example.com",
        display_name="BNC Member",
    )
    service = ReceiptDeliveryService(provider=provider)
    audit_events = []
    service.receipts = SimpleNamespace(
        render=lambda db, requested_id: (
            b"%PDF-test",
            SimpleNamespace(id=uuid4(), receipt_no="RCT-TEST"),
        )
    )
    service.audit = SimpleNamespace(record=lambda db, **values: audit_events.append(values))
    monkeypatch.setattr(
        "app.services.receipt_delivery_service.get_settings",
        lambda: SimpleNamespace(
            frontend_url="https://bnc.pp.ua",
            email_app_name="BNC",
        ),
    )
    return service, FakeDb(payment, recipient), actor, payment_id, audit_events


def test_receipt_delivery_sends_pdf_and_records_audit(monkeypatch) -> None:
    provider = FakeProvider()
    service, db, actor, payment_id, events = make_delivery_service(monkeypatch, provider)

    result = service.send(db, actor=actor, payment_id=payment_id)

    assert result.recipient == "member@example.com"
    assert result.receipt_no == "RCT-TEST"
    assert provider.messages[0].attachment.content == b"%PDF-test"
    assert provider.messages[0].attachment.filename == "RCT-TEST.pdf"
    assert events[0]["action"] == "payment.receipt_emailed"
    assert events[0]["after_data"]["recipient_user_id"] == str(db.recipient.id)


def test_receipt_delivery_records_provider_failure(monkeypatch) -> None:
    provider = FakeProvider(error="provider unavailable")
    service, db, actor, payment_id, events = make_delivery_service(monkeypatch, provider)

    with pytest.raises(EmailDeliveryError, match="provider unavailable"):
        service.send(db, actor=actor, payment_id=payment_id)

    assert events[0]["action"] == "payment.receipt_email_failed"
    assert events[0]["after_data"]["error"] == "provider unavailable"


def test_email_receipt_route_reuses_payment_authorization(monkeypatch) -> None:
    user = SimpleNamespace(id=uuid4())
    payment_id = uuid4()
    checked = []

    class Db:
        def commit(self):
            pass

        def rollback(self):
            pass

    class Handler:
        def detail(self, db, actor, requested_id):
            checked.append((actor, requested_id))
            return SimpleNamespace(status="APPROVED")

    class Delivery:
        def send(self, db, *, actor, payment_id):
            return ReceiptDeliveryResult(
                receipt_no="RCT-TEST",
                recipient="member@example.com",
                provider="TEST_EMAIL",
                provider_message_id="message-1",
            )

    monkeypatch.setattr(payments_api, "handler", Handler())
    monkeypatch.setattr(payments_api, "receipt_delivery_service", Delivery())
    app.dependency_overrides[get_db] = Db
    app.dependency_overrides[current_user] = lambda: user
    try:
        response = TestClient(app).post(f"/api/v1/payments/{payment_id}/receipt/email")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "status": "SENT",
        "receipt_no": "RCT-TEST",
        "recipient": "member@example.com",
    }
    assert checked == [(user, payment_id)]
