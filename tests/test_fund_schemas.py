from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.fund import CreateFundAdjustmentInput, ReverseFundEntryInput


def test_fund_adjustment_accepts_credit() -> None:
    payload = CreateFundAdjustmentInput(
        direction="CREDIT", amount=Decimal("100.00"), description="Opening correction"
    )

    assert payload.direction == "CREDIT"


def test_fund_reversal_requires_reason() -> None:
    with pytest.raises(ValidationError, match="at least 3"):
        ReverseFundEntryInput(reason="x")
