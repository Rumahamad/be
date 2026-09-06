from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import PaymentStatus
from app.schemas.reports import (
    ExpenseReportPage,
    FundReportPage,
    PaymentReportPage,
    ReportSummaryOutput,
)
from app.services.report_service import ReportService

ReportDataset = Literal["payments", "expenses", "fund"]


class ReportHandler:
    def __init__(self, service: ReportService | None = None) -> None:
        self.service = service or ReportService()

    @staticmethod
    def validate_period(date_from: date | None, date_to: date | None) -> None:
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="date_from must be on or before date_to")

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
        self.validate_period(date_from, date_to)
        return self.service.summary(
            db,
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
            category=category,
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
        self.validate_period(date_from, date_to)
        return self.service.export_csv(
            db,
            dataset=dataset,
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
            category=category,
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
        self.validate_period(date_from, date_to)
        return self.service.payment_page(
            db,
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
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
        self.validate_period(date_from, date_to)
        return self.service.expense_page(
            db,
            date_from=date_from,
            date_to=date_to,
            category=category,
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
        self.validate_period(date_from, date_to)
        return self.service.fund_page(
            db,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )
