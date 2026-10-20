from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.identity import Role, User
from app.services.auth_admin_service import AuthAdminService


class AdminBootstrapError(Exception):
    pass


@dataclass(frozen=True)
class AdminBootstrapInput:
    email: str
    password: str
    member_code: str
    first_name: str
    last_name: str | None
    mobile: str | None


class AdminBootstrapService:
    def __init__(self, auth_admin=None) -> None:
        self.auth_admin = auth_admin or AuthAdminService()

    def create_first_admin(self, db: Session, data: AdminBootstrapInput) -> User:
        existing_user_count = db.scalar(select(func.count()).select_from(User)) or 0
        if existing_user_count:
            raise AdminBootstrapError("Bootstrap is disabled because BNC already has users")

        admin_role = db.scalar(select(Role).where(Role.code == "ADMIN", Role.is_active.is_(True)))
        if not admin_role:
            raise AdminBootstrapError("ADMIN role is missing; run database migrations first")

        display_name = " ".join(filter(None, [data.first_name.strip(), data.last_name])).strip()
        auth_user = self.auth_admin.create_user(data.email.strip().lower(), data.password, display_name)
        user = User(
            auth_user_id=auth_user.id,
            member_code=data.member_code.strip().upper(),
            first_name=data.first_name.strip(),
            last_name=data.last_name.strip() if data.last_name else None,
            display_name=display_name,
            email=auth_user.email.lower(),
            mobile=data.mobile.strip() if data.mobile else None,
            role_id=admin_role.id,
        )
        try:
            db.add(user)
            db.commit()
        except Exception:
            db.rollback()
            self.auth_admin.delete_user(auth_user.id)
            raise
        db.refresh(user)
        return user
