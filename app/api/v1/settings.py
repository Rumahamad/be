from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission
from app.constants.permissions import SETTINGS_EDIT
from app.db.session import get_db
from app.models.identity import User
from app.models.settings import OrganizationSetting
from app.schemas.dashboard import PaymentSettingsOutput
from app.schemas.settings import (
    OrganizationSettingsOutput,
    UpdateOrganizationSettingsInput,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])
QR_PATH = Path(__file__).resolve().parents[3] / "assets" / "payment-qr.jpeg"
service = SettingsService()


@router.get("/payment", response_model=PaymentSettingsOutput)
def payment_settings(
    db: Session = Depends(get_db), _: User = Depends(current_user)
) -> PaymentSettingsOutput:
    setting = db.scalar(select(OrganizationSetting).limit(1))
    if not setting:
        raise HTTPException(status_code=503, detail="Organization settings are not configured")
    return PaymentSettingsOutput(
        organization_name=setting.organization_name,
        short_name=setting.short_name,
        upi_id=setting.payment_upi_id,
        mobile=setting.payment_mobile,
        qr_url=setting.payment_qr_path,
        whatsapp_group_url=setting.whatsapp_group_url,
        expense_visibility=setting.expense_visibility,
        expense_visible_fields=setting.expense_visible_fields or [],
    )


@router.get("/payment/qr", response_class=FileResponse)
def payment_qr(_: User = Depends(current_user)) -> FileResponse:
    if not QR_PATH.is_file():
        raise HTTPException(status_code=404, detail="Payment QR is not configured")
    return FileResponse(QR_PATH, media_type="image/jpeg", filename="bnc-payment-qr.jpeg")


@router.get("/organization", response_model=OrganizationSettingsOutput)
def organization_settings(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> OrganizationSettingsOutput:
    return service.get(db)


@router.patch("/organization", response_model=OrganizationSettingsOutput)
def update_organization_settings(
    payload: UpdateOrganizationSettingsInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> OrganizationSettingsOutput:
    return service.update(db, actor, payload)
