from app.jobs.announcements import process_due_announcements

if __name__ == "__main__":
    processed = process_due_announcements()
    print(f"Published {processed} scheduled announcement(s).")
