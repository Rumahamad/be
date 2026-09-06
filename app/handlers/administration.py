from uuid import UUID

from sqlalchemy.orm import Session

from app.models.identity import Group, User
from app.schemas.administration import (
    CreateGroupInput,
    CreateRoleInput,
    GroupOutput,
    PermissionOutput,
    RoleOutput,
    UpdateGroupInput,
    UpdateRoleInput,
)
from app.services.administration_service import AdministrationService


class AdministrationHandler:
    def __init__(self) -> None:
        self.service = AdministrationService()

    def groups(self, db: Session) -> list[GroupOutput]:
        groups = self.service.repository.list_groups(db)
        memberships = self.service.repository.group_member_ids(
            db, [group.id for group in groups]
        )
        return [self.group_output(group, memberships[group.id]) for group in groups]

    @staticmethod
    def group_output(group: Group, member_ids: list[UUID]) -> GroupOutput:
        return GroupOutput(
            id=group.id,
            name=group.name,
            code=group.code,
            description=group.description,
            is_active=group.is_active,
            member_ids=member_ids,
        )

    def roles(self, db: Session) -> list[RoleOutput]:
        roles = self.service.repository.list_roles(db)
        permissions = self.service.repository.permissions(db)
        allowed = self.service.repository.role_permissions(db)
        user_counts = self.service.repository.role_user_counts(db)
        return [
            RoleOutput(
                id=role.id,
                code=role.code,
                name=role.name,
                description=role.description,
                is_protected=role.is_protected,
                is_active=role.is_active,
                user_count=user_counts.get(role.id, 0),
                permissions=[
                    PermissionOutput(
                        code=permission.code,
                        module=permission.module,
                        action=permission.action,
                        scope=permission.scope,
                        allowed=permission.id in allowed.get(role.id, set()),
                    )
                    for permission in permissions
                ],
            )
            for role in roles
        ]

    def create_role(
        self, db: Session, actor: User, payload: CreateRoleInput
    ) -> RoleOutput:
        role = self.service.create_role(db, actor, payload)
        db.commit()
        return next(item for item in self.roles(db) if item.id == role.id)

    def update_role(
        self, db: Session, actor: User, role_id: UUID, payload: UpdateRoleInput
    ) -> RoleOutput:
        role = self.service.update_role(db, actor, role_id, payload)
        db.commit()
        return next(item for item in self.roles(db) if item.id == role.id)

    def delete_role(self, db: Session, actor: User, role_id: UUID) -> None:
        self.service.delete_role(db, actor, role_id)
        db.commit()

    def create_group(
        self, db: Session, actor: User, payload: CreateGroupInput
    ) -> GroupOutput:
        group = self.service.create_group(db, actor, payload)
        db.commit()
        return self.group_output(group, [])

    def update_group(
        self, db: Session, actor: User, group_id: UUID, payload: UpdateGroupInput
    ) -> GroupOutput:
        group = self.service.update_group(db, actor, group_id, payload)
        db.commit()
        members = self.service.repository.group_member_ids(db, [group.id])[group.id]
        return self.group_output(group, members)

    def set_members(
        self, db: Session, actor: User, group_id: UUID, member_ids: list[UUID]
    ) -> GroupOutput:
        group = self.service.set_group_members(db, actor, group_id, member_ids)
        db.commit()
        return self.group_output(group, member_ids)
