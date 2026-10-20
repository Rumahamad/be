from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CreateMemberInput(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    mobile: str | None = Field(default=None, min_length=8, max_length=30)
    role_code: str = Field(default="MEMBER", min_length=2, max_length=40)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
            raise ValueError("Enter a valid email address")
        return normalized

    @field_validator("first_name")
    @classmethod
    def normalize_first_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("First name cannot be blank")
        return normalized

    @field_validator("last_name", "mobile")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("role_code")
    @classmethod
    def normalize_role_code(cls, value: str) -> str:
        return value.strip().upper().replace(" ", "_")


class UpdateMemberStatusInput(BaseModel):
    status: Literal["ACTIVE", "BLOCKED", "INACTIVE"]


class UpdateMemberInput(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    mobile: str | None = Field(default=None, min_length=8, max_length=30)
    role_code: str | None = Field(default=None, min_length=2, max_length=40)

    @field_validator("role_code")
    @classmethod
    def normalize_role_code(cls, value: str | None) -> str | None:
        return value.strip().upper().replace(" ", "_") if value else value

    @field_validator("first_name")
    @classmethod
    def normalize_updated_first_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("First name cannot be blank")
        return normalized

    @field_validator("last_name", "mobile")
    @classmethod
    def normalize_updated_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def required_update_values(self) -> "UpdateMemberInput":
        for field in ("first_name", "role_code"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field.replace('_', ' ').title()} is required")
        return self


class MemberOutput(BaseModel):
    id: UUID
    member_code: str
    first_name: str
    last_name: str | None
    display_name: str
    email: str
    mobile: str | None
    role_code: str
    status: str
    language: Literal["en", "bn", "ur", "pr"]
    theme: Literal["bnc-green", "night"]
    profile_picture_url: str | None = None


class MemberListOutput(BaseModel):
    items: list[MemberOutput]
    total: int
