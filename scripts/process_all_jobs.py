from pathlib import Path
from tempfile import gettempdir

from app.jobs.announcements import process_due_announcements
from app.jobs.contribution_reminders import process_contribution_reminders
from app.jobs.notifications import process_notification_outbox
from app.jobs.push_notifications import process_push_outbox
from app.jobs.backup_schedule import queue_monthly_backup_if_due
from app.services.backup_worker_service import BackupWorkerService
from app.services.backup_sheet_mirror_service import BackupSheetMirrorService
from app.services.gmail_credit_sync_service import GmailCreditSyncService
from app.jobs.payment_verification import process_pending_payment_proofs

failures: list[str] = []


def run_job(name: str, callback, default):
    try:
        return callback()
    except Exception as exc:
        failures.append(f"{name}:{type(exc).__name__}")
        return default


if __name__ == "__main__":
    failures.clear()
    published = run_job("announcements", process_due_announcements, 0)
    reminders = run_job("reminders", process_contribution_reminders, 0)
    delivered = run_job("email", process_notification_outbox, 0)
    pushed = run_job("push", process_push_outbox, 0)
    monthly_queued = run_job("monthly_backup", queue_monthly_backup_if_due, False)
    backup = run_job(
        "backup",
        lambda: BackupWorkerService().process_next(Path(gettempdir()) / "bnc-backup-staging"),
        None,
    )
    mirrored = run_job("sheets", BackupSheetMirrorService().process_due, 0)
    gmail = run_job("gmail", GmailCreditSyncService().sync_if_ready, None)
    proofs = run_job("payment_ocr", process_pending_payment_proofs, 0)
    print(
        f"Published {published} announcement(s), created {reminders} reminder(s), "
        f"delivered {delivered} email(s), sent {pushed} push notification(s), "
        f"backup {'processed' if backup else 'idle'}"
        f"{' (monthly queued)' if monthly_queued else ''}, mirrored {mirrored} change(s), "
        f"Gmail {'idle' if gmail is None else f'{gmail.stored} stored'}, "
        f"OCR {proofs} proof(s)."
    )
    if failures:
        print(f"Failed jobs: {', '.join(failures)}")
        raise SystemExit(1)
