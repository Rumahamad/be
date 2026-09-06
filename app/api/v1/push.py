"""Push subscription management endpoints."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.config.settings import get_settings
from app.db.session import get_db
from app.models.identity import User
from app.models.push_subscriptions import PushSubscription

router = APIRouter(tags=["push"])


class PushSubscriptionInput(BaseModel):
    endpoint: str = Field(min_length=20, max_length=4096)
    p256dh: str = Field(min_length=40, max_length=256)
    auth: str = Field(min_length=8, max_length=64)

    @field_validator("endpoint")
    @classmethod
    def endpoint_must_be_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Push endpoint must be an HTTPS URL without credentials")
        return value


class VapidPublicKeyOutput(BaseModel):
    public_key: str
    enabled: bool


@router.get("/push/vapid-public-key", response_model=VapidPublicKeyOutput)
def vapid_public_key() -> VapidPublicKeyOutput:
    """Return the VAPID public key the frontend needs to subscribe."""
    settings = get_settings()
    return VapidPublicKeyOutput(
        public_key=settings.vapid_public_key,
        enabled=settings.push_enabled,
    )


@router.post("/push/subscribe", status_code=201)
def subscribe(
    payload: PushSubscriptionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Register or refresh a push subscription for the authenticated user."""
    db.execute(
        update(PushSubscription)
        .where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id != user.id,
        )
        .values(is_active=False)
    )
    existing = db.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.endpoint == payload.endpoint,
        )
    )
    if existing:
        existing.p256dh = payload.p256dh
        existing.auth = payload.auth
        existing.is_active = True
        db.commit()
        return {"status": "updated"}

    db.add(
        PushSubscription(
            user_id=user.id,
            endpoint=payload.endpoint,
            p256dh=payload.p256dh,
            auth=payload.auth,
        )
    )
    db.commit()
    return {"status": "created"}


@router.post("/push/unsubscribe")
def unsubscribe(
    payload: PushSubscriptionInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Deactivate a push subscription."""
    sub = db.scalar(
        select(PushSubscription).where(
            PushSubscription.user_id == user.id,
            PushSubscription.endpoint == payload.endpoint,
        )
    )
    if sub:
        sub.is_active = False
        db.commit()
    return {"status": "ok"}
