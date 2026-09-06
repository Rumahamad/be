from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class AnnouncementTargetInput(BaseModel):
    target_type: Literal["ALL", "ROLE", "GROUP", "USER"]
    target_id: UUID | None = None

    @model_validator(mode="after")
    def validate_target(self):
        if self.target_type == "ALL" and self.target_id is not None:
            raise ValueError("ALL target must not include target_id")
        if self.target_type != "ALL" and self.target_id is None:
            raise ValueError(f"{self.target_type} target requires target_id")
        return self


class CreateAnnouncementInput(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    body: str = Field(min_length=1, max_length=10000)
    priority: Literal["NORMAL", "IMPORTANT", "CRITICAL"] = "NORMAL"
    pinned: bool = False
    publish_at: datetime | None = None
    expire_at: datetime | None = None
    targets: list[AnnouncementTargetInput] = Field(
        default_factory=lambda: [AnnouncementTargetInput(target_type="ALL")],
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_schedule_and_targets(self):
        for field_name, value in (("publish_at", self.publish_at), ("expire_at", self.expire_at)):
            if value and value.tzinfo is None:
                raise ValueError(f"{field_name} must include a timezone")
        if self.expire_at and self.publish_at and self.expire_at <= self.publish_at:
            raise ValueError("expire_at must be later than publish_at")
        all_targets = [target for target in self.targets if target.target_type == "ALL"]
        if all_targets and len(self.targets) != 1:
            raise ValueError("ALL cannot be combined with other announcement targets")
        unique_targets = {(target.target_type, target.target_id) for target in self.targets}
        if len(unique_targets) != len(self.targets):
            raise ValueError("Duplicate announcement target")
        return self


class AnnouncementOutput(BaseModel):
    id: UUID
    title: str
    body: str
    priority: str
    status: str
    pinned: bool
    publish_at: datetime
    expire_at: datetime | None
    created_by: UUID
    is_read: bool
    created_at: datetime


class AnnouncementListOutput(BaseModel):
    items: list[AnnouncementOutput]
    total: int


class NotificationOutput(BaseModel):
    id: UUID
    event_type: str
    title: str
    message: str
    reference_type: str | None
    reference_id: UUID | None
    is_read: bool
    read_at: datetime | None
    created_at: datetime


class NotificationListOutput(BaseModel):
    items: list[NotificationOutput]
    total: int
    unread_count: int


class NotificationReadAllOutput(BaseModel):
    updated_count: int
