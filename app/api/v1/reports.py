from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.constants.permissions import PAYMENT_EXPORT
from app.db.session import get_db
from app.handlers.reports import ReportHandler
from app.models.enums import PaymentStatus
from app.models.identity import User
from app.schemas.reports import (
    ExpenseReportPage,
    FundReportPage,
    PaymentReportPage,
    ReportSummaryOutput,
)

router = APIRouter(prefix="/reports", tags=["reports"])
handler = ReportHandler()


@router.get("/summary", response_model=ReportSummaryOutput)
def report_summary(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_status: PaymentStatus | None = Query(default=None, alias="status"),
    member_id: UUID | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
    category: str | None = Query(default=None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PAYMENT_EXPORT)),
) -> ReportSummaryOutput:
    return handler.summary(
        db,
        date_from=date_from,
        date_to=date_to,
        payment_status=payment_status,
        member_id=member_id,
        group_id=group_id,
        category=category,
    )


@router.get("/payments", response_model=PaymentReportPage)
def payment_report_rows(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_status: PaymentStatus | None = Query(default=None, alias="status"),
    member_id: UUID | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PAYMENT_EXPORT)),
) -> PaymentReportPage:
    return handler.payment_page(
        db,
        date_from=date_from,
        date_to=date_to,
        payment_status=payment_status,
        member_id=member_id,
        group_id=group_id,
        offset=offset,
        limit=limit,
    )


@router.get("/expenses", response_model=ExpenseReportPage)
def expense_report_rows(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    category: str | None = Query(default=None, min_length=1, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PAYMENT_EXPORT)),
) -> ExpenseReportPage:
    return handler.expense_page(
        db,
        date_from=date_from,
        date_to=date_to,
        category=category,
        offset=offset,
        limit=limit,
    )


@router.get("/fund", response_model=FundReportPage)
def fund_report_rows(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PAYMENT_EXPORT)),
) -> FundReportPage:
    return handler.fund_page(
        db,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.get("/{dataset}/export.csv")
def export_report(
    dataset: Literal["payments", "expenses", "fund"],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    payment_status: PaymentStatus | None = Query(default=None, alias="status"),
    member_id: UUID | None = Query(default=None),
    group_id: UUID | None = Query(default=None),
    category: str | None = Query(default=None, min_length=1, max_length=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(PAYMENT_EXPORT)),
) -> Response:
    content = handler.export_csv(
        db,
        dataset=dataset,
        date_from=date_from,
        date_to=date_to,
        payment_status=payment_status,
        member_id=member_id,
        group_id=group_id,
        category=category,
    )
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{dataset}-report.csv"'},
    )
