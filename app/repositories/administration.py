from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.identity import Group, Permission, Role, RolePermission, User, UserGroup


class AdministrationRepository:
    def list_groups(self, db: Session) -> list[Group]:
        return list(db.scalars(select(Group).order_by(Group.name, Group.id)).all())

    def group_member_ids(self, db: Session, group_ids: list[UUID]) -> dict[UUID, list[UUID]]:
        result = {group_id: [] for group_id in group_ids}
        rows = db.execute(
            select(UserGroup.group_id, UserGroup.user_id)
            .where(UserGroup.group_id.in_(group_ids))
            .order_by(UserGroup.group_id, UserGroup.user_id)
        ).all()
        for group_id, user_id in rows:
            result[group_id].append(user_id)
        return result

    def group_by_id_for_update(self, db: Session, group_id: UUID) -> Group | None:
        return db.scalar(select(Group).where(Group.id == group_id).with_for_update())

    def list_roles(self, db: Session) -> list[Role]:
        return list(db.scalars(select(Role).order_by(Role.code)).all())

    def permissions(self, db: Session) -> list[Permission]:
        return list(db.scalars(select(Permission).order_by(Permission.code)).all())

    def role_permissions(self, db: Session) -> dict[UUID, set[UUID]]:
        result: dict[UUID, set[UUID]] = {}
        rows = db.execute(
            select(RolePermission.role_id, RolePermission.permission_id).where(
                RolePermission.allowed.is_(True)
            )
        ).all()
        for role_id, permission_id in rows:
            result.setdefault(role_id, set()).add(permission_id)
        return result

    def role_user_counts(self, db: Session) -> dict[UUID, int]:
        return dict(
            db.execute(
                select(User.role_id, func.count(User.id))
                .where(User.status != "DELETED")
                .group_by(User.role_id)
            ).all()
        )

    def active_user_count(self, db: Session, member_ids: set[UUID]) -> int:
        if not member_ids:
            return 0
        from app.models.enums import UserStatus
        from app.models.identity import User

        return int(
            db.scalar(
                select(func.count(User.id)).where(
                    User.id.in_(member_ids), User.status == UserStatus.ACTIVE
                )
            )
            or 0
        )
