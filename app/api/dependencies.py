from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.security import verify_access_token
from app.config.settings import get_settings
from app.db.session import get_db
from app.models.enums import UserStatus
from app.models.identity import Permission, RolePermission, User

bearer = HTTPBearer(auto_error=False)


def access_token_user(access_token: str, db: Session) -> User:
    claims = verify_access_token(access_token)
    try:
        auth_user_id = UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token subject") from exc
    user = db.scalar(select(User).where(User.auth_user_id == auth_user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is not approved for BNC"
        )
    if user.status != UserStatus.ACTIVE:
        detail = (
            "Membership is pending Admin approval"
            if user.status == UserStatus.INACTIVE
            else "BNC account is blocked" if user.status == UserStatus.BLOCKED
            else "BNC account is unavailable"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return user


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_bnc_user_id: UUID | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    if settings.auth_bypass_enabled:
        if settings.environment == "production":
            raise RuntimeError("AUTH_BYPASS_ENABLED cannot be used in production")
        if not x_bnc_user_id:
            raise HTTPException(status_code=401, detail="Development user header required")
        user = db.get(User, x_bnc_user_id)
    else:
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Authentication required")
        return access_token_user(credentials.credentials, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User is not approved for BNC"
        )
    if user.status != UserStatus.ACTIVE:
        detail = (
            "Membership is pending Admin approval"
            if user.status == UserStatus.INACTIVE
            else "BNC account is blocked" if user.status == UserStatus.BLOCKED
            else "BNC account is unavailable"
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
    return user


def user_has_permission(db: Session, user: User, permission_code: str) -> bool:
    allowed = db.scalar(
        select(RolePermission.allowed)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id == user.role_id, Permission.code == permission_code)
    )
    return bool(allowed)


def require_permission(permission_code: str) -> Callable:
    def dependency(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
        if not user_has_permission(db, user, permission_code):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_code}")
        return user

    return dependency
