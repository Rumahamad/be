"""Safe payment-verification diagnostics; fixture mode never writes to the DB."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from app.engines.payment_verification.hdfc_email_parser import parse_hdfc_credit
from app.engines.payment_verification.screenshot_ocr import (
    TesseractScreenshotOcr,
    extract_reference_candidates,
)


def fixture(email_file: Path, screenshot_text_file: Path, amount: Decimal, account_last4: str) -> int:
    email = parse_hdfc_credit(email_file.read_text(encoding="utf-8"))
    candidates = extract_reference_candidates(screenshot_text_file.read_text(encoding="utf-8"))
    screenshot_reference = candidates[0].value if candidates else None
    checks = {
        "email_valid": email.valid,
        "screenshot_reference_found": bool(screenshot_reference),
        "reference_matches": bool(screenshot_reference and screenshot_reference == email.upi_reference),
        "amount_matches": email.amount == amount,
        "account_matches": email.recipient_account_last4 == account_last4,
    }
    checks["would_auto_approve_if_authenticated"] = all(checks.values())
    # Never print raw references or bank-email contents.
    print(json.dumps(checks, indent=2))
    return 0 if checks["would_auto_approve_if_authenticated"] else 1


def ocr(image_file: Path) -> int:
    result = TesseractScreenshotOcr().extract(image_file.read_bytes())
    print(json.dumps({
        "status": "REFERENCE_FOUND" if result.selected_reference else "NO_REFERENCE",
        "reference_last4": result.selected_reference[-4:] if result.selected_reference else None,
        "candidate_count": len(result.candidates),
        "confidence": str(result.confidence) if result.confidence is not None else None,
        "engine_version": result.engine_version,
    }, indent=2))
    return 0 if result.selected_reference else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="BNC payment-verification diagnostics")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture_parser = commands.add_parser("fixture", help="Dry-run parser and matcher")
    fixture_parser.add_argument("--email", type=Path, required=True)
    fixture_parser.add_argument("--screenshot-text", type=Path, required=True)
    fixture_parser.add_argument("--amount", type=Decimal, required=True)
    fixture_parser.add_argument("--account-last4", required=True)
    ocr_parser = commands.add_parser("ocr", help="OCR one screenshot without DB writes")
    ocr_parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fixture":
        return fixture(args.email, args.screenshot_text, args.amount, args.account_last4)
    return ocr(args.image)


if __name__ == "__main__":
    raise SystemExit(main())
