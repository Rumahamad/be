"""Process PUSH-channel notifications from the outbox."""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.communications import NotificationDelivery, NotificationOutbox
from app.models.identity import User
from app.models.push_subscriptions import PushSubscription
from app.services.push_service import PushDeliveryError, send_push

logger = logging.getLogger(__name__)


class PushOutboxService:
    """Processes NotificationOutbox rows where channel='PUSH'."""

    def process_due(self, db: Session, *, limit: int = 100) -> int:
        settings = get_settings()
        if not settings.push_enabled:
            return 0

        now = datetime.now(UTC)
        items = db.scalars(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.channel == "PUSH",
                NotificationOutbox.status.in_(("PENDING", "FAILED")),
                NotificationOutbox.attempt_count < settings.notification_max_attempts,
                (NotificationOutbox.next_retry_at.is_(None))
                | (NotificationOutbox.next_retry_at <= now),
            )
            .order_by(NotificationOutbox.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()

        processed = 0
        for item in items:
            user = db.get(User, item.recipient_user_id)
            if not user:
                self._fail(db, item, "user_not_found", "Recipient user not found")
                continue

            subscriptions = db.scalars(
                select(PushSubscription).where(
                    PushSubscription.user_id == item.recipient_user_id,
                    PushSubscription.is_active.is_(True),
                )
            ).all()

            if not subscriptions:
                # No subscriptions — mark as sent (nothing to do, not an error)
                item.status = "SENT"
                item.processed_at = now
                processed += 1
                continue

            # Keep the encrypted payload comfortably below common Web Push limits.
            title = str(item.payload.get("title", "BNC"))[:120]
            body = str(item.payload.get("message", ""))[:1000]
            url = str(item.payload.get("url", "/"))[:1000]
            tag = str(item.payload.get("tag", item.event_type.lower()))[:120]
            actions = item.payload.get("actions")
            action_urls = item.payload.get("action_urls")

            sent_count = 0
            errors: list[str] = []
            for sub in subscriptions:
                try:
                    send_push(
                        endpoint=sub.endpoint,
                        p256dh=sub.p256dh,
                        auth=sub.auth,
                        title=title,
                        body=body,
                        url=url,
                        tag=tag,
                        actions=actions if isinstance(actions, list) else None,
                        action_urls=action_urls if isinstance(action_urls, dict) else None,
                        vapid_public_key=settings.vapid_public_key,
                        vapid_private_key_pem=settings.vapid_private_key_pem,
                        vapid_subject=settings.vapid_subject,
                    )
                    sub.last_used_at = now
                    sent_count += 1
                except PushDeliveryError as exc:
                    error_str = str(exc)
                    # GONE means the subscription is expired — deactivate it
                    if error_str.startswith("GONE:"):
                        sub.is_active = False
                        logger.info("Deactivated expired push subscription %s", sub.id)
                    errors.append(error_str)
                except Exception as exc:
                    logger.exception("Unexpected push error for outbox %s", item.id)
                    errors.append(str(exc))

            item.attempt_count += 1
            delivered = sent_count > 0
            db.add(
                NotificationDelivery(
                    outbox_id=item.id,
                    provider="webpush",
                    recipient=f"{sent_count}/{len(subscriptions)} active subscription(s)",
                    status="SENT" if delivered else "FAILED",
                    error_message=" | ".join(errors)[:2000] or None,
                    attempt_no=item.attempt_count,
                )
            )
            if delivered:
                item.status = "SENT"
                item.processed_at = now
                processed += 1
            else:
                item.status = "FAILED"
                retry_minutes = min(2 ** (item.attempt_count - 1), 60 * 24)
                item.next_retry_at = now + timedelta(minutes=retry_minutes)

        return processed

    @staticmethod
    def _fail(
        db: Session, item: NotificationOutbox, code: str, message: str
    ) -> None:
        item.attempt_count += 1
        item.status = "FAILED"
        item.next_retry_at = datetime.now(UTC) + timedelta(minutes=5)
        db.add(
            NotificationDelivery(
                outbox_id=item.id,
                provider="webpush",
                recipient="",
                status="FAILED",
                error_code=code,
                error_message=message,
                attempt_no=item.attempt_count,
            )
        )
