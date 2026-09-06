from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission
from app.constants.permissions import SETTINGS_EDIT
from app.db.session import get_db
from app.models.identity import Role, User
from app.schemas.preferences import PreferencesOutput, UpdatePreferencesInput
from app.services.preference_service import PreferenceService

router = APIRouter(tags=["preferences"])
service = PreferenceService()


@router.get("/me/preferences", response_model=PreferencesOutput)
def get_preferences(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> PreferencesOutput:
    return service.get(db, user)


@router.patch("/me/preferences", response_model=PreferencesOutput)
def update_preferences(
    payload: UpdatePreferencesInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> PreferencesOutput:
    return service.update(db, user, payload)


@router.patch("/preferences/all", response_model=PreferencesOutput)
def update_preferences_for_all(
    payload: UpdatePreferencesInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> PreferencesOutput:
    role_code = db.scalar(select(Role.code).where(Role.id == actor.role_id))
    if role_code != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin access required")
    return service.update_for_all(db, actor=actor, payload=payload)
