from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.models.communications import Receipt
from app.models.core import MemberMonthContribution, Payment
from app.models.enums import ContributionStatus
from app.models.identity import User
from app.models.payments import (
    PaymentAllocation,
    PaymentAllocationRevision,
    PaymentReview,
    PaymentRevision,
)
from app.models.reversals import PaymentReversal


class PaymentRepository:
    def get_for_update(self, db: Session, payment_id: UUID) -> Payment | None:
        return db.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())

    def conflicting_contributions(
        self, db: Session, allocations: list[MemberMonthContribution]
    ) -> bool:
        if not allocations:
            return False
        keys = [(item.member_id, item.year, item.month) for item in allocations]
        existing = db.scalar(
            select(MemberMonthContribution.id)
            .where(
                tuple_(
                    MemberMonthContribution.member_id,
                    MemberMonthContribution.year,
                    MemberMonthContribution.month,
                ).in_(keys),
                MemberMonthContribution.status.in_(
                    (ContributionStatus.PENDING, ContributionStatus.APPROVED)
                ),
            )
            .limit(1)
        )
        return existing is not None

    def contribution_states(
        self,
        db: Session,
        *,
        member_ids: list[UUID],
        year_from: int,
        year_to: int,
    ) -> list[MemberMonthContribution]:
        return list(
            db.scalars(
                select(MemberMonthContribution)
                .where(
                    MemberMonthContribution.member_id.in_(member_ids),
                    MemberMonthContribution.year.between(year_from, year_to),
                )
                .order_by(MemberMonthContribution.created_at.desc())
            ).all()
        )

    def list_with_submitter(
        self,
        db: Session,
        *,
        submitted_by: UUID | None,
        payment_status: object | None,
        offset: int,
        limit: int,
    ) -> tuple[list[tuple[Payment, User]], int]:
        filters = []
        if submitted_by:
            filters.append(Payment.submitted_by == submitted_by)
        if payment_status:
            filters.append(Payment.status == payment_status)
        query = select(Payment, User).join(User, User.id == Payment.submitted_by).where(*filters)
        total = db.scalar(select(func.count(Payment.id)).where(*filters)) or 0
        rows = db.execute(
            query.order_by(Payment.submitted_at.desc(), Payment.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return rows, int(total)

    def get_with_submitter(
        self, db: Session, payment_id: UUID
    ) -> tuple[Payment, User] | None:
        return db.execute(
            select(Payment, User)
            .join(User, User.id == Payment.submitted_by)
            .where(Payment.id == payment_id)
        ).one_or_none()

    def allocations_with_members(
        self, db: Session, payment_id: UUID
    ) -> list[tuple[PaymentAllocation, User]]:
        return list(
            db.execute(
                select(PaymentAllocation, User)
                .join(User, User.id == PaymentAllocation.member_id)
                .where(PaymentAllocation.payment_id == payment_id)
                .order_by(
                    PaymentAllocation.contribution_year,
                    PaymentAllocation.contribution_month,
                    User.display_name,
                )
            ).all()
        )

    def reviews_with_reviewers(
        self, db: Session, payment_id: UUID
    ) -> list[tuple[PaymentReview, User]]:
        return list(
            db.execute(
                select(PaymentReview, User)
                .join(User, User.id == PaymentReview.reviewed_by)
                .where(PaymentReview.payment_id == payment_id)
                .order_by(PaymentReview.created_at)
            ).all()
        )

    def revisions_with_allocations(
        self, db: Session, payment_id: UUID
    ) -> list[tuple[PaymentRevision, list[PaymentAllocationRevision]]]:
        revisions = list(
            db.scalars(
                select(PaymentRevision)
                .where(PaymentRevision.payment_id == payment_id)
                .order_by(PaymentRevision.revision_no)
            ).all()
        )
        if not revisions:
            return []
        revision_ids = [revision.id for revision in revisions]
        allocations = db.scalars(
            select(PaymentAllocationRevision)
            .where(PaymentAllocationRevision.payment_revision_id.in_(revision_ids))
            .order_by(
                PaymentAllocationRevision.year,
                PaymentAllocationRevision.month,
                PaymentAllocationRevision.member_id,
            )
        ).all()
        by_revision: dict[UUID, list[PaymentAllocationRevision]] = {
            revision_id: [] for revision_id in revision_ids
        }
        for allocation in allocations:
            by_revision[allocation.payment_revision_id].append(allocation)
        return [(revision, by_revision[revision.id]) for revision in revisions]

    def receipt(self, db: Session, payment_id: UUID) -> Receipt | None:
        return db.scalar(select(Receipt).where(Receipt.payment_id == payment_id))

    def reversal(
        self, db: Session, payment_id: UUID
    ) -> tuple[PaymentReversal, User, str] | None:
        from app.models.fund import FundEntry

        return db.execute(
            select(PaymentReversal, User, FundEntry.entry_no)
            .join(User, User.id == PaymentReversal.reversed_by)
            .join(FundEntry, FundEntry.id == PaymentReversal.reversal_fund_entry_id)
            .where(PaymentReversal.payment_id == payment_id)
        ).one_or_none()
