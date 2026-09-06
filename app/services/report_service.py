import csv
import io
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus
from app.repositories.reports import ReportRepository
from app.schemas.reports import (
    ExpenseReportPage,
    ExpenseReportRow,
    ExpenseReportSummary,
    FundReportPage,
    FundReportRow,
    FundReportSummary,
    PaymentReportAllocation,
    PaymentReportPage,
    PaymentReportRow,
    PaymentReportSummary,
    ReportSummaryOutput,
)

ReportDataset = Literal["payments", "expenses", "fund"]


class ReportService:
    def __init__(self, repository: ReportRepository | None = None) -> None:
        self.repository = repository or ReportRepository()

    def summary(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
        category: str | None,
    ) -> ReportSummaryOutput:
        payment, expense, fund = self.repository.summary(
            db,
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
            category=category,
        )
        credits = Decimal(fund[1])
        debits = Decimal(fund[2])
        return ReportSummaryOutput(
            date_from=date_from,
            date_to=date_to,
            payments=PaymentReportSummary(
                count=payment[0],
                total_amount=payment[1],
                approved_amount=payment[2],
                pending_amount=payment[3],
                rejected_amount=payment[4],
                reversed_amount=payment[5],
            ),
            expenses=ExpenseReportSummary(
                count=expense[0],
                total_amount=expense[1],
                posted_amount=expense[2],
                reversed_amount=expense[3],
            ),
            fund=FundReportSummary(
                entry_count=fund[0],
                total_credits=credits,
                total_debits=debits,
                balance=credits - debits,
            ),
        )

    def payment_page(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
        offset: int,
        limit: int,
    ) -> PaymentReportPage:
        rows, total = self.repository.payment_page(
            db,
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
            offset=offset,
            limit=limit,
        )
        grouped: dict[UUID, dict[str, Any]] = {}
        for row in rows:
            values = row._mapping
            payment_id = values["payment_id"]
            item = grouped.setdefault(
                payment_id,
                {
                    "payment_id": payment_id,
                    "payment_no": values["payment_no"],
                    "status": values["status"],
                    "total_amount": values["total_amount"],
                    "current_revision": values["current_revision"],
                    "submitted_at": values["submitted_at"],
                    "approved_at": values["approved_at"],
                    "submitted_by_code": values["submitted_by_code"],
                    "submitted_by_name": values["submitted_by_name"],
                    "user_note": values["user_note"],
                    "allocations": [],
                },
            )
            item["allocations"].append(
                PaymentReportAllocation(
                    allocation_id=values["allocation_id"],
                    member_code=values["member_code"],
                    member_name=values["member_name"],
                    contribution_year=values["contribution_year"],
                    contribution_month=values["contribution_month"],
                    allocation_amount=values["allocation_amount"],
                )
            )
        return PaymentReportPage(
            items=[PaymentReportRow.model_validate(item) for item in grouped.values()],
            total=total,
            offset=offset,
            limit=limit,
        )

    def expense_page(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        category: str | None,
        offset: int,
        limit: int,
    ) -> ExpenseReportPage:
        rows, total = self.repository.expense_page(
            db,
            date_from=date_from,
            date_to=date_to,
            category=category,
            offset=offset,
            limit=limit,
        )
        return ExpenseReportPage(
            items=[ExpenseReportRow.model_validate(row._mapping) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    def fund_page(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> FundReportPage:
        rows, total = self.repository.fund_page(
            db,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
        return FundReportPage(
            items=[FundReportRow.model_validate(row._mapping) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    def export_csv(
        self,
        db: Session,
        *,
        dataset: ReportDataset,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
        category: str | None,
    ) -> bytes:
        if dataset == "payments":
            headers = [
                "payment_id",
                "allocation_id",
                "payment_no",
                "status",
                "total_amount",
                "current_revision",
                "submitted_at",
                "approved_at",
                "submitted_by_code",
                "submitted_by_name",
                "member_code",
                "member_name",
                "contribution_year",
                "contribution_month",
                "allocation_amount",
                "user_note",
            ]
            rows = self.repository.payment_export(
                db,
                date_from=date_from,
                date_to=date_to,
                payment_status=payment_status,
                member_id=member_id,
                group_id=group_id,
            )
        elif dataset == "expenses":
            headers = [
                "expense_id",
                "expense_date",
                "status",
                "category",
                "amount",
                "description",
                "payee",
                "responsible_member_code",
                "responsible_member_name",
                "payment_method",
                "reference_no",
                "internal_note",
                "fund_account_code",
                "created_by_name",
                "created_at",
            ]
            rows = self.repository.expense_export(
                db, date_from=date_from, date_to=date_to, category=category
            )
        else:
            headers = [
                "entry_id",
                "entry_no",
                "entry_date",
                "direction",
                "entry_type",
                "amount",
                "reference_type",
                "reference_id",
                "description",
                "reversal_of_id",
                "fund_account_code",
                "created_by_name",
                "created_at",
            ]
            rows = self.repository.fund_export(db, date_from=date_from, date_to=date_to)

        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows([self._csv_value(value) for value in row] for row in rows)
        return stream.getvalue().encode("utf-8-sig")

    @staticmethod
    def _csv_value(value: Any) -> str | int | Decimal:
        if value is None:
            return ""
        if isinstance(value, Enum):
            return str(value.value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return value
        rendered = str(value)
        if rendered.startswith(("=", "+", "-", "@")):
            return f"'{rendered}"
        return rendered
