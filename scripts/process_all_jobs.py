from app.jobs.announcements import process_due_announcements
from app.jobs.contribution_reminders import process_contribution_reminders
from app.jobs.notifications import process_notification_outbox
from app.jobs.push_notifications import process_push_outbox

if __name__ == "__main__":
    published = process_due_announcements()
    reminders = process_contribution_reminders()
    delivered = process_notification_outbox()
    pushed = process_push_outbox()
    print(
        f"Published {published} announcement(s), created {reminders} reminder(s), "
        f"delivered {delivered} email(s), sent {pushed} push notification(s)."
    )
