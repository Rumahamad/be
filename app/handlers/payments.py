from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import user_has_permission
from app.constants import permissions
from app.models.identity import User
from app.models.payments import Payment
from app.schemas.payments import (
    ContributionAvailabilityInput,
    ContributionMonthStateOutput,
    CreatePaymentInput,
    PaymentAllocationOutput,
    PaymentDetailOutput,
    PaymentReversalOutput,
    PaymentReviewOutput,
    PaymentRevisionAllocationOutput,
    PaymentRevisionOutput,
    ReceiptOutput,
)
from app.services.audit_service import AuditService
from app.services.payment_service import PaymentService


class PaymentHandler:
    def __init__(self) -> None:
        self.payments = PaymentService()
        self.audit = AuditService()

    def create(self, db: Session, user: User, payload: CreatePaymentInput) -> Payment:
        includes_other_members = any(item.member_id != user.id for item in payload.allocations)
        required = (
            permissions.PAYMENT_CREATE_ANY
            if includes_other_members
            else permissions.PAYMENT_CREATE_SELF
        )
        if not user_has_permission(db, user, required):
            raise HTTPException(status_code=403, detail=f"Missing permission: {required}")
        auto_approve = user_has_permission(db, user, permissions.PAYMENT_APPROVE)
        payment = self.payments.submit(db, user.id, payload, auto_approve=auto_approve)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.created",
            entity_type="payment",
            entity_id=payment.id,
            after_data={"revision": 1, "auto_approved": auto_approve},
        )
        return payment

    def detail(self, db: Session, user: User, payment_id: UUID) -> PaymentDetailOutput:
        row = self.payments.repository.get_with_submitter(db, payment_id)
        if not row:
            raise HTTPException(status_code=404, detail="Payment not found")
        payment, submitter = row
        can_view = (
            user_has_permission(db, user, permissions.PAYMENT_VIEW_ALL)
            or (
                payment.submitted_by == user.id
                and user_has_permission(db, user, permissions.PAYMENT_VIEW_SELF)
            )
            or (
                payment.created_by == user.id
                and user_has_permission(db, user, permissions.PAYMENT_VIEW_CREATED)
            )
        )
        if not can_view:
            raise HTTPException(status_code=403, detail="You cannot view this payment")
        receipt = self.payments.repository.receipt(db, payment.id)
        reversal_row = self.payments.repository.reversal(db, payment.id)
        reversal_output = None
        if reversal_row:
            reversal, reversed_by, reversal_entry_no = reversal_row
            reversal_output = PaymentReversalOutput(
                id=reversal.id,
                reason=reversal.reason,
                reversed_by=reversed_by.id,
                reversed_by_name=reversed_by.display_name,
                reversed_at=reversal.reversed_at,
                reversal_entry_no=reversal_entry_no,
            )
        return PaymentDetailOutput(
            id=payment.id,
            payment_no=payment.payment_no,
            status=payment.status.value,
            total_amount=payment.total_amount,
            current_revision=payment.current_revision,
            user_note=payment.user_note,
            submitted_at=payment.submitted_at,
            approved_at=payment.approved_at,
            rejected_at=payment.rejected_at,
            rejection_reason=payment.rejection_reason,
            verification_status=payment.verification_status,
            verification_method=payment.verification_method,
            verification_reference_masked=(
                f"********{payment.auto_verified_reference[-4:]}"
                if payment.auto_verified_reference else None
            ),
            submitted_by_id=submitter.id,
            submitted_by_name=submitter.display_name,
            submitted_by_email=submitter.email,
            allocations=[
                PaymentAllocationOutput(
                    member_id=member.id,
                    member_code=member.member_code,
                    member_name=member.display_name,
                    year=allocation.contribution_year,
                    month=allocation.contribution_month,
                    amount=allocation.amount,
                )
                for allocation, member in self.payments.repository.allocations_with_members(
                    db, payment.id
                )
            ],
            reviews=[
                PaymentReviewOutput(
                    revision_no=review.revision_no,
                    action=review.action.value,
                    comment=review.comment,
                    reviewed_by=reviewer.id,
                    reviewer_name=reviewer.display_name,
                    created_at=review.created_at,
                )
                for review, reviewer in self.payments.repository.reviews_with_reviewers(
                    db, payment.id
                )
            ],
            revisions=[
                PaymentRevisionOutput(
                    revision_no=revision.revision_no,
                    total_amount=revision.total_amount,
                    user_note=revision.user_note,
                    status_snapshot=revision.status_snapshot.value,
                    created_at=revision.created_at,
                    allocations=[
                        PaymentRevisionAllocationOutput(
                            member_id=allocation.member_id,
                            year=allocation.year,
                            month=allocation.month,
                            amount=allocation.amount,
                        )
                        for allocation in revision_allocations
                    ],
                )
                for revision, revision_allocations in (
                    self.payments.repository.revisions_with_allocations(db, payment.id)
                )
            ],
            receipt=(
                ReceiptOutput(
                    id=receipt.id,
                    receipt_no=receipt.receipt_no,
                    status=receipt.status,
                    generated_at=receipt.generated_at,
                )
                if receipt
                else None
            ),
            reversal=reversal_output,
        )

    def availability(
        self, db: Session, user: User, payload: ContributionAvailabilityInput
    ) -> list[ContributionMonthStateOutput]:
        includes_other_members = any(member_id != user.id for member_id in payload.member_ids)
        if includes_other_members and not user_has_permission(
            db, user, permissions.PAYMENT_CREATE_ANY
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Missing permission: {permissions.PAYMENT_CREATE_ANY}",
            )
        if not includes_other_members and not (
            user_has_permission(db, user, permissions.PAYMENT_CREATE_SELF)
            or user_has_permission(db, user, permissions.PAYMENT_CREATE_ANY)
        ):
            raise HTTPException(status_code=403, detail="Payment creation is unavailable")
        return self.payments.availability(db, payload)

    def resubmit(
        self, db: Session, user: User, payment_id: UUID, payload: CreatePaymentInput
    ) -> Payment:
        payment = db.get(Payment, payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        required = (
            permissions.PAYMENT_EDIT_REJECTED_SELF
            if payment.submitted_by == user.id
            else permissions.PAYMENT_EDIT_REJECTED_CREATED
        )
        if not user_has_permission(db, user, required):
            raise HTTPException(status_code=403, detail=f"Missing permission: {required}")
        updated = self.payments.resubmit(db, payment_id, user.id, payload)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.resubmitted",
            entity_type="payment",
            entity_id=updated.id,
            after_data={"revision": updated.current_revision},
        )
        return updated

    def approve(self, db: Session, user: User, payment_id: UUID, *, verified: bool = False) -> Payment:
        if verified:
            from app.services.payment_reconciliation_service import PaymentReconciliationService
            result = PaymentReconciliationService().reconcile_payment(
                db, payment_id, user.id, approve_verified=True,
            )
            if result != 'VERIFIED_APPROVED':
                raise HTTPException(409, f'Verified approval unavailable: {result}. Refresh and review the payment.')
            payment = db.get(Payment, payment_id)
        else:
            payment = self.payments.approve(db, payment_id, user.id)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.approved",
            entity_type="payment",
            entity_id=payment.id,
            after_data={"revision": payment.current_revision},
        )
        return payment

    def mark_ready_for_review(self, db: Session, user: User, payment_id: UUID) -> Payment:
        payment = self.payments.mark_ready_for_review(db, payment_id, user.id)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.ready_for_review",
            entity_type="payment",
            entity_id=payment.id,
            after_data={"revision": payment.current_revision},
        )
        return payment

    def reject(self, db: Session, user: User, payment_id: UUID, reason: str) -> Payment:
        payment = self.payments.reject(db, payment_id, user.id, reason)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.rejected",
            entity_type="payment",
            entity_id=payment.id,
            after_data={"revision": payment.current_revision, "reason": reason},
        )
        return payment

    def reverse(self, db: Session, user: User, payment_id: UUID, reason: str) -> Payment:
        payment = self.payments.reverse(db, payment_id, user.id, reason)
        self.audit.record(
            db,
            actor_user_id=user.id,
            action="payment.reversed",
            entity_type="payment",
            entity_id=payment.id,
            after_data={"reason": reason},
        )
        return payment
