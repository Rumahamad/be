# BNC Backend

Independent FastAPI service using Supabase PostgreSQL, Auth, and Storage. The UI reaches Supabase only through this REST API, except for the normal browser redirect during Google sign-in.

## Setup

1. Copy `.env.example` to `.env` and fill the private values locally.
2. Create a Python 3.12 virtual environment.
3. Install: `python -m pip install -e .[dev]`.
4. Migrate: `python -m alembic upgrade head`.
5. Bootstrap screenshot storage: `python scripts/bootstrap_storage.py`.
6. Run: `python app.py` (starts on `http://127.0.0.1:8080`).

The storage bootstrap is idempotent and creates the configured bucket as private
with the application's file-size and image-type limits.

Never expose `DATABASE_URL` or `SUPABASE_SERVICE_ROLE_KEY` to the UI.

Authentication endpoints are under `/api/v1/auth`: login, refresh, logout, Google redirect, OAuth session acceptance, current user, first-login password setup, and password recovery. Supabase Auth sends invitation and reset emails; a recovery link opens `/auth/reset-password`, verifies the recovery session, shows the new-password form, and returns the user to sign-in after success.

For local password links, set `FRONTEND_URL=http://127.0.0.1:5173`. In Supabase **Authentication → URL Configuration**, add `http://127.0.0.1:5173/auth/set-password` and `http://127.0.0.1:5173/auth/reset-password` to Redirect URLs. For deployment, replace `FRONTEND_URL` with the public UI origin and add the equivalent HTTPS routes. The frontend host must rewrite these routes to `index.html`.

Payments use `/api/v1/payments`: contribution availability, explicit member/month allocations, member submission/resubmission, protected screenshot upload/download, member history, and permission-checked verification. Admins can read `/api/v1/fund/summary`, create/list immutable expenses under `/api/v1/expenses`, and inspect `/api/v1/audit`. Per-user language, theme, and RTL preferences are under `/api/v1/me/preferences`.

Announcements and the per-user inbox use `/api/v1/announcements` and `/api/v1/notifications`. Immediate announcements create in-app notifications in the same database transaction. To publish due scheduled announcements, run `python scripts/process_due_announcements.py` from a local scheduler or Supabase-compatible cron runner; the job uses row locking and is safe to run repeatedly.

Web Push subscriptions use `/api/v1/push/*`. Generate a VAPID key pair with
`python scripts/generate_vapid_keys.py`, copy the three `VAPID_*` settings into
`.env`, and restart the API. Announcement publication and payment creation,
resubmission, approval, and rejection start immediate outbox delivery after the
database transaction commits. `process_all_jobs.py` retries transient failures
and also delivers pushes for scheduled announcements.

Run `python scripts/process_contribution_reminders.py` daily to create the configured
month-end reminders. Delivery is idempotent per member, month, and reminder day;
`process_notification_outbox.py` sends the queued email notifications.
For a single scheduler command, run `python scripts/process_all_jobs.py`; it publishes
scheduled announcements, creates due reminders, and processes email and push delivery.

Email delivery is disabled by default. To enable it, set `EMAIL_PROVIDER=smtp`,
configure the `SMTP_*` values in `.env`, then schedule `scripts/process_all_jobs.py`.
Port 587 normally uses `SMTP_USE_TLS=true`; port 465 uses `SMTP_USE_SSL=true` and
`SMTP_USE_TLS=false`. Approval emails include the generated PDF receipt. Other
outbox events use dedicated HTML and plain-text templates with a safe generic
fallback. Supabase Auth sends membership invitations itself; copy
`templates/supabase/invite.html` into the Supabase **Invite user** email template
to keep that email consistent with the app. Copy `templates/supabase/recovery.html`
into the Supabase **Reset password** template. It defers token verification until
the user submits the new-password form, so simply opening the email link does not
consume it. Supabase still requires a finite Email OTP Expiration; 24 hours is the
recommended maximum.

## Create the first administrator

Public registration is intentionally unavailable. After migration, configure
`SUPABASE_SECRET_KEY` and run this once:

```powershell
.\.venv\Scripts\python.exe scripts\bootstrap_admin.py --email admin@example.com --first-name "Admin" --mobile "9800000000"
```

The password is requested securely and is not placed in shell history. Bootstrap refuses to run after the first BNC user exists.
