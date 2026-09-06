import pytest
from pydantic import ValidationError

from app.schemas.auth import SetPasswordInput
from app.schemas.members import CreateMemberInput


def test_member_email_is_normalized() -> None:
    payload = CreateMemberInput(email=" Member@Example.com ", first_name="Member")
    assert payload.email == "member@example.com"


def test_member_role_cannot_be_admin() -> None:
    with pytest.raises(ValidationError):
        CreateMemberInput(email="member@example.com", first_name="Member", role_code="ADMIN")


def test_password_setup_requires_matching_strong_passwords() -> None:
    payload = SetPasswordInput(password="new-password", confirm_password="new-password")
    assert payload.password == "new-password"


def test_password_setup_rejects_mismatched_passwords() -> None:
    with pytest.raises(ValueError, match="Passwords do not match"):
        SetPasswordInput(password="new-password", confirm_password="different-password")
