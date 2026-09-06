from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_permission
from app.constants.permissions import SETTINGS_EDIT, USER_VIEW
from app.db.session import get_db
from app.handlers.administration import AdministrationHandler
from app.models.identity import User
from app.schemas.administration import (
    CreateGroupInput,
    CreateRoleInput,
    GroupOutput,
    RoleOutput,
    SetGroupMembersInput,
    UpdateGroupInput,
    UpdateRoleInput,
    UpdateRolePermissionsInput,
)

router = APIRouter(tags=["administration"])
handler = AdministrationHandler()


@router.get("/groups", response_model=list[GroupOutput])
def list_groups(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(USER_VIEW)),
) -> list[GroupOutput]:
    return handler.groups(db)


@router.post("/groups", response_model=GroupOutput, status_code=status.HTTP_201_CREATED)
def create_group(
    payload: CreateGroupInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GroupOutput:
    return handler.create_group(db, actor, payload)


@router.patch("/groups/{group_id}", response_model=GroupOutput)
def update_group(
    group_id: UUID,
    payload: UpdateGroupInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GroupOutput:
    return handler.update_group(db, actor, group_id, payload)


@router.put("/groups/{group_id}/members", response_model=GroupOutput)
def set_group_members(
    group_id: UUID,
    payload: SetGroupMembersInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> GroupOutput:
    return handler.set_members(db, actor, group_id, payload.member_ids)


@router.get("/roles", response_model=list[RoleOutput])
def list_roles(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(SETTINGS_EDIT)),
) -> list[RoleOutput]:
    return handler.roles(db)


@router.post("/roles", response_model=RoleOutput, status_code=status.HTTP_201_CREATED)
def create_role(
    payload: CreateRoleInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> RoleOutput:
    return handler.create_role(db, actor, payload)


@router.patch("/roles/{role_id}", response_model=RoleOutput)
def update_role(
    role_id: UUID,
    payload: UpdateRoleInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> RoleOutput:
    return handler.update_role(db, actor, role_id, payload)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> None:
    handler.delete_role(db, actor, role_id)


@router.put("/roles/{role_id}/permissions", response_model=RoleOutput)
def set_role_permissions(
    role_id: UUID,
    payload: UpdateRolePermissionsInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(SETTINGS_EDIT)),
) -> RoleOutput:
    handler.service.set_role_permissions(db, actor, role_id, payload.permission_codes)
    db.commit()
    return next(role for role in handler.roles(db) if role.id == role_id)
