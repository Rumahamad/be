import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parseaddr
from zoneinfo import ZoneInfo


PARSER_VERSION = "hdfc-credit-v2"


@dataclass(frozen=True)
class ParsedHdfcCredit:
    amount: Decimal | None
    transaction_at: datetime | None
    sender_name: str | None
    sender_vpa: str | None
    upi_reference: str | None
    recipient_account_last4: str | None
    valid: bool
    error_code: str | None


def normalize_upi_reference(value: str | None) -> str | None:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return digits if 10 <= len(digits) <= 20 else None


def normalize_email_address(value: str) -> str:
    return parseaddr(value)[1].strip().lower()


def parse_hdfc_credit(body: str) -> ParsedHdfcCredit:
    text = re.sub(r"\s+", " ", body or "").strip()
    amount_match = re.search(
        r"(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        text, re.IGNORECASE,
    )
    reference_match = re.search(
        r"UPI\s+(?:Reference|Ref)\s*(?:No\.?|Number)?\s*[:\-]?\s*([0-9][0-9\s-]{8,28})",
        text, re.IGNORECASE,
    )
    account_match = re.search(
        r"account\s+ending(?:\s+in)?\s+(?:[xX*\-]*\s*)?([0-9]{4})\b",
        text, re.IGNORECASE,
    )
    sender_match = re.search(
        r"Sender\s*:\s*(.+?)(?:\s*\(\s*VPA\s*:\s*([^\s)]+)\s*\)|\s+[a-z]\.|$)",
        text, re.IGNORECASE,
    )
    date_match = re.search(
        r"(?:Transaction\s+)?Date\s*:\s*([0-9]{1,2}[\-/][0-9]{1,2}[\-/][0-9]{2,4}(?:\s+[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)?)",
        text, re.IGNORECASE,
    )
    amount = None
    if amount_match:
        try:
            amount = Decimal(amount_match.group(1).replace(",", ""))
        except InvalidOperation:
            amount = None
    reference = normalize_upi_reference(reference_match.group(1) if reference_match else None)
    transaction_at = _parse_date(date_match.group(1)) if date_match else None
    account_last4 = account_match.group(1) if account_match else None
    sender_name = sender_match.group(1).strip(" :-") if sender_match else None
    sender_vpa = sender_match.group(2).strip() if sender_match and sender_match.group(2) else None
    missing = [
        label for label, value in (
            ("AMOUNT", amount), ("REFERENCE", reference), ("ACCOUNT", account_last4),
        ) if value is None
    ]
    credit_alert = bool(re.search(r'\bcredited\s+to\b', text, re.IGNORECASE))
    return ParsedHdfcCredit(
        amount=amount,
        transaction_at=transaction_at,
        sender_name=sender_name,
        sender_vpa=sender_vpa,
        upi_reference=reference,
        recipient_account_last4=account_last4,
        valid=not missing and credit_alert and amount is not None and amount > 0,
        error_code=(f"MISSING_{'_'.join(missing)}" if missing else
                    'NOT_A_CREDIT_ALERT' if not credit_alert else
                    'INVALID_AMOUNT' if amount is None or amount <= 0 else None),
    )


def _parse_date(value: str) -> datetime | None:
    for pattern in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(value.strip(), pattern).replace(
                tzinfo=ZoneInfo("Asia/Kolkata")
            ).astimezone(UTC)
        except ValueError:
            continue
    return None
