from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission, user_has_permission
from app.constants import permissions
from app.constants.permissions import PAYMENT_APPROVE, PAYMENT_REJECT, PAYMENT_REVERSE
from app.db.session import get_db
from app.handlers.payments import PaymentHandler
from app.jobs.payment_verification import process_payment_proof
from app.jobs.push_notifications import process_push_outbox
from app.models.enums import PaymentStatus
from app.models.identity import User
from app.schemas.payments import (
    ContributionAvailabilityInput,
    ContributionAvailabilityOutput,
    CreatePaymentInput,
    PaymentDetailOutput,
    PaymentFileOutput,
    PaymentListOutput,
    PaymentOutput,
    PaymentQueueItem,
    ReceiptEmailOutput,
    RejectPaymentInput,
    ReversePaymentInput,
)
from app.services.email_service import EmailDeliveryError
from app.services.payment_file_service import PaymentFileService
from app.services.receipt_delivery_service import ReceiptDeliveryService
from app.services.receipt_service import ReceiptService

router = APIRouter(prefix="/payments", tags=["payments"])
handler = PaymentHandler()
file_service = PaymentFileService()
receipt_service = ReceiptService()
receipt_delivery_service = ReceiptDeliveryService()


def output(payment) -> PaymentOutput:
    return PaymentOutput(
        id=payment.id,
        payment_no=payment.payment_no,
        status=payment.status.value,
        total_amount=payment.total_amount,
        current_revision=payment.current_revision,
        submitted_at=payment.submitted_at,
        verification_status=payment.verification_status,
        verification_method=payment.verification_method,
    )


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="The requested financial record conflicts with existing data"
        ) from exc


@router.post("/availability", response_model=ContributionAvailabilityOutput)
def contribution_availability(
    payload: ContributionAvailabilityInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ContributionAvailabilityOutput:
    return ContributionAvailabilityOutput(items=handler.availability(db, user, payload))


@router.get("", response_model=PaymentListOutput)
def list_payments(
    payment_status: PaymentStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentListOutput:
    if user_has_permission(db, user, permissions.PAYMENT_VIEW_ALL):
        submitted_by = None
    elif user_has_permission(db, user, permissions.PAYMENT_VIEW_CREATED):
        submitted_by = user.id
    else:
        submitted_by = user.id
    rows, total = handler.payments.repository.list_with_submitter(
        db,
        submitted_by=submitted_by,
        payment_status=payment_status,
        offset=offset,
        limit=limit,
    )
    return PaymentListOutput(
        items=[
            PaymentQueueItem(
                id=payment.id,
                payment_no=payment.payment_no,
                status=payment.status.value,
                total_amount=payment.total_amount,
                current_revision=payment.current_revision,
                submitted_at=payment.submitted_at,
                submitted_by_id=submitter.id,
                submitted_by_name=submitter.display_name,
                submitted_by_email=submitter.email,
                rejection_reason=payment.rejection_reason,
                verification_status=payment.verification_status,
                verification_method=payment.verification_method,
            )
            for payment, submitter in rows
        ],
        total=total,
    )


@router.post("", response_model=PaymentOutput, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: CreatePaymentInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentOutput:
    payment = handler.create(db, user, payload)
    commit(db)
    background_tasks.add_task(process_push_outbox)
    return output(payment)


@router.get("/{payment_id}", response_model=PaymentDetailOutput)
def payment_detail(
    payment_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentDetailOutput:
    return handler.detail(db, user, payment_id)


@router.get("/{payment_id}/receipt")
def download_receipt(
    payment_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    detail = handler.detail(db, user, payment_id)
    if detail.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Receipt is available after approval")
    content, receipt = receipt_service.render(db, payment_id)
    db.commit()
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{receipt.receipt_no}.pdf"'
        },
    )


@router.post("/{payment_id}/receipt/email", response_model=ReceiptEmailOutput)
def email_receipt(
    payment_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ReceiptEmailOutput:
    # Reuse the same object-level authorization as the detail and download routes.
    handler.detail(db, user, payment_id)
    try:
        result = receipt_delivery_service.send(db, actor=user, payment_id=payment_id)
        commit(db)
    except HTTPException:
        # Receipt rendering/status failures recorded by the service are audit-worthy too.
        commit(db)
        raise
    except EmailDeliveryError as exc:
        # Preserve the failure audit entry while returning a safe operational error.
        commit(db)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ReceiptEmailOutput(
        status="SENT",
        receipt_no=result.receipt_no,
        recipient=result.recipient,
    )


@router.put("/{payment_id}/resubmit", response_model=PaymentOutput)
def resubmit_payment(
    payment_id: UUID,
    payload: CreatePaymentInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentOutput:
    payment = handler.resubmit(db, user, payment_id, payload)
    commit(db)
    background_tasks.add_task(process_push_outbox)
    return output(payment)


@router.post("/{payment_id}/approve", response_model=PaymentOutput)
def approve_payment(
    payment_id: UUID,
    background_tasks: BackgroundTasks,
    verified: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PAYMENT_APPROVE)),
) -> PaymentOutput:
    payment = handler.approve(db, user, payment_id, verified=verified)
    commit(db)
    background_tasks.add_task(process_push_outbox)
    return output(payment)


@router.post("/{payment_id}/ready-for-review", response_model=PaymentOutput)
def mark_payment_ready_for_review(
    payment_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentOutput:
    payment = handler.mark_ready_for_review(db, user, payment_id)
    commit(db)
    background_tasks.add_task(process_payment_proof, payment_id)
    background_tasks.add_task(process_push_outbox)
    return output(payment)


@router.post("/{payment_id}/reject", response_model=PaymentOutput)
def reject_payment(
    payment_id: UUID,
    payload: RejectPaymentInput,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PAYMENT_REJECT)),
) -> PaymentOutput:
    payment = handler.reject(db, user, payment_id, payload.reason)
    commit(db)
    background_tasks.add_task(process_push_outbox)
    return output(payment)


@router.post("/{payment_id}/reverse", response_model=PaymentOutput)
def reverse_payment(
    payment_id: UUID,
    payload: ReversePaymentInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(PAYMENT_REVERSE)),
) -> PaymentOutput:
    payment = handler.reverse(db, user, payment_id, payload.reason)
    commit(db)
    return output(payment)


@router.post("/{payment_id}/files", response_model=PaymentFileOutput, status_code=status.HTTP_201_CREATED)
async def upload_payment_file(
    payment_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    filename: str = Query(default="screenshot", min_length=1, max_length=255),
    content_type: str = Header(default="application/octet-stream"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PaymentFileOutput:
    content = await request.body()
    uploaded = file_service.upload(
        db,
        user,
        payment_id,
        filename=filename,
        mime_type=content_type,
        content=content,
    )
    return uploaded


@router.get("/{payment_id}/files", response_model=list[PaymentFileOutput])
def list_payment_files(
    payment_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[PaymentFileOutput]:
    return file_service.list_files(db, user, payment_id)


@router.get("/{payment_id}/files/{file_id}")
def download_payment_file(
    payment_id: UUID,
    file_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    content, media_type, filename = file_service.download(db, user, payment_id, file_id)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
