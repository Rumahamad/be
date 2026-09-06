from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines.payment_numbers import receipt_no
from app.models.communications import Receipt
from app.models.enums import PaymentStatus
from app.models.identity import User
from app.models.payments import Payment, PaymentAllocation
from app.models.settings import OrganizationSetting


class ReceiptService:
    def create_for_payment(self, db: Session, payment: Payment) -> Receipt:
        existing = db.scalar(select(Receipt).where(Receipt.payment_id == payment.id))
        if existing:
            return existing
        receipt = Receipt(
            receipt_no=receipt_no(),
            payment_id=payment.id,
            language="en",
            status="PENDING_GENERATION",
        )
        db.add(receipt)
        db.flush()
        return receipt

    def render(self, db: Session, payment_id: UUID) -> tuple[bytes, Receipt]:
        payment = db.get(Payment, payment_id)
        if not payment or payment.status != PaymentStatus.APPROVED:
            raise HTTPException(status_code=404, detail="Approved receipt not found")
        receipt = db.scalar(select(Receipt).where(Receipt.payment_id == payment.id))
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt metadata not found")
        submitter = db.get(User, payment.submitted_by)
        organization = db.scalar(select(OrganizationSetting).limit(1))
        allocations = db.execute(
            select(PaymentAllocation, User)
            .join(User, User.id == PaymentAllocation.member_id)
            .where(PaymentAllocation.payment_id == payment.id)
            .order_by(
                PaymentAllocation.contribution_year,
                PaymentAllocation.contribution_month,
                User.display_name,
            )
        ).all()
        content = self._build_pdf(
            organization_name=(
                organization.organization_name
                if organization
                else "Bamarrrah Naujawan Committee"
            ),
            receipt=receipt,
            payment=payment,
            submitter_name=submitter.display_name if submitter else "BNC member",
            allocations=list(allocations),
        )
        receipt.status = "GENERATED"
        receipt.generated_at = datetime.now(UTC)
        return content, receipt

    @staticmethod
    def _amount(value: Decimal) -> str:
        return f"INR {value:,.2f}"

    def _build_pdf(
        self,
        *,
        organization_name: str,
        receipt: Receipt,
        payment: Payment,
        submitter_name: str,
        allocations: list[tuple[PaymentAllocation, User]],
    ) -> bytes:
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title=f"BNC receipt {receipt.receipt_no}",
            author=organization_name,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "BncTitle",
            parent=styles["Title"],
            textColor=HexColor("#0D4D45"),
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            alignment=TA_CENTER,
            spaceAfter=4 * mm,
        )
        subtitle_style = ParagraphStyle(
            "BncSubtitle",
            parent=styles["Heading2"],
            textColor=HexColor("#8C7442"),
            alignment=TA_CENTER,
            fontSize=12,
            leading=15,
            spaceAfter=8 * mm,
        )
        body_style = ParagraphStyle(
            "BncBody", parent=styles["BodyText"], fontSize=10, leading=15
        )
        story = [
            Paragraph(organization_name, title_style),
            Paragraph("Contribution Receipt", subtitle_style),
        ]
        metadata = [
            ["Receipt number", receipt.receipt_no, "Payment number", payment.payment_no],
            [
                "Approved on",
                payment.approved_at.strftime("%d %b %Y, %I:%M %p")
                if payment.approved_at
                else "-",
                "Submitted by",
                submitter_name,
            ],
        ]
        meta_table = Table(metadata, colWidths=[28 * mm, 51 * mm, 29 * mm, 52 * mm])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F3F7F4")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), HexColor("#183E37")),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#DCE5E0")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, HexColor("#DCE5E0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.extend([meta_table, Spacer(1, 8 * mm)])
        rows = [["Member", "Contribution month", "Amount"]]
        rows.extend(
            [
                member.display_name,
                f"{allocation.contribution_year}-{allocation.contribution_month:02d}",
                self._amount(allocation.amount),
            ]
            for allocation, member in allocations
        )
        rows.append(["", "Total", self._amount(payment.total_amount)])
        allocation_table = Table(rows, colWidths=[70 * mm, 48 * mm, 42 * mm], repeatRows=1)
        allocation_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), HexColor("#0D4D45")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (1, -1), (-1, -1), "Helvetica-Bold"),
                    ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.35, HexColor("#CFDAD5")),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("BACKGROUND", (0, -1), (-1, -1), HexColor("#F7F2E7")),
                ]
            )
        )
        story.extend(
            [
                allocation_table,
                Spacer(1, 12 * mm),
                Paragraph(
                    "Thank you for your contribution and continued support of BNC's community work.",
                    body_style,
                ),
                Spacer(1, 4 * mm),
                Paragraph(
                    "This is a system-generated receipt. No signature is required.", body_style
                ),
            ]
        )
        document.build(story)
        return buffer.getvalue()
