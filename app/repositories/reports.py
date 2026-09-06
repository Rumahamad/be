from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models.enums import LedgerDirection, PaymentStatus
from app.models.expenses import Expense
from app.models.fund import FundAccount, FundEntry
from app.models.identity import User, UserGroup
from app.models.payments import Payment, PaymentAllocation


def _datetime_bounds(
    date_from: date | None, date_to: date | None
) -> tuple[datetime | None, datetime | None]:
    start = datetime.combine(date_from, time.min, tzinfo=UTC) if date_from else None
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        if date_to
        else None
    )
    return start, end


class ReportRepository:
    @staticmethod
    def _payment_filters(
        *,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
    ) -> list[Any]:
        start, end = _datetime_bounds(date_from, date_to)
        filters: list[Any] = []
        if start:
            filters.append(Payment.submitted_at >= start)
        if end:
            filters.append(Payment.submitted_at < end)
        if payment_status:
            filters.append(Payment.status == payment_status)
        if member_id:
            filters.append(
                exists(
                    select(PaymentAllocation.id).where(
                        PaymentAllocation.payment_id == Payment.id,
                        PaymentAllocation.member_id == member_id,
                    )
                )
            )
        if group_id:
            filters.append(
                exists(
                    select(PaymentAllocation.id)
                    .join(UserGroup, UserGroup.user_id == PaymentAllocation.member_id)
                    .where(
                        PaymentAllocation.payment_id == Payment.id,
                        UserGroup.group_id == group_id,
                    )
                )
            )
        return filters

    @staticmethod
    def _expense_filters(
        *, date_from: date | None, date_to: date | None, category: str | None
    ) -> list[Any]:
        filters: list[Any] = []
        if date_from:
            filters.append(Expense.expense_date >= date_from)
        if date_to:
            filters.append(Expense.expense_date <= date_to)
        if category:
            filters.append(Expense.category == category)
        return filters

    @staticmethod
    def _fund_filters(*, date_from: date | None, date_to: date | None) -> list[Any]:
        filters: list[Any] = []
        if date_from:
            filters.append(FundEntry.entry_date >= date_from)
        if date_to:
            filters.append(FundEntry.entry_date <= date_to)
        return filters

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
    ) -> tuple[Any, Any, Any]:
        payment_filters = self._payment_filters(
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
        )
        payment_row = db.execute(
            select(
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.total_amount), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (Payment.status == PaymentStatus.APPROVED, Payment.total_amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                Payment.status == PaymentStatus.PENDING_VERIFICATION,
                                Payment.total_amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (Payment.status == PaymentStatus.REJECTED, Payment.total_amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (Payment.status == PaymentStatus.REVERSED, Payment.total_amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(*payment_filters)
        ).one()

        expense_filters = self._expense_filters(
            date_from=date_from, date_to=date_to, category=category
        )
        expense_row = db.execute(
            select(
                func.count(Expense.id),
                func.coalesce(func.sum(Expense.amount), 0),
                func.coalesce(
                    func.sum(case((Expense.status == "POSTED", Expense.amount), else_=0)), 0
                ),
                func.coalesce(
                    func.sum(case((Expense.status == "REVERSED", Expense.amount), else_=0)), 0
                ),
            ).where(*expense_filters)
        ).one()

        fund_filters = self._fund_filters(date_from=date_from, date_to=date_to)
        fund_row = db.execute(
            select(
                func.count(FundEntry.id),
                func.coalesce(
                    func.sum(
                        case(
                            (FundEntry.direction == LedgerDirection.CREDIT, FundEntry.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (FundEntry.direction == LedgerDirection.DEBIT, FundEntry.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(*fund_filters)
        ).one()
        return payment_row, expense_row, fund_row

    def _payment_rows_statement(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
    ) -> Select:
        submitter = aliased(User)
        member = aliased(User)
        filters = self._payment_filters(
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
        )
        if member_id:
            filters.append(PaymentAllocation.member_id == member_id)
        if group_id:
            filters.append(
                exists(
                    select(UserGroup.id).where(
                        UserGroup.user_id == PaymentAllocation.member_id,
                        UserGroup.group_id == group_id,
                    )
                )
            )
        statement: Select = (
            select(
                Payment.id.label("payment_id"),
                PaymentAllocation.id.label("allocation_id"),
                Payment.payment_no,
                Payment.status,
                Payment.total_amount,
                Payment.current_revision,
                Payment.submitted_at,
                Payment.approved_at,
                submitter.member_code.label("submitted_by_code"),
                submitter.display_name.label("submitted_by_name"),
                member.member_code.label("member_code"),
                member.display_name.label("member_name"),
                PaymentAllocation.contribution_year,
                PaymentAllocation.contribution_month,
                PaymentAllocation.amount.label("allocation_amount"),
                Payment.user_note,
            )
            .join(submitter, submitter.id == Payment.submitted_by)
            .join(PaymentAllocation, PaymentAllocation.payment_id == Payment.id)
            .join(member, member.id == PaymentAllocation.member_id)
            .where(*filters)
            .order_by(
                Payment.submitted_at.desc(),
                Payment.payment_no,
                PaymentAllocation.contribution_year,
                PaymentAllocation.contribution_month,
                member.display_name,
            )
        )
        return statement

    def payment_export(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        payment_status: PaymentStatus | None,
        member_id: UUID | None,
        group_id: UUID | None,
    ) -> list[Any]:
        statement = self._payment_rows_statement(
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
        )
        return list(db.execute(statement).all())

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
    ) -> tuple[list[Any], int]:
        filters = self._payment_filters(
            date_from=date_from,
            date_to=date_to,
            payment_status=payment_status,
            member_id=member_id,
            group_id=group_id,
        )
        total = db.scalar(select(func.count(Payment.id)).where(*filters)) or 0
        payment_ids = list(
            db.scalars(
                select(Payment.id)
                .where(*filters)
                .order_by(Payment.submitted_at.desc(), Payment.payment_no)
                .offset(offset)
                .limit(limit)
            ).all()
        )
        if not payment_ids:
            return [], int(total)
        statement = self._payment_rows_statement(
            date_from=None,
            date_to=None,
            payment_status=None,
            member_id=None,
            group_id=None,
        ).where(Payment.id.in_(payment_ids))
        rows = db.execute(statement).all()
        return list(rows), int(total)

    def _expense_rows_statement(
        self,
        *,
        date_from: date | None,
        date_to: date | None,
        category: str | None,
    ) -> Select:
        responsible = aliased(User)
        creator = aliased(User)
        statement = (
            select(
                Expense.id.label("expense_id"),
                Expense.expense_date,
                Expense.status,
                Expense.category,
                Expense.amount,
                Expense.description,
                Expense.payee,
                responsible.member_code.label("responsible_member_code"),
                responsible.display_name.label("responsible_member_name"),
                Expense.payment_method,
                Expense.reference_no,
                Expense.internal_note,
                FundAccount.code.label("fund_account_code"),
                creator.display_name.label("created_by_name"),
                Expense.created_at,
            )
            .join(FundAccount, FundAccount.id == Expense.fund_account_id)
            .join(creator, creator.id == Expense.created_by)
            .outerjoin(responsible, responsible.id == Expense.responsible_member_id)
            .where(
                *self._expense_filters(
                    date_from=date_from, date_to=date_to, category=category
                )
            )
            .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        )
        return statement

    def expense_export(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        category: str | None,
    ) -> list[Any]:
        statement = self._expense_rows_statement(
            date_from=date_from, date_to=date_to, category=category
        )
        return list(db.execute(statement).all())

    def expense_page(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        category: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Any], int]:
        statement = self._expense_rows_statement(
            date_from=date_from, date_to=date_to, category=category
        )
        total = db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        rows = db.execute(statement.offset(offset).limit(limit)).all()
        return list(rows), int(total)

    def _fund_rows_statement(
        self, *, date_from: date | None, date_to: date | None
    ) -> Select:
        creator = aliased(User)
        statement = (
            select(
                FundEntry.id.label("entry_id"),
                FundEntry.entry_no,
                FundEntry.entry_date,
                FundEntry.direction,
                FundEntry.entry_type,
                FundEntry.amount,
                FundEntry.reference_type,
                FundEntry.reference_id,
                FundEntry.description,
                FundEntry.reversal_of_id,
                FundAccount.code.label("fund_account_code"),
                creator.display_name.label("created_by_name"),
                FundEntry.created_at,
            )
            .join(FundAccount, FundAccount.id == FundEntry.fund_account_id)
            .join(creator, creator.id == FundEntry.created_by)
            .where(*self._fund_filters(date_from=date_from, date_to=date_to))
            .order_by(FundEntry.entry_date.desc(), FundEntry.created_at.desc())
        )
        return statement

    def fund_export(
        self, db: Session, *, date_from: date | None, date_to: date | None
    ) -> list[Any]:
        return list(
            db.execute(
                self._fund_rows_statement(date_from=date_from, date_to=date_to)
            ).all()
        )

    def fund_page(
        self,
        db: Session,
        *,
        date_from: date | None,
        date_to: date | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Any], int]:
        statement = self._fund_rows_statement(date_from=date_from, date_to=date_to)
        total = db.scalar(
            select(func.count()).select_from(statement.order_by(None).subquery())
        ) or 0
        rows = db.execute(statement.offset(offset).limit(limit)).all()
        return list(rows), int(total)
