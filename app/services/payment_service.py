from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.constants.permissions import PAYMENT_APPROVE
from app.engines.payment_numbers import ledger_entry_no, payment_no
from app.models.communications import NotificationOutbox
from app.models.enums import (
    ContributionStatus,
    LedgerDirection,
    PaymentStatus,
    ReviewAction,
    UserStatus,
)
from app.models.fund import FundAccount, FundEntry
from app.models.identity import User
from app.models.payments import (
    MemberMonthContribution,
    Payment,
    PaymentAllocation,
    PaymentAllocationRevision,
    PaymentFile,
    PaymentReview,
    PaymentRevision,
)
from app.models.reversals import PaymentReversal
from app.models.verification import PaymentVerificationEvent, PaymentProofExtraction
from app.services.payment_utr_service import claim_reference
from app.repositories.payments import PaymentRepository
from app.schemas.payments import (
    ContributionAvailabilityInput,
    ContributionMonthStateOutput,
    CreatePaymentInput,
)
from app.services.announcement_service import NotificationService
from app.services.receipt_service import ReceiptService


class PaymentService:
    def __init__(self, repository: PaymentRepository | None = None) -> None:
        self.repository = repository or PaymentRepository()
        self.notifications = NotificationService()
        self.receipts = ReceiptService()

    def submit(
        self,
        db: Session,
        actor_id: UUID,
        payload: CreatePaymentInput,
        *,
        auto_approve: bool = False,
    ) -> Payment:
        payment = Payment(
            payment_no=payment_no(),
            submitted_by=actor_id,
            created_by=actor_id,
            total_amount=self._total(payload),
            status=PaymentStatus.PENDING_VERIFICATION,
            current_revision=1,
            user_note=payload.note,
            submitted_at=datetime.now(UTC),
            verification_status="WAITING",
        )
        db.add(payment)
        db.flush()
        self._replace_allocations(db, payment, payload)
        self._record_revision(db, payment, payload)
        if auto_approve:
            self.approve(
                db,
                payment.id,
                actor_id,
                comment="Admin-created payment",
                require_proof=False,
                verification_method="ADMIN_CREATED",
            )
        return payment

    def availability(
        self, db: Session, payload: ContributionAvailabilityInput
    ) -> list[ContributionMonthStateOutput]:
        requested_ids = set(payload.member_ids)
        active_ids = set(
            db.scalars(
                select(User.id).where(
                    User.id.in_(requested_ids), User.status == UserStatus.ACTIVE
                )
            ).all()
        )
        if active_ids != requested_ids:
            raise HTTPException(status_code=400, detail="One or more selected members are unavailable")

        priority = {
            ContributionStatus.REJECTED: 1,
            ContributionStatus.PENDING: 2,
            ContributionStatus.APPROVED: 3,
        }
        selected = {}
        for item in self.repository.contribution_states(
            db,
            member_ids=list(requested_ids),
            year_from=payload.year_from,
            year_to=payload.year_to,
        ):
            key = (item.member_id, item.year, item.month)
            current = selected.get(key)
            if current is None or priority[item.status] > priority[current.status]:
                selected[key] = item
        return [
            ContributionMonthStateOutput(
                member_id=item.member_id,
                year=item.year,
                month=item.month,
                status=item.status.value,
                amount=item.amount,
                payment_id=item.payment_id,
            )
            for item in sorted(
                selected.values(), key=lambda row: (str(row.member_id), row.year, row.month)
            )
        ]

    def resubmit(
        self,
        db: Session,
        payment_id: UUID,
        actor_id: UUID,
        payload: CreatePaymentInput,
    ) -> Payment:
        payment = self.repository.get_for_update(db, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != PaymentStatus.REJECTED:
            raise HTTPException(status_code=409, detail="Only rejected payments can be resubmitted")
        if actor_id not in {payment.submitted_by, payment.created_by}:
            raise HTTPException(status_code=403, detail="Payment cannot be edited by this user")

        db.execute(
            delete(MemberMonthContribution).where(MemberMonthContribution.payment_id == payment.id)
        )
        db.execute(delete(PaymentAllocation).where(PaymentAllocation.payment_id == payment.id))
        payment.current_revision += 1
        payment.total_amount = self._total(payload)
        payment.user_note = payload.note
        payment.status = PaymentStatus.PENDING_VERIFICATION
        payment.submitted_at = datetime.now(UTC)
        payment.rejected_at = None
        payment.rejected_by = None
        payment.rejection_reason = None
        payment.verification_status = "WAITING"
        payment.verification_method = None
        payment.auto_verified_at = None
        payment.auto_verified_reference = None
        payment.verification_error_code = None
        self._replace_allocations(db, payment, payload)
        self._record_revision(db, payment, payload)
        db.add(PaymentVerificationEvent(
            payment_id=payment.id,
            event_type="RESUBMITTED_FOR_VERIFICATION",
            actor_type="USER",
            actor_user_id=actor_id,
            metadata_json={"revision": payment.current_revision},
        ))
        return payment

    def mark_ready_for_review(self, db: Session, payment_id: UUID, actor_id: UUID) -> Payment:
        payment = self.repository.get_for_update(db, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        if payment.status != PaymentStatus.PENDING_VERIFICATION:
            raise HTTPException(status_code=409, detail="Payment is not awaiting verification")
        if actor_id not in {payment.submitted_by, payment.created_by}:
            raise HTTPException(status_code=403, detail="You cannot submit this payment for review")

        proof_id = db.scalar(
            select(PaymentFile.id)
            .join(PaymentRevision, PaymentRevision.id == PaymentFile.payment_revision_id)
            .where(
                PaymentFile.payment_id == payment.id,
                PaymentRevision.revision_no == payment.current_revision,
            )
            .limit(1)
        )
        if not proof_id:
            raise HTTPException(status_code=409, detail="Upload at least one screenshot before submitting")

        already_queued = db.scalar(
            select(NotificationOutbox.id).where(
                NotificationOutbox.event_type == "PAYMENT_PENDING_VERIFICATION",
                NotificationOutbox.channel == "PUSH",
                NotificationOutbox.payload["payment_id"].as_string() == str(payment.id),
                NotificationOutbox.payload["revision"].as_integer() == payment.current_revision,
            ).limit(1)
        )
        if not already_queued:
            self._notify_reviewers(
                db,
                payment,
                "Payment awaiting verification" if payment.current_revision == 1 else "Payment resubmitted for verification",
            )
        return payment

    def approve(
        self,
        db: Session,
        payment_id: UUID,
        admin_id: UUID,
        comment: str | None = None,
        *,
        require_proof: bool = True,
        verification_method: str = "MANUAL",
        incoming_credit_id: UUID | None = None,
    ) -> Payment:
        payment = self.repository.get_for_update(db, payment_id)
        if not payment or payment.status != PaymentStatus.PENDING_VERIFICATION:
            raise HTTPException(status_code=409, detail="Payment is not awaiting verification")

        if require_proof:
            proof_id = db.scalar(
                select(PaymentFile.id)
                .join(PaymentRevision, PaymentRevision.id == PaymentFile.payment_revision_id)
                .where(
                    PaymentFile.payment_id == payment.id,
                    PaymentRevision.revision_no == payment.current_revision,
                )
                .limit(1)
            )
            if not proof_id:
                raise HTTPException(
                    status_code=409,
                    detail="At least one screenshot is required before approval",
                )

        # Every approval path claims known UTRs permanently, including manual
        # approval before email arrival. Reversal never releases those claims.
        references = set(db.scalars(select(PaymentProofExtraction.selected_upi_reference).where(
            PaymentProofExtraction.payment_id == payment.id,
            PaymentProofExtraction.payment_revision == payment.current_revision,
            PaymentProofExtraction.selected_upi_reference.is_not(None),
        )).all())
        if payment.auto_verified_reference:
            references.add(payment.auto_verified_reference)
        for reference in sorted(references):
            claim_reference(db, reference, payment.id)
        now = datetime.now(UTC)
        payment.status = PaymentStatus.APPROVED
        payment.approved_at = now
        payment.approved_by = admin_id
        payment.verification_method = verification_method
        payment.verification_status = (
            "AUTO_VERIFIED" if verification_method == "HDFC_EMAIL" else "MANUAL_VERIFIED"
        )
        db.add(PaymentVerificationEvent(
            payment_id=payment.id,
            event_type=("AUTO_VERIFIED" if verification_method == "HDFC_EMAIL" else "MANUAL_APPROVED"),
            actor_type="SYSTEM" if verification_method == "HDFC_EMAIL" else "USER",
            actor_user_id=admin_id,
            incoming_credit_id=incoming_credit_id,
            upi_reference_masked=(
                f"********{payment.auto_verified_reference[-4:]}"
                if payment.auto_verified_reference else None
            ),
            metadata_json={"revision": payment.current_revision, "method": verification_method,
                           "approved_at": now.isoformat(), "references": sorted(references)},
        ))
        contributions = db.scalars(
            select(MemberMonthContribution)
            .where(MemberMonthContribution.payment_id == payment_id)
            .with_for_update()
        ).all()
        for contribution in contributions:
            contribution.status = ContributionStatus.APPROVED

        fund_account = db.scalar(
            select(FundAccount).where(
                FundAccount.is_default.is_(True), FundAccount.is_active.is_(True)
            )
        )
        if not fund_account:
            raise HTTPException(status_code=409, detail="Default fund account is not configured")
        db.add(
            FundEntry(
                entry_no=ledger_entry_no(),
                fund_account_id=fund_account.id,
                entry_date=datetime.now(UTC).date(),
                direction=LedgerDirection.CREDIT,
                entry_type="CONTRIBUTION",
                amount=payment.total_amount,
                reference_type="PAYMENT",
                reference_id=payment.id,
                description=f"Approved contribution {payment.payment_no}",
                created_by=admin_id,
            )
        )
        db.add(
            PaymentReview(
                payment_id=payment.id,
                revision_no=payment.current_revision,
                reviewed_by=admin_id,
                action=ReviewAction.APPROVED,
                comment=comment,
            )
        )
        receipt = self.receipts.create_for_payment(db, payment)
        self.notifications.create_for_users(
            db,
            user_ids=[payment.submitted_by],
            event_type="PAYMENT_APPROVED",
            title="Contribution approved ✅",
            message=f"{payment.payment_no} for ₹{payment.total_amount} was approved.",
            reference_type="payment",
            reference_id=payment.id,
            email_payload={
                "payment_id": str(payment.id),
                "receipt_id": str(receipt.id),
            },
            push_url=f"/?section=History&payment={payment.id}",
        )
        return payment

    def reject(self, db: Session, payment_id: UUID, admin_id: UUID, reason: str) -> Payment:
        payment = self.repository.get_for_update(db, payment_id)
        if not payment or payment.status != PaymentStatus.PENDING_VERIFICATION:
            raise HTTPException(status_code=409, detail="Payment is not awaiting verification")
        now = datetime.now(UTC)
        payment.status = PaymentStatus.REJECTED
        payment.rejected_at = now
        payment.rejected_by = admin_id
        payment.rejection_reason = reason
        db.add(PaymentVerificationEvent(
            payment_id=payment.id,
            event_type="MANUAL_REJECTED",
            actor_type="USER",
            actor_user_id=admin_id,
            metadata_json={"revision": payment.current_revision},
        ))
        contributions = db.scalars(
            select(MemberMonthContribution)
            .where(MemberMonthContribution.payment_id == payment_id)
            .with_for_update()
        ).all()
        for contribution in contributions:
            contribution.status = ContributionStatus.REJECTED
        db.add(
            PaymentReview(
                payment_id=payment.id,
                revision_no=payment.current_revision,
                reviewed_by=admin_id,
                action=ReviewAction.REJECTED,
                comment=reason,
            )
        )
        self.notifications.create_for_users(
            db,
            user_ids=[payment.submitted_by],
            event_type="PAYMENT_REJECTED",
            title="Contribution needs correction",
            message=f"{payment.payment_no}: {reason}",
            reference_type="payment",
            reference_id=payment.id,
            push_url=f"/?section=History&payment={payment.id}",
        )
        return payment

    def reverse(self, db: Session, payment_id: UUID, admin_id: UUID, reason: str) -> Payment:
        payment = self.repository.get_for_update(db, payment_id)
        if not payment or payment.status != PaymentStatus.APPROVED:
            raise HTTPException(status_code=409, detail="Only approved payments can be reversed")

        original_entry = db.scalar(
            select(FundEntry)
            .where(
                FundEntry.reference_type == "PAYMENT",
                FundEntry.reference_id == payment.id,
                FundEntry.entry_type == "CONTRIBUTION",
                FundEntry.direction == LedgerDirection.CREDIT,
                FundEntry.reversal_of_id.is_(None),
            )
            .with_for_update()
        )
        if not original_entry:
            raise HTTPException(status_code=409, detail="Original fund credit was not found")
        existing_reversal = db.scalar(
            select(FundEntry.id).where(FundEntry.reversal_of_id == original_entry.id)
        )
        if existing_reversal:
            raise HTTPException(status_code=409, detail="Payment has already been reversed")

        reversal_entry = FundEntry(
            entry_no=ledger_entry_no(),
            fund_account_id=original_entry.fund_account_id,
            entry_date=datetime.now(UTC).date(),
            direction=LedgerDirection.DEBIT,
            entry_type="REVERSAL",
            amount=original_entry.amount,
            reference_type="PAYMENT_REVERSAL",
            reference_id=payment.id,
            description=f"Reversal of {original_entry.entry_no}: {reason}",
            reversal_of_id=original_entry.id,
            created_by=admin_id,
        )
        db.add(reversal_entry)
        db.flush()
        db.add(
            PaymentReversal(
                payment_id=payment.id,
                original_fund_entry_id=original_entry.id,
                reversal_fund_entry_id=reversal_entry.id,
                reason=reason,
                reversed_by=admin_id,
            )
        )
        payment.status = PaymentStatus.REVERSED
        contributions = db.scalars(
            select(MemberMonthContribution)
            .where(MemberMonthContribution.payment_id == payment.id)
            .with_for_update()
        ).all()
        for contribution in contributions:
            contribution.status = ContributionStatus.REVERSED
        receipt = self.repository.receipt(db, payment.id)
        if receipt:
            receipt.status = "VOID"
        db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.event_type == "PAYMENT_APPROVED",
                NotificationOutbox.status.in_(("PENDING", "FAILED")),
                NotificationOutbox.payload["payment_id"].as_string() == str(payment.id),
            )
            .values(status="CANCELLED", processed_at=datetime.now(UTC))
        )
        self.notifications.create_for_users(
            db,
            user_ids=[payment.submitted_by],
            event_type="PAYMENT_REVERSED",
            title="Contribution reversed",
            message=f"{payment.payment_no} was reversed: {reason}",
            reference_type="payment",
            reference_id=payment.id,
        )
        return payment

    def _notify_reviewers(self, db: Session, payment: Payment, title: str) -> None:
        reviewer_ids = self.notifications.users_with_permission(db, PAYMENT_APPROVE)
        review_url = f"/admin?view=payments&payment={payment.id}&review=1"
        self.notifications.create_for_users(
            db,
            user_ids=reviewer_ids,
            event_type="PAYMENT_PENDING_VERIFICATION",
            title=title,
            message=f"{payment.payment_no} for ₹{payment.total_amount} needs review.",
            reference_type="payment",
            reference_id=payment.id,
            email_payload={"payment_id": str(payment.id), "revision": payment.current_revision},
            push_url=review_url,
            push_payload={
                "payment_id": str(payment.id),
                "revision": payment.current_revision,
                "actions": [
                    {"action": "review", "title": "Review"},
                    {"action": "reject", "title": "Reject"},
                ],
                "action_urls": {
                    "review": review_url,
                    "reject": f"{review_url}&reject=1",
                },
            },
        )

    def _replace_allocations(
        self, db: Session, payment: Payment, payload: CreatePaymentInput
    ) -> None:
        contributions: list[MemberMonthContribution] = []
        for item in payload.allocations:
            allocation = PaymentAllocation(
                payment_id=payment.id,
                member_id=item.member_id,
                contribution_year=item.year,
                contribution_month=item.month,
                amount=item.amount,
            )
            db.add(allocation)
            db.flush()
            contributions.append(
                MemberMonthContribution(
                    member_id=item.member_id,
                    year=item.year,
                    month=item.month,
                    payment_id=payment.id,
                    allocation_id=allocation.id,
                    amount=item.amount,
                    status=ContributionStatus.PENDING,
                )
            )
        if self.repository.conflicting_contributions(db, contributions):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="One or more selected member/month pairs are unavailable",
            )
        db.add_all(contributions)

    def _record_revision(self, db: Session, payment: Payment, payload: CreatePaymentInput) -> None:
        revision = PaymentRevision(
            payment_id=payment.id,
            revision_no=payment.current_revision,
            total_amount=payment.total_amount,
            user_note=payment.user_note,
            status_snapshot=PaymentStatus.PENDING_VERIFICATION,
            created_by=payment.created_by,
        )
        db.add(revision)
        db.flush()
        db.add_all(
            [
                PaymentAllocationRevision(
                    payment_revision_id=revision.id,
                    member_id=item.member_id,
                    year=item.year,
                    month=item.month,
                    amount=item.amount,
                )
                for item in payload.allocations
            ]
        )

    @staticmethod
    def _total(payload: CreatePaymentInput) -> Decimal:
        return sum((item.amount for item in payload.allocations), Decimal(0))
