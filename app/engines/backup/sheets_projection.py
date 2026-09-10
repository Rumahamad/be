"""Readable, rebuildable Sheets projections from a verified recovery snapshot."""

import gzip
import json
from datetime import UTC, datetime
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.engines.backup.canonical import canonical_bytes, digest, money_minor


def load_dataset(root: Path, name: str) -> list[dict]:
    return json.loads(gzip.decompress((root / "data" / f"{name}.json.gz").read_bytes()))


def _minor(value) -> int:
    return money_minor(Decimal(str(value)))


def _year(value, year: int) -> bool:
    return bool(value) and str(value).startswith(str(year))


def build_yearly_master(
    root: Path, year: int, evidence_links: dict[str, str], *, include_month_tabs: bool = True,
) -> dict[str, list[list]]:
    users = load_dataset(root, "users")
    roles = {row["id"]: row for row in load_dataset(root, "roles")}
    user_by_id = {row["id"]: row for row in users}
    name = lambda user_id: user_by_id.get(user_id, {}).get("display_name", "")
    payments = load_dataset(root, "payments")
    allocations = load_dataset(root, "payment_allocations")
    contributions = load_dataset(root, "member_month_contributions")
    expenses = load_dataset(root, "expenses")
    fund_entries = load_dataset(root, "fund_entries")
    audits = load_dataset(root, "audit_logs")
    payment_files = load_dataset(root, "payment_files")
    expense_attachments = load_dataset(root, "expense_attachments")
    files_by_payment: dict[str, list[str]] = defaultdict(list)
    for row in payment_files:
        link = evidence_links.get(row["file_id"])
        if link:
            files_by_payment[row["payment_id"]].append(link)
    files_by_expense: dict[str, list[str]] = defaultdict(list)
    for row in expense_attachments:
        link = evidence_links.get(row["file_id"])
        if link:
            files_by_expense[row["expense_id"]].append(link)
    allocations_by_payment: dict[str, list[dict]] = defaultdict(list)
    for row in allocations:
        allocations_by_payment[row["payment_id"]].append(row)

    yearly_contributions = [row for row in contributions if row["year"] == year]
    yearly_payments = [row for row in payments if _year(row.get("submitted_at"), year)]
    yearly_expenses = [row for row in expenses if _year(row.get("expense_date"), year)]
    yearly_audits = [row for row in audits if _year(row.get("created_at"), year)]
    approved_contributions = sum(
        (_minor(row["amount"]) for row in yearly_contributions if row["status"] == "APPROVED"), 0
    )
    yearly_ledger = [row for row in fund_entries if _year(row.get("entry_date"), year)]
    approved_cash = sum(
        (_minor(row["amount"]) for row in yearly_ledger
         if row["direction"] == "CREDIT" and row["entry_type"] == "CONTRIBUTION"), 0
    )
    expense_total = sum((_minor(row["amount"]) for row in yearly_expenses if row["status"] == "POSTED"), 0)
    ledger_credits = sum(_minor(row["amount"]) for row in yearly_ledger if row["direction"] == "CREDIT")
    ledger_debits = sum(_minor(row["amount"]) for row in yearly_ledger if row["direction"] == "DEBIT")

    contribution_rows = [[
        "backup_key", "payment_id", "member_id", "member_name", "contribution_month",
        "amount_minor", "currency", "status", "evidence_links", "updated_at",
    ]]
    for row in sorted(yearly_contributions, key=lambda item: (item["year"], item["month"], item["member_id"])):
        contribution_rows.append([
            f"CONTRIB:{row['payment_id']}:{row['year']}-{row['month']:02d}:{row['member_id']}",
            row["payment_id"], row["member_id"], name(row["member_id"]),
            f"{row['year']}-{row['month']:02d}", _minor(row["amount"]), "INR", row["status"],
            "\n".join(sorted(files_by_payment[row["payment_id"]])), row.get("updated_at", ""),
        ])
    payment_rows = [[
        "payment_id", "payment_no", "payer_id", "payer_name", "beneficiary_ids",
        "beneficiary_names", "total_amount_minor", "currency", "status", "submitted_at",
        "approved_at", "approved_by", "rejection_reason", "current_revision", "evidence_links",
    ]]
    for row in sorted(yearly_payments, key=lambda item: item.get("submitted_at") or ""):
        beneficiaries = allocations_by_payment[row["id"]]
        ids = sorted({item["member_id"] for item in beneficiaries})
        payment_rows.append([
            row["id"], row["payment_no"], row["submitted_by"], name(row["submitted_by"]),
            ", ".join(ids), ", ".join(name(item) for item in ids), _minor(row["total_amount"]),
            "INR", row["status"], row.get("submitted_at", ""), row.get("approved_at", ""),
            name(row.get("approved_by")), row.get("rejection_reason", ""), row["current_revision"],
            "\n".join(sorted(files_by_payment[row["id"]])),
        ])
    expense_rows = [[
        "expense_id", "expense_date", "category", "description", "amount_minor", "currency",
        "payee", "payment_method", "reference_no", "created_by", "receipt_links", "status",
    ]]
    for row in sorted(yearly_expenses, key=lambda item: (item["expense_date"], item["id"])):
        expense_rows.append([
            row["id"], row["expense_date"], row["category"], row.get("description", ""),
            _minor(row["amount"]), "INR", row.get("payee", ""), row.get("payment_method", ""),
            row.get("reference_no", ""), name(row["created_by"]),
            "\n".join(sorted(files_by_expense[row["id"]])), row["status"],
        ])
    member_rows = [["user_id", "member_code", "name", "email", "mobile", "role", "status", "joined_at", "updated_at"]]
    for row in sorted(users, key=lambda item: item["member_code"]):
        member_rows.append([
            row["id"], row["member_code"], row["display_name"], row["email"], row.get("mobile", ""),
            roles.get(row["role_id"], {}).get("name", ""), row["status"], row["created_at"], row["updated_at"],
        ])
    audit_rows = [["audit_id", "event_at", "actor_id", "actor_name", "entity_type", "entity_id", "action", "before_hash", "after_hash"]]
    for row in sorted(yearly_audits, key=lambda item: item["created_at"]):
        audit_rows.append([
            row["id"], row["created_at"], row.get("actor_user_id", ""), name(row.get("actor_user_id")),
            row["entity_type"], row.get("entity_id", ""), row["action"],
            digest(canonical_bytes(row["before_data"])) if row.get("before_data") is not None else "",
            digest(canonical_bytes(row["after_data"])) if row.get("after_data") is not None else "",
        ])
    tabs = {
        "Dashboard": [
            ["Metric", "Amount minor / count"],
            ["Year", year], ["Approved contribution amount", approved_contributions],
            ["Approved payment cash", approved_cash], ["Posted expense amount", expense_total],
            ["Ledger credits", ledger_credits], ["Ledger debits", ledger_debits],
            ["Net cash flow", ledger_credits - ledger_debits], ["Payment transactions", len(yearly_payments)],
            ["Contribution rows", len(yearly_contributions)], ["Expenses", len(yearly_expenses)],
            ["Members", len(users)],
        ],
        "Contributions": contribution_rows,
        "Payment_Transactions": payment_rows,
        "Expenses": expense_rows,
        "Members": member_rows,
        "Audit": audit_rows,
    }
    if include_month_tabs:
        for archive_year, archive_month in available_months(root):
            if archive_year != year:
                continue
            monthly = build_monthly_archive(
                root, archive_year, archive_month, evidence_links, "LIVE",
            )
            rows = [["BNC monthly view", f"{archive_year}-{archive_month:02d}"]]
            for section in (
                "Overview", "Contributions", "Payment_Transactions",
                "Payment_History", "Expenses", "Audit",
            ):
                rows.extend([[], [section], *monthly[section]])
            tabs[datetime(archive_year, archive_month, 1).strftime("%b")] = rows
    return tabs


