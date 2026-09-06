from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.services.receipt_service import ReceiptService


def test_receipt_renderer_creates_valid_pdf() -> None:
    service = ReceiptService()
    payment = SimpleNamespace(
        payment_no="PAY-TEST0001",
        approved_at=datetime(2026, 9, 3, 8, 30, tzinfo=UTC),
        total_amount=Decimal("1250.00"),
    )
    receipt = SimpleNamespace(receipt_no="RCT-TEST0001")
    allocation = SimpleNamespace(
        contribution_year=2026,
        contribution_month=9,
        amount=Decimal("1250.00"),
    )
    member = SimpleNamespace(display_name="BNC Member")

    content = service._build_pdf(
        organization_name="Bamarrrah Naujawan Committee",
        receipt=receipt,
        payment=payment,
        submitter_name="BNC Member",
        allocations=[(allocation, member)],
    )

    assert content.startswith(b"%PDF-")
    assert len(content) > 1500
