from app.jobs.notifications import process_notification_outbox

if __name__ == "__main__":
    processed = process_notification_outbox()
    print(f"Delivered {processed} notification email(s).")
