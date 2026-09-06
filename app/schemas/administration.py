from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CreateGroupInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str | None = Field(default=None, min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "code", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.upper().replace(" ", "-") if value else value


class UpdateGroupInput(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    code: str | None = Field(default=None, min_length=2, max_length=40)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class SetGroupMembersInput(BaseModel):
    member_ids: list[UUID] = Field(max_length=100)


class GroupOutput(BaseModel):
    id: UUID
    name: str
    code: str | None
    description: str | None
    is_active: bool
    member_ids: list[UUID]


class PermissionOutput(BaseModel):
    code: str
    module: str
    action: str
    scope: str
    allowed: bool


class RoleOutput(BaseModel):
    id: UUID
    code: str
    name: str
    description: str | None
    is_protected: bool
    is_active: bool
    user_count: int
    permissions: list[PermissionOutput]


class UpdateRolePermissionsInput(BaseModel):
    permission_codes: list[str] = Field(max_length=100)


class CreateRoleInput(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9 _-]*$")
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "_").replace("-", "_")

    @field_validator("name", "description")
    @classmethod
    def strip_role_text(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class UpdateRoleInput(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
