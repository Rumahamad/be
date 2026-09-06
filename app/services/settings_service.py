from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.settings import OrganizationSetting
from app.schemas.settings import (
    OrganizationSettingsOutput,
    UpdateOrganizationSettingsInput,
)
from app.services.audit_service import AuditService


class SettingsService:
    def __init__(self) -> None:
        self.audit = AuditService()

    @staticmethod
    def get_model(db: Session) -> OrganizationSetting:
        setting = db.scalar(select(OrganizationSetting).limit(1))
        if not setting:
            raise HTTPException(status_code=503, detail="Organization settings are not configured")
        return setting

    def get(self, db: Session) -> OrganizationSettingsOutput:
        return OrganizationSettingsOutput.model_validate(
            self.get_model(db), from_attributes=True
        )

    def update(
        self, db: Session, actor: User, payload: UpdateOrganizationSettingsInput
    ) -> OrganizationSettingsOutput:
        setting = self.get_model(db)
        changes = payload.model_dump(exclude_unset=True)
        before = {key: getattr(setting, key) for key in changes}
        for key, value in changes.items():
            if isinstance(value, str):
                value = value.strip() or None
            setattr(setting, key, value)
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="settings.updated",
            entity_type="organization_settings",
            entity_id=setting.id,
            before_data=before,
            after_data={key: getattr(setting, key) for key in changes},
        )
        db.commit()
        return self.get(db)
