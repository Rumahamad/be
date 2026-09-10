from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import UserStatus
from app.models.identity import User
from app.schemas.members import CreateMemberInput, UpdateMemberInput
from app.schemas.preferences import PreferencesOutput, UpdatePreferencesInput
from app.services.member_service import MemberConflictError, MemberService
from app.services.preference_service import PreferenceService
from app.services.supabase_admin_service import SupabaseAdminError


class MemberHandler:
    def __init__(self) -> None:
        self.service = MemberService()
        self.preferences = PreferenceService()

    def create(self, db: Session, actor: User, payload: CreateMemberInput) -> User:
        try:
            return self.service.create(db, actor, payload)
        except MemberConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SupabaseAdminError as exc:
            if exc.status_code == 409 or exc.error_code in {
                "email_exists",
                "user_already_exists",
            }:
                response_status = 409
            elif exc.status_code in {400, 422}:
                response_status = 400
            else:
                response_status = 502
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc

    def set_status(
        self, db: Session, actor: User, member_id: UUID, status: UserStatus
    ) -> User:
        try:
            return self.service.set_status(db, actor, member_id, status)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MemberConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SupabaseAdminError as exc:
            response_status = (
                409
                if exc.status_code == 409
                or exc.error_code in {"email_exists", "user_already_exists"}
                else 502
            )
            raise HTTPException(status_code=response_status, detail=str(exc)) from exc

    def update(
        self, db: Session, actor: User, member_id: UUID, payload: UpdateMemberInput
    ) -> User:
        try:
            return self.service.update(db, actor, member_id, payload)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MemberConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def send_password_reset(self, db: Session, actor: User, member_id: UUID) -> None:
        try:
            self.service.send_password_reset(db, actor, member_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MemberConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SupabaseAdminError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def delete(self, db: Session, actor: User, member_id: UUID) -> None:
        try:
            self.service.delete(db, actor, member_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MemberConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SupabaseAdminError as exc:
            raise HTTPException(
                status_code=502,
                detail="User was archived, but Supabase Auth cleanup must be retried",
            ) from exc

    def update_preferences(
        self,
        db: Session,
        actor: User,
        member_id: UUID,
        payload: UpdatePreferencesInput,
    ) -> PreferencesOutput:
        member = db.get(User, member_id)
        if not member or member.status == UserStatus.DELETED:
            raise HTTPException(status_code=404, detail="Member not found")
        return self.preferences.update_for_user(
            db,
            actor=actor,
            user=member,
            payload=payload,
        )
