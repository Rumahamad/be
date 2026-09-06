import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.enums import UserStatus
from app.models.mixins import TimestampMixin


class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Permission(Base):
    __tablename__ = "permissions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    module: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    scope: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    auth_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, index=True
    )
    member_code: Mapped[str] = mapped_column(String(40), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    mobile: Mapped[str | None] = mapped_column(String(30), unique=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), index=True
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, name="user_status"), default=UserStatus.ACTIVE
    )
    password_setup_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profile_picture_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class Group(Base, TimestampMixin):
    __tablename__ = "groups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str | None] = mapped_column(String(40), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class UserGroup(Base):
    __tablename__ = "user_groups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE")
    )
    added_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_group"),)


class UserPreference(Base, TimestampMixin):
    __tablename__ = "user_preferences"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    language_override: Mapped[str | None] = mapped_column(String(10))
    theme_override: Mapped[str | None] = mapped_column(String(50))


class DeletedUser(Base):
    __tablename__ = "deleted_users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    member_code: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(255))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    deleted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    deleted_at: Mapped[datetime] = mapped_column()
