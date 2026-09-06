from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.engines.payment_numbers import ledger_entry_no
from app.models.enums import LedgerDirection
from app.models.fund import FundAccount, FundEntry
from app.models.identity import User
from app.schemas.fund import (
    CreateFundAdjustmentInput,
    FundEntryListOutput,
    FundEntryOutput,
    FundSummaryOutput,
)
from app.services.audit_service import AuditService


class FundService:
    def __init__(self) -> None:
        self.audit = AuditService()

    def summary(self, db: Session) -> FundSummaryOutput:
        account = db.scalar(
            select(FundAccount).where(
                FundAccount.is_default.is_(True), FundAccount.is_active.is_(True)
            )
        )
        if not account:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Default fund account is not configured",
            )

        credits = db.scalar(
            select(func.coalesce(func.sum(FundEntry.amount), 0)).where(
                FundEntry.fund_account_id == account.id,
                FundEntry.direction == LedgerDirection.CREDIT,
            )
        ) or Decimal(0)
        debits = db.scalar(
            select(func.coalesce(func.sum(FundEntry.amount), 0)).where(
                FundEntry.fund_account_id == account.id,
                FundEntry.direction == LedgerDirection.DEBIT,
            )
        ) or Decimal(0)
        entry_count = db.scalar(
            select(func.count(FundEntry.id)).where(FundEntry.fund_account_id == account.id)
        ) or 0
        return FundSummaryOutput(
            account_id=account.id,
            account_name=account.name,
            account_code=account.code,
            balance=credits - debits,
            total_credits=credits,
            total_debits=debits,
            entry_count=int(entry_count),
        )

    def entries(self, db: Session, *, offset: int, limit: int) -> FundEntryListOutput:
        total = int(db.scalar(select(func.count(FundEntry.id))) or 0)
        entries = db.scalars(
            select(FundEntry)
            .order_by(FundEntry.entry_date.desc(), FundEntry.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return FundEntryListOutput(
            items=[
                FundEntryOutput(
                    id=entry.id,
                    entry_no=entry.entry_no,
                    entry_date=entry.entry_date,
                    direction=entry.direction.value,
                    entry_type=entry.entry_type,
                    amount=entry.amount,
                    reference_type=entry.reference_type,
                    reference_id=entry.reference_id,
                    description=entry.description,
                    reversal_of_id=entry.reversal_of_id,
                    created_by=entry.created_by,
                    created_at=entry.created_at,
                )
                for entry in entries
            ],
            total=total,
        )

    def create_adjustment(
        self, db: Session, actor: User, payload: CreateFundAdjustmentInput
    ) -> FundEntry:
        account = db.scalar(
            select(FundAccount)
            .where(FundAccount.is_default.is_(True), FundAccount.is_active.is_(True))
            .with_for_update()
        )
        if not account:
            raise HTTPException(status_code=409, detail="Default fund account is unavailable")
        entry = FundEntry(
            entry_no=ledger_entry_no(),
            fund_account_id=account.id,
            entry_date=payload.entry_date or datetime.now(UTC).date(),
            direction=LedgerDirection(payload.direction),
            entry_type="MANUAL_ADJUSTMENT",
            amount=payload.amount,
            reference_type="MANUAL_ADJUSTMENT",
            reference_id=uuid4(),
            description=payload.description.strip(),
            created_by=actor.id,
        )
        db.add(entry)
        db.flush()
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="fund.adjusted",
            entity_type="fund_entry",
            entity_id=entry.id,
            after_data={
                "direction": entry.direction.value,
                "amount": str(entry.amount),
                "description": entry.description,
            },
        )
        return entry

    def reverse_adjustment(
        self, db: Session, actor: User, entry_id: UUID, reason: str
    ) -> FundEntry:
        original = db.scalar(
            select(FundEntry).where(FundEntry.id == entry_id).with_for_update()
        )
        if not original:
            raise HTTPException(status_code=404, detail="Fund entry not found")
        if original.entry_type != "MANUAL_ADJUSTMENT":
            raise HTTPException(
                status_code=409,
                detail="Use the payment or expense reversal workflow for this entry",
            )
        existing = db.scalar(
            select(FundEntry.id).where(FundEntry.reversal_of_id == original.id)
        )
        if existing:
            raise HTTPException(status_code=409, detail="Fund entry is already reversed")
        direction = (
            LedgerDirection.DEBIT
            if original.direction == LedgerDirection.CREDIT
            else LedgerDirection.CREDIT
        )
        reversal = FundEntry(
            entry_no=ledger_entry_no(),
            fund_account_id=original.fund_account_id,
            entry_date=datetime.now(UTC).date(),
            direction=direction,
            entry_type="REVERSAL",
            amount=original.amount,
            reference_type="MANUAL_ADJUSTMENT_REVERSAL",
            reference_id=original.reference_id,
            description=f"Reversal of {original.entry_no}: {reason}",
            reversal_of_id=original.id,
            created_by=actor.id,
        )
        db.add(reversal)
        db.flush()
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="fund.adjustment_reversed",
            entity_type="fund_entry",
            entity_id=reversal.id,
            after_data={"original_entry_id": str(original.id), "reason": reason},
        )
        return reversal

    @staticmethod
    def output(entry: FundEntry) -> FundEntryOutput:
        return FundEntryOutput(
            id=entry.id,
            entry_no=entry.entry_no,
            entry_date=entry.entry_date,
            direction=entry.direction.value,
            entry_type=entry.entry_type,
            amount=entry.amount,
            reference_type=entry.reference_type,
            reference_id=entry.reference_id,
            description=entry.description,
            reversal_of_id=entry.reversal_of_id,
            created_by=entry.created_by,
            created_at=entry.created_at,
        )
