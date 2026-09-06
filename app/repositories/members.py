from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.models.identity import Role, User


class MemberRepository:
    def list(
        self,
        db: Session,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
        status: str | None = None,
        role_code: str | None = None,
    ) -> tuple[list[tuple[User, str]], int]:
        filters = [User.status != "DELETED"]
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    User.display_name.ilike(term),
                    User.email.ilike(term),
                    User.mobile.ilike(term),
                    User.member_code.ilike(term),
                )
            )
        if status:
            filters.append(User.status == status)
        if role_code:
            filters.append(Role.code == role_code)
        statement = select(User, Role.code).join(Role, Role.id == User.role_id).where(*filters)
        total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
        rows = db.execute(
            statement
            .order_by(User.display_name, User.id)
            .offset(offset)
            .limit(limit)
        ).all()
        return list(rows), total

    def active_role(self, db: Session, code: str) -> Role | None:
        return db.scalar(select(Role).where(Role.code == code, Role.is_active.is_(True)))

    def role_code(self, db: Session, role_id: UUID) -> str:
        return db.scalar(select(Role.code).where(Role.id == role_id)) or ""

    def next_member_code(self, db: Session) -> str:
        number = db.scalar(select(text("nextval('bnc_member_code_seq')")))
        return f"BNC-{number:03d}"
