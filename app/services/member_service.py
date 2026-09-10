from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.models.enums import UserStatus
from app.models.communications import NotificationOutbox
from app.models.identity import DeletedUser, User, UserGroup, UserPreference
from app.models.push_subscriptions import PushSubscription
from app.repositories.members import MemberRepository
from app.schemas.members import CreateMemberInput, UpdateMemberInput
from app.services.audit_service import AuditService
from app.services.supabase_admin_service import SupabaseAdminService


class MemberConflictError(Exception):
    pass


class MemberService:
    def __init__(self) -> None:
        self.members = MemberRepository()
        self.auth_admin = SupabaseAdminService()
        self.audit = AuditService()

    def create(self, db: Session, actor: User, payload: CreateMemberInput) -> User:
        role = self.members.active_role(db, payload.role_code)
        if not role or role.code == "ADMIN":
            raise ValueError("Selected role is unavailable")
        creator_role = self.members.role_code(db, actor.role_id)
        if creator_role == "MEMBER":
            raise PermissionError("Members cannot create user accounts")
        if creator_role != "ADMIN" and payload.role_code != "MEMBER":
            raise ValueError("Only Admin can assign the Committee role")
        display_name = " ".join(filter(None, [payload.first_name.strip(), payload.last_name])).strip()
        email = payload.email.strip().lower()
        auth_user = None
        if creator_role == "ADMIN":
            auth_user = self.auth_admin.invite_user(
                email,
                display_name,
                f"{get_settings().frontend_url.rstrip('/')}/auth/set-password",
            )
        user = User(
            auth_user_id=auth_user.id if auth_user else None,
            member_code=self.members.next_member_code(db),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip() if payload.last_name else None,
            display_name=display_name,
            email=auth_user.email.lower() if auth_user else email,
            mobile=payload.mobile.strip() if payload.mobile else None,
            role_id=role.id,
            status=UserStatus.ACTIVE if creator_role == "ADMIN" else UserStatus.INACTIVE,
            password_setup_required=True,
            created_by=actor.id,
        )
        try:
            db.add(user)
            db.flush()
            self.audit.record(
                db,
                actor_user_id=actor.id,
                action="user.created",
                entity_type="user",
                entity_id=user.id,
                after_data={
                    "member_code": user.member_code,
                    "role": role.code,
                    "status": user.status.value,
                    "requires_admin_approval": user.status == UserStatus.INACTIVE,
                },
            )
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            if auth_user:
                self.auth_admin.delete_user(auth_user.id)
            raise MemberConflictError("Email, mobile, or member identity already exists") from exc
        except Exception:
            db.rollback()
            if auth_user:
                self.auth_admin.delete_user(auth_user.id)
            raise
        db.refresh(user)
        return user

    def set_status(self, db: Session, actor: User, member_id: UUID, status: UserStatus) -> User:
        user = db.get(User, member_id)
        if not user or user.status == UserStatus.DELETED:
            raise LookupError("Member not found")
        if user.id == actor.id and status != UserStatus.ACTIVE:
            raise MemberConflictError("You cannot disable your own account")
        previous = user.status
        invited_auth_user = None
        if status == UserStatus.ACTIVE and user.auth_user_id is None:
            invited_auth_user = self.auth_admin.invite_user(
                user.email,
                user.display_name,
                f"{get_settings().frontend_url.rstrip('/')}/auth/set-password",
            )
            user.auth_user_id = invited_auth_user.id
            user.password_setup_required = True
        user.status = status
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.status_changed",
            entity_type="user",
            entity_id=user.id,
            before_data={"status": previous.value},
            after_data={"status": status.value},
        )
        try:
            db.commit()
        except Exception:
            db.rollback()
            if invited_auth_user:
                self.auth_admin.delete_user(invited_auth_user.id)
            raise
        db.refresh(user)
        return user

    def update(
        self, db: Session, actor: User, member_id: UUID, payload: UpdateMemberInput
    ) -> User:
        user = db.get(User, member_id)
        if not user or user.status == UserStatus.DELETED:
            raise LookupError("Member not found")
        changes = payload.model_dump(exclude_unset=True)
        before = {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "mobile": user.mobile,
            "role_id": str(user.role_id),
        }
        if "role_code" in changes:
            actor_role = self.members.role_code(db, actor.role_id)
            if actor_role != "ADMIN":
                raise PermissionError("Only Admin can change a user's role")
            if user.id == actor.id:
                raise MemberConflictError("You cannot change your own role")
            role = self.members.active_role(db, changes.pop("role_code"))
            if not role or role.code == "ADMIN":
                raise ValueError("Selected role is unavailable")
            user.role_id = role.id
        for field in ("first_name", "last_name", "mobile"):
            if field in changes:
                value = changes[field]
                setattr(user, field, value.strip() if value else None)
        if not user.first_name:
            raise ValueError("First name is required")
        user.display_name = " ".join(filter(None, [user.first_name, user.last_name]))
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.updated",
            entity_type="user",
            entity_id=user.id,
            before_data=before,
            after_data={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "mobile": user.mobile,
                "role_id": str(user.role_id),
            },
        )
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise MemberConflictError("Mobile number already exists") from exc
        db.refresh(user)
        return user

    def send_password_reset(self, db: Session, actor: User, member_id: UUID) -> None:
        user = db.get(User, member_id)
        if not user or user.status == UserStatus.DELETED:
            raise LookupError("Member not found")
        if user.auth_user_id is None:
            raise MemberConflictError("Approve this member before sending a password reset")
        self.auth_admin.send_password_reset(
            user.email,
            f"{get_settings().frontend_url.rstrip('/')}/auth/reset-password",
        )
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.password_reset_requested",
            entity_type="user",
            entity_id=user.id,
        )
        db.commit()

    def delete(self, db: Session, actor: User, member_id: UUID) -> None:
        user = db.get(User, member_id)
        if not user:
            raise LookupError("Member not found")
        if user.id == actor.id:
            raise MemberConflictError("You cannot delete your own account")
        if user.status == UserStatus.DELETED:
            self._cleanup_deleted_auth(db, user)
            return
        role_code = self.members.role_code(db, user.role_id)
        if role_code == "ADMIN":
            raise MemberConflictError("Administrator accounts cannot be deleted")

        preference = db.get(UserPreference, user.id)
        group_ids = list(
            db.scalars(select(UserGroup.group_id).where(UserGroup.user_id == user.id)).all()
        )
        auth_user_id = user.auth_user_id
        db.add(
            DeletedUser(
                id=uuid4(),
                original_user_id=user.id,
                member_code=user.member_code,
                display_name=user.display_name,
                email=user.email,
                deleted_by=actor.id,
                deleted_at=datetime.now(UTC),
                snapshot={
                    "auth_user_id": str(auth_user_id) if auth_user_id else None,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "display_name": user.display_name,
                    "email": user.email,
                    "mobile": user.mobile,
                    "role_code": role_code,
                    "status": user.status.value,
                    "password_setup_required": user.password_setup_required,
                    "profile_picture_file_id": (
                        str(user.profile_picture_file_id) if user.profile_picture_file_id else None
                    ),
                    "created_by": str(user.created_by) if user.created_by else None,
                    "created_at": user.created_at.isoformat(),
                    "updated_at": user.updated_at.isoformat(),
                    "group_ids": [str(group_id) for group_id in group_ids],
                    "preferences": {
                        "language_override": preference.language_override if preference else None,
                        "theme_override": preference.theme_override if preference else None,
                    },
                },
            )
        )
        db.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
        if preference:
            db.delete(preference)
        db.execute(
            update(PushSubscription)
            .where(PushSubscription.user_id == user.id)
            .values(is_active=False)
        )
        db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.recipient_user_id == user.id,
                NotificationOutbox.status.in_(("PENDING", "FAILED")),
            )
            .values(status="CANCELLED", processed_at=datetime.now(UTC))
        )
        user.first_name = "Deleted"
        user.last_name = None
        user.display_name = f"Deleted member ({user.member_code})"
        user.email = f"deleted-{user.id}@archive.invalid"
        user.mobile = None
        user.status = UserStatus.DELETED
        user.password_setup_required = False
        user.profile_picture_file_id = None
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="user.deleted",
            entity_type="user",
            entity_id=user.id,
            before_data={"member_code": user.member_code, "role": role_code},
            after_data={"archived": True},
        )
        db.commit()
        self._cleanup_deleted_auth(db, user, auth_user_id)

    def _cleanup_deleted_auth(
        self,
        db: Session,
        user: User,
        auth_user_id: UUID | None = None,
    ) -> None:
        target = auth_user_id or user.auth_user_id
        if not target:
            return
        self.auth_admin.delete_user(target)
        user.auth_user_id = None
        db.commit()
