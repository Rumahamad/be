from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission, user_has_permission
from app.config.settings import get_settings
from app.constants.permissions import SETTINGS_EDIT, PAYMENT_APPROVE
from app.db.session import SessionLocal, get_db
from app.models.backup import GoogleConnection
from app.models.identity import User
from app.schemas.backups import GoogleAuthorizationOutput
from app.engines.payment_verification.hdfc_email_parser import parse_hdfc_credit
from app.engines.payment_verification.screenshot_ocr import (
    OcrProcessingError, OcrUnavailableError, TesseractScreenshotOcr,
    extract_reference_candidates,
)
from app.jobs.payment_verification import process_payment_proof
from app.schemas.verification import (
    GmailVerificationStatusOutput, OcrTestOutput, VerificationFixtureInput,
    VerificationFixtureOutput,
)
from app.services.gmail_credit_sync_service import GmailCreditSyncService
from app.services.gmail_verification_oauth_service import GmailVerificationOAuthService, PURPOSE
from app.services.google_backup_oauth_service import GoogleBackupOAuthError

router = APIRouter(prefix="/admin/payment-verification", tags=["admin payment verification"])
oauth = GmailVerificationOAuthService()
sync_service = GmailCreditSyncService()


@router.get("/status", response_model=GmailVerificationStatusOutput)
def verification_status(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GmailVerificationStatusOutput:
    result = sync_service.status(db, include_payments=True)
    result.can_approve_verified = user_has_permission(db, actor, PAYMENT_APPROVE)
    return result


@router.post("/google/authorization", response_model=GoogleAuthorizationOutput)
def gmail_authorization(
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GoogleAuthorizationOutput:
    try:
        url, expires_at = oauth.start(db, actor)
    except GoogleBackupOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return GoogleAuthorizationOutput(authorization_url=url, expires_at=expires_at)


@router.get("/google/callback", include_in_schema=False)
def gmail_callback(
    state: str = Query(min_length=20, max_length=500),
    code: str | None = Query(default=None, min_length=5, max_length=4096),
    error: str | None = Query(default=None, max_length=200),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    result = "connected"
    if error or not code:
        result = "denied"
    else:
        try:
            oauth.complete(db, state, code)
        except GoogleBackupOAuthError:
            result = "failed"
    return RedirectResponse(
        f"{get_settings().frontend_url.rstrip('/')}/admin?{urlencode({'gmail_verification': result})}",
        status_code=303,
    )


@router.post("/gmail/sync", status_code=202)
def sync_gmail(
    background_tasks: BackgroundTasks,
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> dict[str, str]:
    background_tasks.add_task(_sync_gmail_background)
    return {"status": "QUEUED"}


def _sync_gmail_background() -> None:
    try:
        with SessionLocal() as db:
            sync_service.sync(db)
    except Exception as exc:
        with SessionLocal() as db, db.begin():
            connection = db.scalar(select(GoogleConnection).where(
                GoogleConnection.purpose == PURPOSE,
            ))
            if connection:
                connection.last_sync_error_code = type(exc).__name__[:80]


@router.post("/ocr/test", response_model=OcrTestOutput)
async def test_screenshot_ocr(
    request: Request,
    content_type: str = Header(default="application/octet-stream"),
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> OcrTestOutput:
    if content_type.split(";", 1)[0].lower() not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG, or WebP screenshot")
    content = await request.body()
    if not content or len(content) > get_settings().storage_max_file_bytes:
        raise HTTPException(status_code=413, detail="Screenshot must be between 1 byte and 5 MB")
    try:
        result = TesseractScreenshotOcr().extract(content)
    except OcrUnavailableError:
        return OcrTestOutput(status="ERROR", engine="TESSERACT", error_code="OCR_ENGINE_UNAVAILABLE")
    except OcrProcessingError:
        return OcrTestOutput(status="ERROR", engine="TESSERACT", error_code="OCR_PROCESSING_FAILED")
    return OcrTestOutput(
        status="REFERENCE_FOUND" if result.selected_reference else "NO_REFERENCE",
        selected_reference_masked=(
            f"********{result.selected_reference[-4:]}" if result.selected_reference else None
        ),
        confidence=result.confidence,
        candidate_count=len(result.candidates),
        engine=result.engine,
        engine_version=result.engine_version,
        error_code=None if result.selected_reference else "OCR_REFERENCE_NOT_FOUND",
    )


@router.post("/fixture/test", response_model=VerificationFixtureOutput)
def test_verification_fixture(
    payload: VerificationFixtureInput,
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> VerificationFixtureOutput:
    parsed = parse_hdfc_credit(payload.email_body)
    candidates = extract_reference_candidates(payload.screenshot_ocr_text)
    screenshot_reference = candidates[0].value if candidates else None
    reference_matches = bool(
        screenshot_reference and parsed.upi_reference and screenshot_reference == parsed.upi_reference
    )
    amount_matches = parsed.amount is not None and Decimal(parsed.amount) == payload.payment_amount
    account_matches = parsed.recipient_account_last4 == payload.expected_account_last4
    errors: list[str] = []
    if not parsed.valid:
        errors.append(parsed.error_code or "EMAIL_PARSE_FAILED")
    if not screenshot_reference:
        errors.append("OCR_REFERENCE_NOT_FOUND")
    if parsed.valid and screenshot_reference and not reference_matches:
        errors.append("REFERENCE_MISMATCH")
    if parsed.amount is not None and not amount_matches:
        errors.append("AMOUNT_MISMATCH")
    if parsed.recipient_account_last4 and not account_matches:
        errors.append("RECIPIENT_ACCOUNT_MISMATCH")
    return VerificationFixtureOutput(
        email_valid=parsed.valid,
        screenshot_reference_found=bool(screenshot_reference),
        reference_matches=reference_matches,
        amount_matches=amount_matches,
        account_matches=account_matches,
        would_auto_approve_if_authenticated=(
            parsed.valid and reference_matches and amount_matches and account_matches
        ),
        error_codes=errors,
    )


@router.post("/payments/{payment_id}/process", status_code=202)
def retry_payment_verification(
    payment_id: UUID,
    background_tasks: BackgroundTasks,
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> dict[str, str]:
    background_tasks.add_task(process_payment_proof, payment_id, force=True)
    return {"status": "QUEUED"}
