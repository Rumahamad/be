from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identity import Group, Permission, Role, RolePermission, User, UserGroup
from app.repositories.administration import AdministrationRepository
from app.schemas.administration import (
    CreateGroupInput,
    CreateRoleInput,
    UpdateGroupInput,
    UpdateRoleInput,
)
from app.services.audit_service import AuditService


class AdministrationService:
    def __init__(self) -> None:
        self.repository = AdministrationRepository()
        self.audit = AuditService()

    def create_group(
        self, db: Session, actor: User, payload: CreateGroupInput
    ) -> Group:
        group = Group(
            name=payload.name,
            code=payload.code,
            description=payload.description,
            created_by=actor.id,
        )
        db.add(group)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Group code already exists") from exc
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="group.created",
            entity_type="group",
            entity_id=group.id,
            after_data={"name": group.name, "code": group.code},
        )
        return group

    def update_group(
        self, db: Session, actor: User, group_id: UUID, payload: UpdateGroupInput
    ) -> Group:
        group = self.repository.group_by_id_for_update(db, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        before = {"name": group.name, "code": group.code, "is_active": group.is_active}
        for field, value in payload.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                value = value.strip()
            if field == "code" and value:
                value = value.upper().replace(" ", "-")
            setattr(group, field, value)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Group code already exists") from exc
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="group.updated",
            entity_type="group",
            entity_id=group.id,
            before_data=before,
            after_data={"name": group.name, "code": group.code, "is_active": group.is_active},
        )
        return group

    def set_group_members(
        self, db: Session, actor: User, group_id: UUID, member_ids: list[UUID]
    ) -> Group:
        group = self.repository.group_by_id_for_update(db, group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if not group.is_active:
            raise HTTPException(
                status_code=409,
                detail="Activate this group before changing its members",
            )
        requested = set(member_ids)
        if len(requested) != len(member_ids):
            raise HTTPException(status_code=422, detail="Duplicate members are not allowed")
        if self.repository.active_user_count(db, requested) != len(requested):
            raise HTTPException(status_code=422, detail="One or more members are unavailable")
        existing = set(
            db.scalars(select(UserGroup.user_id).where(UserGroup.group_id == group.id)).all()
        )
        db.execute(delete(UserGroup).where(UserGroup.group_id == group.id))
        db.add_all(
            UserGroup(user_id=user_id, group_id=group.id, added_by=actor.id)
            for user_id in requested
        )
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="group.members_replaced",
            entity_type="group",
            entity_id=group.id,
            before_data={"member_ids": sorted(map(str, existing))},
            after_data={"member_ids": sorted(map(str, requested))},
        )
        return group

    def set_role_permissions(
        self, db: Session, actor: User, role_id: UUID, permission_codes: list[str]
    ) -> Role:
        role = db.scalar(select(Role).where(Role.id == role_id).with_for_update())
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.code == "ADMIN":
            raise HTTPException(status_code=409, detail="Protected role permissions cannot be changed")
        requested = set(permission_codes)
        permissions = list(
            db.scalars(select(Permission).where(Permission.code.in_(requested))).all()
        ) if requested else []
        if len(permissions) != len(requested):
            raise HTTPException(status_code=422, detail="One or more permissions are unknown")
        previous = set(
            db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id, RolePermission.allowed.is_(True))
            ).all()
        )
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        db.add_all(
            RolePermission(role_id=role.id, permission_id=permission.id, allowed=True)
            for permission in permissions
        )
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="role.permissions_replaced",
            entity_type="role",
            entity_id=role.id,
            before_data={"permissions": sorted(previous)},
            after_data={"permissions": sorted(requested)},
        )
        return role

    def create_role(self, db: Session, actor: User, payload: CreateRoleInput) -> Role:
        role = Role(
            code=payload.code,
            name=payload.name,
            description=payload.description,
            is_system=False,
            is_protected=False,
            is_active=True,
        )
        db.add(role)
        try:
            db.flush()
        except IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Role code already exists") from exc
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="role.created",
            entity_type="role",
            entity_id=role.id,
            after_data={"code": role.code, "name": role.name},
        )
        return role

    def update_role(
        self,
        db: Session,
        actor: User,
        role_id: UUID,
        payload: UpdateRoleInput,
    ) -> Role:
        role = db.scalar(select(Role).where(Role.id == role_id).with_for_update())
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.is_protected:
            raise HTTPException(status_code=409, detail="Protected roles cannot be edited")
        before = {
            "name": role.name,
            "description": role.description,
            "is_active": role.is_active,
        }
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(role, field, value.strip() if isinstance(value, str) else value)
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="role.updated",
            entity_type="role",
            entity_id=role.id,
            before_data=before,
            after_data={
                "name": role.name,
                "description": role.description,
                "is_active": role.is_active,
            },
        )
        return role

    def delete_role(self, db: Session, actor: User, role_id: UUID) -> None:
        role = db.scalar(select(Role).where(Role.id == role_id).with_for_update())
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role.is_protected:
            raise HTTPException(status_code=409, detail="Protected roles cannot be deleted")
        assigned = db.scalar(
            select(User.id).where(User.role_id == role.id, User.status != "DELETED").limit(1)
        )
        if assigned:
            raise HTTPException(
                status_code=409,
                detail="Move all users to another role before deleting this role",
            )
        self.audit.record(
            db,
            actor_user_id=actor.id,
            action="role.deleted",
            entity_type="role",
            entity_id=role.id,
            before_data={"code": role.code, "name": role.name},
        )
        db.delete(role)
