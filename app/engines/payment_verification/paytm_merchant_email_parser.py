import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


PARSER_VERSION = "paytm-merchant-v1"


@dataclass(frozen=True)
class ParsedPaytmMerchantPayment:
    amount: Decimal | None
    transaction_at: datetime | None
    sender_name: str | None
    sender_vpa: str | None
    merchant_name: str | None
    paytm_order_id: str | None
    valid: bool
    error_code: str | None


def normalize_merchant_name(value: str | None) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", value or "").upper().split())


def merchant_names_match(observed: str | None, expected: str | None) -> bool:
    return bool(observed and expected and
                normalize_merchant_name(observed) == normalize_merchant_name(expected))


def parse_paytm_merchant_payment(body: str) -> ParsedPaytmMerchantPayment:
    text = re.sub(r"\s+", " ", body or "").strip()
    amount_match = re.search(
        r"\bPayment\s+Received\b.*?(?:₹|INR|Rs\.?)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE,
    )
    payer_match = re.search(
        r"\bFrom\s+(.+?)\s+\bIn\s+Account\s+of\b",
        text,
        re.IGNORECASE,
    )
    merchant_match = re.search(
        r"\bIn\s+Account\s+of\s+(.+?)\s+(?:\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b|\bOrder\s+ID\b)",
        text,
        re.IGNORECASE,
    )
    date_match = re.search(
        r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s*[AP]M)\b",
        text,
        re.IGNORECASE,
    )
    order_match = re.search(r"\bOrder\s*ID\s*:\s*([A-Za-z0-9_-]{10,80})\b", text, re.IGNORECASE)

    amount = None
    if amount_match:
        try:
            amount = Decimal(amount_match.group(1).replace(",", ""))
        except InvalidOperation:
            amount = None

    payer = payer_match.group(1).strip(" :-") if payer_match else None
    sender_vpa_match = re.search(r"([A-Za-z0-9._-]{2,}@[A-Za-z0-9._-]{2,})\b", payer or "")
    sender_vpa = sender_vpa_match.group(1).lower() if sender_vpa_match else None
    sender_name = (payer[:sender_vpa_match.start()].strip(" :-") if sender_vpa_match else payer) or None
    merchant_name = merchant_match.group(1).strip(" :-") if merchant_match else None
    transaction_at = _parse_date(date_match.group(1)) if date_match else None
    paytm_order_id = order_match.group(1).upper() if order_match else None
    missing = [
        label for label, value in (
            ("AMOUNT", amount),
            ("MERCHANT", merchant_name),
            ("TRANSACTION_AT", transaction_at),
            ("ORDER_ID", paytm_order_id),
        ) if value is None
    ]
    return ParsedPaytmMerchantPayment(
        amount=amount,
        transaction_at=transaction_at,
        sender_name=sender_name,
        sender_vpa=sender_vpa,
        merchant_name=merchant_name,
        paytm_order_id=paytm_order_id,
        valid=not missing and amount is not None and amount > 0,
        error_code=(f"MISSING_{'_'.join(missing)}" if missing else
                    "INVALID_AMOUNT" if amount is None or amount <= 0 else None),
    )


def _parse_date(value: str) -> datetime | None:
    for pattern in ("%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(value.strip(), pattern).replace(
                tzinfo=ZoneInfo("Asia/Kolkata")
            ).astimezone(UTC)
        except ValueError:
            continue
    return None