def build_current_users(root: Path) -> dict[str, list[list]]:
    users = load_dataset(root, "users")
    roles = {row["id"]: row for row in load_dataset(root, "roles")}
    preferences = {row["user_id"]: row for row in load_dataset(root, "user_preferences")}
    rows = [["user_id", "member_code", "name", "mobile", "email", "role", "status", "joined_at", "updated_at", "language", "theme"]]
    for user in sorted(users, key=lambda item: item["member_code"]):
        pref = preferences.get(user["id"], {})
        rows.append([
            user["id"], user["member_code"], user["display_name"], user.get("mobile", ""), user["email"],
            roles.get(user["role_id"], {}).get("name", ""), user["status"], user["created_at"],
            user["updated_at"], pref.get("language_override", ""), pref.get("theme_override", ""),
        ])
    return {"Current_Users": rows}


def available_months(root: Path) -> list[tuple[int, int]]:
    months = {(datetime.now(UTC).year, datetime.now(UTC).month)}
    for row in load_dataset(root, "member_month_contributions"):
        months.add((int(row["year"]), int(row["month"])))
    for dataset, field in (
        ("payments", "submitted_at"), ("payments", "approved_at"),
        ("payments", "rejected_at"), ("expenses", "expense_date"),
        ("fund_entries", "entry_date"),
        ("audit_logs", "created_at"), ("payment_reviews", "created_at"),
    ):
        for row in load_dataset(root, dataset):
            value = row.get(field)
            if value:
                months.add((int(str(value)[:4]), int(str(value)[5:7])))
    return sorted(months)


