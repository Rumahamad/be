from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, require_permission, user_has_permission
from app.constants.permissions import (
    USER_BLOCK,
    USER_CREATE,
    USER_DELETE,
    USER_EDIT,
    USER_VIEW,
)
from app.db.session import get_db
from app.handlers.members import MemberHandler
from app.models.enums import UserStatus
from app.models.identity import User
from app.repositories.members import MemberRepository
from app.schemas.members import (
    CreateMemberInput,
    MemberListOutput,
    MemberOutput,
    UpdateMemberInput,
    UpdateMemberStatusInput,
)
from app.schemas.preferences import PreferencesOutput, UpdatePreferencesInput
from app.services.preference_service import PreferenceService
from app.services.profile_picture_service import ProfilePictureService

router = APIRouter(prefix="/members", tags=["members"])
handler = MemberHandler()
repository = MemberRepository()
preferences = PreferenceService()
profile_pictures = ProfilePictureService()


def require_self_or_edit(db: Session, actor: User, member_id: UUID) -> None:
    if actor.id != member_id and not user_has_permission(db, actor, USER_EDIT):
        raise HTTPException(status_code=403, detail="You cannot edit this profile picture")


def output(
    user: User,
    role_code: str,
    preference: PreferencesOutput,
) -> MemberOutput:
    return MemberOutput(
        id=user.id,
        member_code=user.member_code,
        first_name=user.first_name,
        last_name=user.last_name,
        display_name=user.display_name,
        email=user.email,
        mobile=user.mobile,
        role_code=role_code,
        status=user.status.value,
        language=preference.language,
        theme=preference.theme,
        profile_picture_url=(
            f"/api/v1/members/{user.id}/profile-picture"
            if user.profile_picture_file_id
            else None
        ),
    )


@router.get("", response_model=MemberListOutput)
def list_members(
    search: str | None = Query(default=None, max_length=160),
    member_status: UserStatus | None = Query(default=None, alias="status"),
    role_code: str | None = Query(default=None, max_length=40),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(USER_VIEW)),
) -> MemberListOutput:
    rows, total = repository.list(
        db,
        offset=offset,
        limit=limit,
        search=search,
        status=member_status.value if member_status else None,
        role_code=role_code,
    )
    resolved = preferences.get_many(db, [user.id for user, _ in rows])
    return MemberListOutput(
        items=[output(user, role, resolved[user.id]) for user, role in rows],
        total=total,
    )


@router.post("", response_model=MemberOutput, status_code=status.HTTP_201_CREATED)
def create_member(
    payload: CreateMemberInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_CREATE)),
) -> MemberOutput:
    user = handler.create(db, actor, payload)
    return output(user, payload.role_code, preferences.get(db, user))


@router.patch("/{member_id}/status", response_model=MemberOutput)
def update_member_status(
    member_id: UUID,
    payload: UpdateMemberStatusInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_BLOCK)),
) -> MemberOutput:
    user = handler.set_status(db, actor, member_id, UserStatus(payload.status))
    return output(user, repository.role_code(db, user.role_id), preferences.get(db, user))


@router.patch("/{member_id}", response_model=MemberOutput)
def update_member(
    member_id: UUID,
    payload: UpdateMemberInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_EDIT)),
) -> MemberOutput:
    user = handler.update(db, actor, member_id, payload)
    return output(user, repository.role_code(db, user.role_id), preferences.get(db, user))


@router.patch("/{member_id}/preferences", response_model=PreferencesOutput)
def update_member_preferences(
    member_id: UUID,
    payload: UpdatePreferencesInput,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_EDIT)),
) -> PreferencesOutput:
    return handler.update_preferences(db, actor, member_id, payload)


@router.post("/{member_id}/password-reset", status_code=status.HTTP_204_NO_CONTENT)
def send_member_password_reset(
    member_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_EDIT)),
) -> None:
    handler.send_password_reset(db, actor, member_id)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(
    member_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permission(USER_DELETE)),
) -> None:
    handler.delete(db, actor, member_id)


@router.put("/{member_id}/profile-picture")
async def upload_profile_picture(
    member_id: UUID,
    request: Request,
    x_file_name: str = Header(default="profile-picture", max_length=255),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> dict[str, str]:
    require_self_or_edit(db, actor, member_id)
    content = await request.body()
    url = profile_pictures.upload(
        db,
        actor,
        member_id,
        filename=x_file_name,
        mime_type=request.headers.get("content-type", "application/octet-stream"),
        content=content,
    )
    return {"profile_picture_url": url}


@router.get("/{member_id}/profile-picture")
def download_profile_picture(
    member_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
) -> Response:
    content, mime_type = profile_pictures.download(db, member_id)
    return Response(content=content, media_type=mime_type, headers={"Cache-Control": "private, max-age=300"})


@router.delete("/{member_id}/profile-picture", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile_picture(
    member_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> None:
    require_self_or_edit(db, actor, member_id)
    profile_pictures.delete(db, member_id)
