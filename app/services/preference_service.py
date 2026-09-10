from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User, UserPreference
from app.models.enums import UserStatus
from app.models.settings import OrganizationSetting
from app.schemas.preferences import PreferencesOutput, UpdatePreferencesInput
from app.services.audit_service import AuditService


class PreferenceService:
    def __init__(self) -> None:
        self.audit = AuditService()

    def get(self, db: Session, user: User) -> PreferencesOutput:
        setting = db.scalar(select(OrganizationSetting).limit(1))
        preference = db.get(UserPreference, user.id)
        language = (preference.language_override if preference else None) or (setting.default_language if setting else "en")
        theme = (preference.theme_override if preference else None) or (setting.default_theme if setting else "bnc-green")
        return PreferencesOutput(language=language, theme=theme, is_rtl=language == "ur")

    def update(self, db: Session, user: User, payload: UpdatePreferencesInput) -> PreferencesOutput:
        return self.update_for_user(db, actor=user, user=user, payload=payload)

    def update_for_user(
        self,
        db: Session,
        *,
        actor: User,
        user: User,
        payload: UpdatePreferencesInput,
    ) -> PreferencesOutput:
        preference = db.get(UserPreference, user.id)
        if not preference:
            preference = UserPreference(user_id=user.id)
            db.add(preference)
        before = {
            "language": preference.language_override,
            "theme": preference.theme_override,
        }
        if payload.language is not None:
            preference.language_override = payload.language
        if payload.theme is not None:
            preference.theme_override = payload.theme
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.preferences_updated",
            entity_type="user",
            entity_id=user.id,
            before_data=before,
            after_data={
                "language": preference.language_override,
                "theme": preference.theme_override,
            },
        )
        db.commit()
        return self.get(db, user)

    def get_many(self, db: Session, user_ids: list[UUID]) -> dict[UUID, PreferencesOutput]:
        if not user_ids:
            return {}
        setting = db.scalar(select(OrganizationSetting).limit(1))
        default_language = setting.default_language if setting else "en"
        default_theme = setting.default_theme if setting else "bnc-green"
        stored = {
            item.user_id: item
            for item in db.scalars(
                select(UserPreference).where(UserPreference.user_id.in_(user_ids))
            ).all()
        }
        result: dict[UUID, PreferencesOutput] = {}
        for user_id in user_ids:
            preference = stored.get(user_id)
            language = (preference.language_override if preference else None) or default_language
            theme = (preference.theme_override if preference else None) or default_theme
            result[user_id] = PreferencesOutput(
                language=language,
                theme=theme,
                is_rtl=language == "ur",
            )
        return result

    def update_for_all(
        self,
        db: Session,
        *,
        actor: User,
        payload: UpdatePreferencesInput,
    ) -> PreferencesOutput:
        setting = db.scalar(select(OrganizationSetting).limit(1))
        before = {
            "default_language": setting.default_language if setting else None,
            "default_theme": setting.default_theme if setting else None,
        }
        if setting:
            if payload.language is not None:
                setting.default_language = payload.language
            if payload.theme is not None:
                setting.default_theme = payload.theme

        users = db.scalars(select(User).where(User.status != UserStatus.DELETED)).all()
        stored = {
            item.user_id: item
            for item in db.scalars(select(UserPreference)).all()
        }
        for user in users:
            preference = stored.get(user.id)
            if not preference:
                preference = UserPreference(user_id=user.id)
                db.add(preference)
            if payload.language is not None:
                preference.language_override = payload.language
            if payload.theme is not None:
                preference.theme_override = payload.theme

        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.preferences_bulk_updated",
            entity_type="organization",
            entity_id=actor.id,
            before_data=before,
            after_data={
                "language": payload.language,
                "theme": payload.theme,
                "updated_users": len(users),
            },
        )
        db.commit()
        return self.get(db, actor)