def build_monthly_archive(
    root: Path, year: int, month: int, evidence_links: dict[str, str], run_id: str,
) -> dict[str, list[list]]:
    prefix = f"{year}-{month:02d}"
    yearly = build_yearly_master(root, year, evidence_links, include_month_tabs=False)
    contributions = [yearly["Contributions"][0], *[
        row for row in yearly["Contributions"][1:] if row[4] == prefix
    ]]
    transactions = [yearly["Payment_Transactions"][0], *[
        row for row in yearly["Payment_Transactions"][1:] if str(row[9]).startswith(prefix)
    ]]
    expenses = [yearly["Expenses"][0], *[
        row for row in yearly["Expenses"][1:] if str(row[1]).startswith(prefix)
    ]]
    audits = [yearly["Audit"][0], *[
        row for row in yearly["Audit"][1:] if str(row[1]).startswith(prefix)
    ]]
    users = {row["id"]: row["display_name"] for row in load_dataset(root, "users")}
    history = [[
        "event_id", "payment_id", "sequence_no", "event_type", "actor_id",
        "actor_name", "event_at", "reason", "note", "event_hash",
    ]]
    events = []
    for row in load_dataset(root, "payment_revisions"):
        if str(row["created_at"]).startswith(prefix):
            payload = {
                "id": row["id"], "payment_id": row["payment_id"],
                "revision_no": row["revision_no"], "status": row["status_snapshot"],
                "created_at": row["created_at"],
            }
            events.append([
                row["id"], row["payment_id"], row["revision_no"], "REVISION_CREATED",
                row["created_by"], users.get(row["created_by"], ""), row["created_at"], "",
                row.get("user_note", ""), digest(canonical_bytes(payload)),
            ])
    for row in load_dataset(root, "payment_reviews"):
        if str(row["created_at"]).startswith(prefix):
            payload = {
                "id": row["id"], "payment_id": row["payment_id"], "action": row["action"],
                "revision_no": row["revision_no"], "created_at": row["created_at"],
            }
            events.append([
                row["id"], row["payment_id"], row["revision_no"], row["action"],
                row["reviewed_by"], users.get(row["reviewed_by"], ""), row["created_at"],
                row.get("comment", ""), "", digest(canonical_bytes(payload)),
            ])
    history.extend(sorted(events, key=lambda row: (row[6], row[0])))
    approved_contributions = sum(row[5] for row in contributions[1:] if row[7] == "APPROVED")
    ledger = [row for row in load_dataset(root, "fund_entries") if str(row["entry_date"]).startswith(prefix)]
    approved_cash = sum(
        _minor(row["amount"]) for row in ledger
        if row["direction"] == "CREDIT" and row["entry_type"] == "CONTRIBUTION"
    )
    ledger_credits = sum(_minor(row["amount"]) for row in ledger if row["direction"] == "CREDIT")
    ledger_debits = sum(_minor(row["amount"]) for row in ledger if row["direction"] == "DEBIT")
    posted_expenses = sum(row[4] for row in expenses[1:] if row[11] == "POSTED")
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "Overview": [
            ["Metric", "Amount minor / count"], ["Archive month", prefix],
            ["Approved contributions allocated to month", approved_contributions],
            ["Approved payment cash during month", approved_cash],
            ["Posted expenses during month", posted_expenses],
            ["Ledger credits", ledger_credits], ["Ledger debits", ledger_debits],
            ["Net cash flow", ledger_credits - ledger_debits],
            ["Pending payment transactions", sum(row[8] == "PENDING_VERIFICATION" for row in transactions[1:])],
            ["Rejected payment transactions", sum(row[8] == "REJECTED" for row in transactions[1:])],
            ["Generated at", generated_at],
        ],
        "Contributions": contributions,
        "Payment_Transactions": transactions,
        "Payment_History": history,
        "Expenses": expenses,
        "Audit": audits,
        "Backup_Metadata": [
            ["Key", "Value"], ["schema_version", 1], ["archive_month", prefix],
            ["generated_at", generated_at], ["backup_run_id", run_id],
            ["verification_status", "ARTIFACT_INTEGRITY_PASSED"],
            ["restore_tested", False],
        ],
    }


