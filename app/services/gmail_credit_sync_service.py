from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.session import SessionLocal
from app.engines.payment_verification.gmail_client import GmailClient
from app.engines.payment_verification.email_authentication import authenticate, AUTH_VERSION
from app.engines.payment_verification.hdfc_email_parser import (
    PARSER_VERSION, normalize_email_address, parse_hdfc_credit,
)
from app.engines.payment_verification.paytm_merchant_email_parser import (
    PARSER_VERSION as PAYTM_PARSER_VERSION,
    merchant_names_match,
    parse_paytm_merchant_payment,
)
from app.models.backup import GoogleConnection
from app.models.enums import PaymentStatus
from app.models.payments import Payment
from app.models.verification import IncomingUpiCredit
from app.schemas.verification import GmailSyncOutput, GmailVerificationStatusOutput
from app.services.gmail_verification_oauth_service import GmailVerificationOAuthService, PURPOSE
from app.services.google_backup_oauth_service import GoogleBackupOAuthError
from app.services.payment_reconciliation_service import PaymentReconciliationService


@dataclass(frozen=True)
class GmailCreditSource:
    source: str
    query: str
    trusted_sender: str
    forwarder: str
    expected_recipient: str
    parser_version: str


class GmailCreditSyncService:
    oauth = GmailVerificationOAuthService()

    @staticmethod
    def _sources(settings) -> tuple[GmailCreditSource, ...]:
        sources: list[GmailCreditSource] = []
        if settings.hdfc_gmail_source_configured:
            sources.append(GmailCreditSource(
                source="HDFC_GMAIL",
                query=settings.gmail_hdfc_search_query,
                trusted_sender=settings.hdfc_credit_email_from,
                forwarder=settings.hdfc_forwarder_email,
                expected_recipient=settings.hdfc_expected_account_last4,
                parser_version=PARSER_VERSION,
            ))
        if settings.paytm_merchant_source_configured:
            sources.append(GmailCreditSource(
                source="PAYTM_MERCHANT_GMAIL",
                query=settings.gmail_paytm_search_query,
                trusted_sender=settings.paytm_merchant_email_from,
                forwarder=settings.paytm_forwarder_email,
                expected_recipient=settings.paytm_expected_merchant_name,
                parser_version=PAYTM_PARSER_VERSION,
            ))
        return tuple(sources)

    def sync_if_ready(self) -> GmailSyncOutput | None:
        with SessionLocal() as db:
            status = self.status(db)
            if not status.configured or not status.connected:
                return None
            connection = db.scalar(select(GoogleConnection).where(
                GoogleConnection.purpose == PURPOSE,
                GoogleConnection.status == "ACTIVE",
            ))
            if connection and connection.last_sync_at:
                due_at = connection.last_sync_at + timedelta(
                    seconds=get_settings().gmail_poll_interval_seconds,
                )
                if due_at > datetime.now(UTC):
                    return None
            return self.sync(db)

    def status(self, db: Session, *, include_payments: bool = False) -> GmailVerificationStatusOutput:
        settings = get_settings()
        connection = db.scalar(select(GoogleConnection).where(GoogleConnection.purpose == PURPOSE))
        pending = db.scalar(select(func.count()).select_from(Payment).where(
            Payment.status == PaymentStatus.PENDING_VERIFICATION,
        )) or 0
        unmatched = db.scalar(select(func.count()).select_from(IncomingUpiCredit).where(
            IncomingUpiCredit.matched_payment_id.is_(None),
            IncomingUpiCredit.parse_status == "READY",
        )) or 0
        processed = db.scalar(select(func.count()).select_from(IncomingUpiCredit)) or 0
        rejected = db.scalar(select(func.count()).select_from(IncomingUpiCredit).where(
            IncomingUpiCredit.parse_status == "REJECTED",
        )) or 0
        review_required = db.scalar(select(func.count()).select_from(IncomingUpiCredit).where(
            IncomingUpiCredit.parse_status == "REVIEW_REQUIRED",
        )) or 0
        latest_credit = db.execute(
            select(
                IncomingUpiCredit.parse_status,
                IncomingUpiCredit.parse_error_code,
                IncomingUpiCredit.message_received_at,
            )
            .order_by(
                IncomingUpiCredit.message_received_at.desc(),
                IncomingUpiCredit.created_at.desc(),
            )
            .limit(1)
        ).first()
        from app.services.verification_report_service import payment_match_report
        return GmailVerificationStatusOutput(
            approval_mode=('SHADOW' if settings.payment_auto_verify_shadow_mode else
                           'AUTOMATIC' if settings.payment_auto_verify_enabled else 'DISABLED'),
            payments=payment_match_report(db) if include_payments else [],
            configured=settings.gmail_verification_configured,
            connected=bool(connection and connection.status == "ACTIVE"),
            account_email=connection.account_email if connection else None,
            last_successful_sync_at=connection.last_sync_at if connection else None,
            last_error_code=connection.last_sync_error_code if connection else None,
            last_credit_error_code=(
                latest_credit.parse_error_code
                if latest_credit and latest_credit.parse_status in {"REJECTED", "REVIEW_REQUIRED"}
                else None
            ),
            latest_credit_status=latest_credit.parse_status if latest_credit else None,
            latest_credit_received_at=latest_credit.message_received_at if latest_credit else None,
            pending_payments=pending,
            unmatched_credits=unmatched,
            processed_credits=processed,
            rejected_credits=rejected,
            review_required_credits=review_required,
        )

    def sync(self, db: Session) -> GmailSyncOutput:
        settings = get_settings()
        if not settings.gmail_verification_configured:
            raise GoogleBackupOAuthError("Gmail verification configuration is incomplete")
        connection = db.scalar(select(GoogleConnection).where(
            GoogleConnection.purpose == PURPOSE, GoogleConnection.status == "ACTIVE",
        ))
        if not connection:
            raise GoogleBackupOAuthError("Gmail verification is not connected")
        connection_id = connection.id
        actor_user_id = connection.connected_by
        client = GmailClient(self.oauth.access_token(connection))
        # Do not keep a PostgreSQL transaction open while Gmail is contacted.
        db.rollback()
        message_sources: dict[str, GmailCreditSource] = {}
        for source in self._sources(settings):
            for message_id in client.list_message_ids(source.query):
                message_sources.setdefault(message_id, source)
        message_ids = list(message_sources)
        existing_statuses = dict(db.execute(select(
            IncomingUpiCredit.gmail_message_id,
            IncomingUpiCredit.parse_status,
        ).where(IncomingUpiCredit.gmail_message_id.in_(message_ids))).all()) if message_ids else {}
        outdated = set(db.scalars(select(IncomingUpiCredit.gmail_message_id).where(
            IncomingUpiCredit.gmail_message_id.in_(message_ids),
            IncomingUpiCredit.consumed_at.is_(None),
            func.coalesce(IncomingUpiCredit.authentication_evidence['version'].as_string(), '') != AUTH_VERSION,
        )).all()) if message_ids else set()
        db.rollback()
        messages = [
            (message_sources[message_id], message_id, client.get_message(message_id))
            for message_id in message_ids
            if message_id not in existing_statuses
            or message_id in outdated
            or existing_statuses[message_id] in {"REJECTED", "REVIEW_REQUIRED"}
        ]
        # Serialize imports from the scheduler and Sync button. No network calls
        # occur while holding this lock; repeated deliveries remain idempotent.
        db.execute(text("SELECT pg_advisory_xact_lock(710021)"))
        connection = db.get(GoogleConnection, connection_id)
        if not connection or connection.status != "ACTIVE":
            raise GoogleBackupOAuthError("Gmail verification was disconnected during sync")
        stored = rejected = 0
        ready_references: list[str] = []
        for source, message_id, message in messages:
            existing_credit = db.scalar(select(IncomingUpiCredit).where(
                IncomingUpiCredit.gmail_message_id == message_id,
            ).with_for_update())
            if existing_credit and (existing_credit.consumed_at or
                    existing_credit.authentication_evidence.get('version') == AUTH_VERSION
                    and existing_credit.parse_status == 'READY'):
                continue
            headers = client.headers(message)
            body = client.body_text(message)
            if source.source == "HDFC_GMAIL":
                parsed = parse_hdfc_credit(body)
                recipient_matches = parsed.recipient_account_last4 == source.expected_recipient
                merchant_order_id = None
            else:
                parsed = parse_paytm_merchant_payment(body)
                recipient_matches = merchant_names_match(
                    parsed.merchant_name, source.expected_recipient,
                )
                merchant_order_id = parsed.paytm_order_id
            outer_from = normalize_email_address(headers.get("from", ""))
            trusted_sender = normalize_email_address(source.trusted_sender)
            forwarder = normalize_email_address(source.forwarder)
            is_forwarded = bool(
                headers.get("x-forwarded-for") or headers.get("x-forwarded-to")
            )
            email_from = outer_from
            sender_matches = email_from == trusted_sender
            authentication = authenticate(message, trusted_sender, forwarder, connection.account_email)
            sender_verified = authentication['verified']
            spf_pass, dkim_pass = authentication['spf_pass'], authentication['dkim_pass']
            parse_status = "READY" if parsed.valid and sender_verified and recipient_matches else "REJECTED"
            error_code = parsed.error_code
            if not sender_matches:
                error_code = "SENDER_MISMATCH"
            elif not sender_verified:
                if is_forwarded and parsed.valid and sender_matches and recipient_matches:
                    parse_status = "REVIEW_REQUIRED"
                    error_code = authentication['reason'] or "FORWARDED_EMAIL_REVIEW_REQUIRED"
                else:
                    error_code = "FORWARDED_EMAIL_UNVERIFIED" if is_forwarded else "EMAIL_AUTH_FAILED"
            elif not recipient_matches:
                error_code = (
                    "RECIPIENT_ACCOUNT_MISMATCH"
                    if source.source == "HDFC_GMAIL" else "MERCHANT_NAME_MISMATCH"
                )
            existing_credit = db.scalar(select(IncomingUpiCredit).where(
                IncomingUpiCredit.gmail_message_id == message_id,
            ))
            # Untrusted/rejected messages must never reserve a financial
            # transaction reference and block a later authenticated message.
            upi_reference = (
                parsed.upi_reference
                if source.source == "HDFC_GMAIL" and parse_status == "READY"
                else None
            )
            duplicate_query = select(IncomingUpiCredit.id).where(
                IncomingUpiCredit.upi_reference == upi_reference,
            )
            if existing_credit:
                duplicate_query = duplicate_query.where(IncomingUpiCredit.id != existing_credit.id)
            if upi_reference and db.scalar(duplicate_query):
                upi_reference = None
                parse_status = "REJECTED"
                error_code = "DUPLICATE_REFERENCE"
            credit = existing_credit or IncomingUpiCredit(
                gmail_message_id=message_id,
                message_received_at=client.received_at(message),
                email_from=email_from,
                parser_version=source.parser_version,
            )
            credit.source = source.source
            credit.gmail_thread_id = message.get("threadId")
            credit.message_received_at = client.received_at(message)
            credit.amount = parsed.amount
            credit.transaction_at = parsed.transaction_at
            credit.sender_name = parsed.sender_name
            credit.sender_vpa = parsed.sender_vpa
            credit.observed_upi_reference = (
                parsed.upi_reference if source.source == "HDFC_GMAIL" else None
            )
            credit.upi_reference = upi_reference
            credit.recipient_account_last4 = (
                parsed.recipient_account_last4 if source.source == "HDFC_GMAIL" else None
            )
            credit.email_from = email_from
            credit.email_subject = headers.get("subject")
            credit.sender_verified = sender_verified
            credit.spf_pass = spf_pass
            credit.dkim_pass = dkim_pass
            credit.recipient_account_matches = recipient_matches
            credit.parse_status = parse_status
            credit.parse_error_code = error_code
            credit.parser_version = source.parser_version
            credit.authentication_evidence = {
                **authentication,
                "payment_source": source.source,
                **({"merchant_order_id": merchant_order_id,
                    "merchant_name": parsed.merchant_name}
                   if source.source == "PAYTM_MERCHANT_GMAIL" else {}),
            }
            if existing_credit is None:
                try:
                    with db.begin_nested():
                        db.add(credit)
                        db.flush()
                except IntegrityError:
                    continue
                stored += 1
            else:
                db.flush()
            rejected += parse_status == "REJECTED"
            if parse_status == "READY" and upi_reference:
                ready_references.append(upi_reference)
        db.commit()
        # Reconsider all trusted, unconsumed credits. This recovers when OCR and
        # email arrive in either order, or after a worker restart.
        ready_references = list(db.scalars(select(IncomingUpiCredit.upi_reference).where(
            IncomingUpiCredit.source == "HDFC_GMAIL",
            IncomingUpiCredit.parse_status == "READY",
            IncomingUpiCredit.consumed_at.is_(None),
            IncomingUpiCredit.upi_reference.is_not(None),
        )).all())
        review_references = list(db.scalars(select(IncomingUpiCredit.observed_upi_reference).where(
            IncomingUpiCredit.source == "HDFC_GMAIL",
            IncomingUpiCredit.parse_status == "REVIEW_REQUIRED",
            IncomingUpiCredit.consumed_at.is_(None),
            IncomingUpiCredit.observed_upi_reference.is_not(None),
        )).all())
        outcomes: list[str] = []
        reconciliation = PaymentReconciliationService()
        for reference in dict.fromkeys([*ready_references, *review_references]):
            outcomes.extend(reconciliation.reconcile_reference(db, reference, actor_user_id))
            db.commit()
        connection = db.get(GoogleConnection, connection_id)
        connection.last_sync_at = datetime.now(UTC)
        connection.last_sync_error_code = None
        db.commit()
        return GmailSyncOutput(
            discovered=len(message_ids), stored=stored, rejected=rejected,
            matched=sum(value in {"SHADOW_MATCH", "AUTO_APPROVED"} for value in outcomes),
            auto_approved=outcomes.count("AUTO_APPROVED"),
        )
