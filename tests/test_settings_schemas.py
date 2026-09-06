import pytest
from pydantic import ValidationError

from app.schemas.settings import UpdateOrganizationSettingsInput


def test_reminder_days_are_deduplicated_and_sorted() -> None:
    payload = UpdateOrganizationSettingsInput(
        reminder_days_before_month_end=[1, 5, 1]
    )

    assert payload.reminder_days_before_month_end == [5, 1]


def test_rejects_invalid_reminder_day() -> None:
    with pytest.raises(ValidationError, match="between 0 and 30"):
        UpdateOrganizationSettingsInput(reminder_days_before_month_end=[31])
