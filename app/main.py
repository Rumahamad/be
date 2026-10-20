from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.administration import router as administration_router
from app.api.v1.announcements import router as announcements_router
from app.api.v1.audit import router as audit_router
from app.api.v1.backups import router as backups_router
from app.api.v1.auth import router as auth_router
from app.api.v1.expenses import router as expenses_router
from app.api.v1.fund import router as fund_router
from app.api.v1.me import router as me_router
from app.api.v1.members import router as members_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.payments import router as payments_router
from app.api.v1.payment_verification import router as payment_verification_router
from app.api.v1.preferences import router as preferences_router
from app.api.v1.push import router as push_router
from app.api.v1.reports import router as reports_router
from app.api.v1.settings import router as settings_router
from app.config.settings import get_settings
from app.config.auth_middleware import protect_auth

app = FastAPI(title="BNC API", version="0.1.0")
app.middleware("http")(protect_auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(payments_router, prefix="/api/v1")
app.include_router(administration_router, prefix="/api/v1")
app.include_router(fund_router, prefix="/api/v1")
app.include_router(expenses_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(announcements_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(members_router, prefix="/api/v1")
app.include_router(preferences_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(push_router, prefix="/api/v1")
app.include_router(backups_router, prefix="/api/v1")
app.include_router(payment_verification_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
