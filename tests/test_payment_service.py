from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.payments import (
    AllocationInput,
    ContributionAvailabilityInput,
    CreatePaymentInput,
    ReversePaymentInput,
)


def test_rejects_duplicate_member_month_in_submission() -> None:
    member = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        CreatePaymentInput(
            allocations=[
                AllocationInput(member_id=member, year=2026, month=9, amount=Decimal(500)),
                AllocationInput(member_id=member, year=2026, month=9, amount=Decimal(700)),
            ]
        )


def test_rejects_invalid_availability_year_range() -> None:
    with pytest.raises(ValidationError, match="year_to"):
        ContributionAvailabilityInput(
            member_ids=[uuid4()], year_from=2027, year_to=2026
        )


def test_rejects_duplicate_members_in_availability_query() -> None:
    member = uuid4()
    with pytest.raises(ValidationError, match="only once"):
        ContributionAvailabilityInput(
            member_ids=[member, member], year_from=2026, year_to=2026
        )


def test_reversal_requires_meaningful_reason() -> None:
    with pytest.raises(ValidationError, match="at least 3"):
        ReversePaymentInput(reason="x")