def build_control_sheet(manifest: dict, runs: list[dict], run_id: str, run_folder_link: str) -> dict[str, list[list]]:
    artifacts = manifest.get("artifacts", [])
    inventory = [["Dataset", "Records", "Size bytes", "SHA-256"]]
    for artifact in artifacts:
        if "record_count" in artifact:
            inventory.append([
                Path(artifact["path"]).name.removesuffix(".json.gz"), artifact["record_count"],
                artifact["size_bytes"], artifact["sha256"],
            ])
    run_rows = [["Run ID", "Type", "Trigger", "Status", "Attempts", "Created", "Completed", "Error code"]]
    for run in runs:
        status = "SUCCEEDED" if run["id"] == run_id else run["status"]
        run_rows.append([
            run["id"], run["run_type"], run["trigger_type"], status, run["attempt_count"],
            run["created_at"], datetime.now(UTC).isoformat() if run["id"] == run_id else run.get("completed_at", ""),
            "" if run["id"] == run_id else run.get("error_code", ""),
        ])
    errors = [["Run ID", "Item", "Error type"]]
    errors.extend([
        [run_id, item.get("file_id", "snapshot"), item.get("error_type", "UNKNOWN")]
        for item in manifest.get("errors", [])
    ])
    return {
        "Status": [
            ["Metric", "Value"], ["Google Drive connection", "CONNECTED"],
            ["Last backup status", "SUCCEEDED"], ["Last backup run", run_id],
            ["Source cutoff", manifest.get("source_cutoff", "")],
            ["Artifacts", len(artifacts)],
            ["Failed items", len(manifest.get("errors", []))],
            ["Restore tested", False],
        ],
        "Backup_Runs": run_rows,
        "Inventory": inventory,
        "Restore_Points": [["Run ID", "Created", "Folder link", "Restore tested"], [
            run_id, manifest.get("completed_at", ""), run_folder_link, False,
        ]],
        "Errors": errors,
    }
