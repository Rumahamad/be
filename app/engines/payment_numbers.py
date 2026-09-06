from uuid import uuid4


def payment_no() -> str:
    return f"PAY-{uuid4().hex[:10].upper()}"


def ledger_entry_no() -> str:
    return f"LED-{uuid4().hex[:10].upper()}"


def receipt_no() -> str:
    return f"RCT-{uuid4().hex[:10].upper()}"
