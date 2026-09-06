from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.payment_numbers import ledger_entry_no
from app.models.enums import LedgerDirection
from app.models.expense_reversals import ExpenseReversal
from app.models.expenses import Expense
from app.models.fund import FundAccount, FundEntry
from app.models.identity import User
from app.schemas.expenses import CreateExpenseInput
from app.services.audit_service import AuditService


class ExpenseService:
    def __init__(self) -> None:
        self.audit = AuditService()

    def create(self, db: Session, actor: User, payload: CreateExpenseInput) -> Expense:
        account = db.scalar(
            select(FundAccount).where(
                FundAccount.is_default.is_(True), FundAccount.is_active.is_(True)
            ).with_for_update()
        )
        if not account:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Default fund account is not configured",
            )
        if payload.responsible_member_id:
            responsible = db.get(User, payload.responsible_member_id)
            if not responsible:
                raise HTTPException(status_code=422, detail="Responsible member not found")
        category_name = payload.category.strip() if payload.category else None
        if payload.category_id:
            from app.models.expenses import ExpenseCategory

            category = db.get(ExpenseCategory, payload.category_id)
            if not category:
                raise HTTPException(status_code=422, detail="Expense category not found")
            if not category.is_active:
                raise HTTPException(status_code=409, detail="Expense category is inactive")
            category_name = category.name
        if not category_name:
            raise HTTPException(status_code=422, detail="Expense category is required")
        expense = Expense(
            fund_account_id=account.id,
            expense_category_id=payload.category_id,
            amount=payload.amount,
            category=category_name,
            description=payload.description.strip() if payload.description else None,
            payee=payload.payee.strip() if payload.payee else None,
            responsible_member_id=payload.responsible_member_id,
            payment_method=payload.payment_method.strip() if payload.payment_method else None,
            reference_no=payload.reference_no.strip() if payload.reference_no else None,
            internal_note=payload.internal_note.strip() if payload.internal_note else None,
            status="POSTED",
            expense_date=payload.expense_date or datetime.now(UTC).date(),
            created_by=actor.id,
        )
        db.add(expense)
        db.flush()
        entry = FundEntry(
            entry_no=ledger_entry_no(),
            fund_account_id=account.id,
            entry_date=expense.expense_date,
            direction=LedgerDirection.DEBIT,
            entry_type="EXPENSE",
            amount=expense.amount,
            reference_type="EXPENSE",
            reference_id=expense.id,
            description=f"Expense: {expense.category}",
            created_by=actor.id,
        )
        db.add(entry)
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="expense.created",
            entity_type="expense",
            entity_id=expense.id,
            after_data={"amount": str(expense.amount), "category": expense.category},
        )
        return expense

    def reverse(
        self, db: Session, actor: User, expense_id, reason: str
    ) -> Expense:
        expense = db.scalar(
            select(Expense).where(Expense.id == expense_id).with_for_update()
        )
        if not expense:
            raise HTTPException(status_code=404, detail="Expense not found")
        if expense.status != "POSTED":
            raise HTTPException(status_code=409, detail="Expense has already been reversed")
        original = db.scalar(
            select(FundEntry)
            .where(
                FundEntry.reference_type == "EXPENSE",
                FundEntry.reference_id == expense.id,
                FundEntry.direction == LedgerDirection.DEBIT,
                FundEntry.reversal_of_id.is_(None),
            )
            .with_for_update()
        )
        if not original:
            raise HTTPException(status_code=409, detail="Original expense debit was not found")
        reversal = FundEntry(
            entry_no=ledger_entry_no(),
            fund_account_id=original.fund_account_id,
            entry_date=datetime.now(UTC).date(),
            direction=LedgerDirection.CREDIT,
            entry_type="REVERSAL",
            amount=original.amount,
            reference_type="EXPENSE_REVERSAL",
            reference_id=expense.id,
            description=f"Reversal of {original.entry_no}: {reason}",
            reversal_of_id=original.id,
            created_by=actor.id,
        )
        db.add(reversal)
        db.flush()
        db.add(
            ExpenseReversal(
                expense_id=expense.id,
                original_fund_entry_id=original.id,
                reversal_fund_entry_id=reversal.id,
                reason=reason,
                reversed_by=actor.id,
            )
        )
        expense.status = "REVERSED"
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="expense.reversed",
            entity_type="expense",
            entity_id=expense.id,
            after_data={"reason": reason, "reversal_entry": reversal.entry_no},
        )
        return expense

    def list(
        self,
        db: Session,
        *,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Expense, str, str | None]], int]:
        responsible = User.__table__.alias("responsible_member")
        query = select(Expense, FundEntry.entry_no, responsible.c.display_name).join(
            FundEntry,
            (FundEntry.reference_id == Expense.id)
            & (FundEntry.reference_type == "EXPENSE"),
        ).outerjoin(responsible, responsible.c.id == Expense.responsible_member_id)
        total = db.scalar(select(func.count(Expense.id))) or 0
        rows = db.execute(
            query.order_by(Expense.expense_date.desc(), Expense.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), int(total)
