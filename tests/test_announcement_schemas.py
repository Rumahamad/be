from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.announcements import AnnouncementTargetInput, CreateAnnouncementInput


def test_all_audience_cannot_be_combined_with_other_targets() -> None:
    with pytest.raises(ValidationError, match="ALL cannot be combined"):
        CreateAnnouncementInput(
            title="Meeting",
            body="Monthly meeting",
            targets=[
                AnnouncementTargetInput(target_type="ALL"),
                AnnouncementTargetInput(target_type="USER", target_id=uuid4()),
            ],
        )


def test_specific_audience_requires_target_id() -> None:
    with pytest.raises(ValidationError, match="requires target_id"):
        AnnouncementTargetInput(target_type="GROUP")


def test_announcement_expiry_must_follow_publish_time() -> None:
    publish_at = datetime.now(UTC)
    with pytest.raises(ValidationError, match="expire_at"):
        CreateAnnouncementInput(
            title="Meeting",
            body="Monthly meeting",
            publish_at=publish_at,
            expire_at=publish_at - timedelta(minutes=1),
        )
