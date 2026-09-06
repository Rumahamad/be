from app.jobs.contribution_reminders import process_contribution_reminders

if __name__ == "__main__":
    created = process_contribution_reminders()
    print(f"Created {created} contribution reminder(s).")
