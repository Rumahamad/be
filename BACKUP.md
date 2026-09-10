# Backup implementation progress

## Available now

Local snapshot command: reads the configured PostgreSQL database using a single
repeatable-read/read-only transaction, exports explicit BNC business tables and
downloads every registered evidence object. Existing payment revision/file links
are retained. It never writes to the database or Google.

```powershell
# Run from bnc-be. Use a private destination outside the source repository.
.\.venv\Scripts\python.exe -m app.jobs.backup snapshot --output C:\BNC-Recovery
.\.venv\Scripts\python.exe -m app.jobs.backup verify --archive "C:\BNC-Recovery\BNC_BACKUP\99_FULL_RECOVERY\01_WEEKLY\2026\2026-W37\<run-folder>"
```

The command returns nonzero for incomplete/missing/corrupted evidence. A failed
DB/export step may leave an incomplete directory without a manifest; retain it
for diagnosis or remove it manually. Each retry uses a new run directory.

Financial Decimal columns remain exact decimal strings in raw table exports to
preserve the source schema. The minor-unit serializer is available for Sheets.
ZIP/gzip output is not encryption: keep archives private.

`verify` checks manifest and artifact hashes/sizes and JSON row counts offline.
New snapshots also declare table keys/references: verification rejects missing
datasets, duplicate primary keys, broken in-scope foreign keys, and missing or
duplicate evidence. Older snapshots report `relations: NOT_CHECKED`.
These checks do NOT assert financial validity or successful restoration.
Never label this output RESTORE_TESTED. Five offline integrity tests pass; a
focused relational check also confirmed orphaned references are rejected.

Timezone-less database timestamps are preserved as wall-clock ISO strings;
the exporter does not falsely label them UTC. Aware timestamps use UTC.

## Remaining recovery work

The Drive/Sheets pipeline, Admin manual backup, monthly scheduling and near-real-time
Sheets mirror are implemented. Remaining hardening is a disposable-database restore
drill and separate source/config recovery. HDFC Gmail setup and rollout are documented
in `PAYMENT_VERIFICATION.md`; it uses a separate consent record and does not change
the recovery format.

Google Drive/Sheets/Gmail APIs and Web OAuth credentials need owner setup. Never
paste secrets into chat; keep them backend-only. Use drive.file for BNC-created
backup files and gmail.readonly for bank email. Keep Google connection tokens out
of every archive. Backup account and Gmail account are confirmed to be the same.

## Google owner connection setup

The backend now has an owner-only Drive OAuth foundation. Refresh tokens and PKCE
verifiers are encrypted; raw access tokens are not persisted. OAuth state is
random, expires after ten minutes, and is consumed before external calls.

1. In Google Cloud, create a project, enable **Google Drive API** and
   **Google Sheets API**, then configure the OAuth consent screen.
2. Create a **Web application** OAuth client.
3. Add the exact backend callback URL from `GOOGLE_OAUTH_REDIRECT_URI` as an
   authorized redirect URI. Local default is:
   `http://127.0.0.1:8080/api/v1/admin/backups/google/callback`.
4. Put client ID/secret and a generated Fernet key in backend `.env`. Optionally
   set `GOOGLE_OWNER_EMAIL` to prevent connecting the wrong account.
5. Apply migration `0017_backup_google_foundation`, restart the backend, then open
   Admin → General settings → Backup and select **Connect Google Drive**.

Only `openid`, `email`, and `drive.file` are requested. Gmail access will use a
separate consent record even though it is the same Google account. A callback
query parameter is never proof of connection; the UI must reload `/status`.

## Running a queued backup

**Back up now** writes a durable database job and returns immediately. The API
then processes that job in the background, so Google and file downloads stay
outside the request. The Admin screen polls the durable run state and shows
Pending, Running, Succeeded or Failed plus recent run history.

If the API process exits after queuing, the job remains Pending. Process it from
a scheduler or a separate terminal:

```powershell
cd C:\Kayef\bnc-web\bnc-be
.\.venv\Scripts\python.exe -m app.jobs.backup process-next --staging C:\BNC-Recovery
```

Run `scripts/process_all_jobs.py` regularly (for example every minute). Besides
the existing app jobs, it recovers pending backup work and creates one automatic
monthly recovery point on its first successful scheduler run each calendar
month. Manual recovery points remain available on any day.

On the current Windows host, Task Scheduler can call the repository runner every
minute without depending on an activated terminal environment:

```text
Program: powershell.exe
Arguments: -NoProfile -ExecutionPolicy Bypass -File "C:\Kayef\bnc-web\bnc-be\scripts\run_all_jobs.ps1"
```

The runner returns a nonzero exit code if any job fails, but still attempts the
remaining email, push, backup, Sheets and Gmail jobs. Admin -> Backup shows the
latest durable backup result and whether Sheets changes are waiting.

The worker creates a read-only consistent database snapshot, verifies it, uploads
the complete recovery directory with immutable run keys, then verifies Drive
size and MD5 for every binary object. Files larger than 5 MB use resumable upload.
It also creates or refreshes:

- `BNC_BACKUP/00_CONTROL/BNC_Backup_Control`
- `BNC_BACKUP/01_MASTER/YYYY/BNC_Master_YYYY`
- `BNC_BACKUP/02_ARCHIVE/YYYY/MM_Month/BNC_YYYY-MM`
- `BNC_BACKUP/03_USERS/00_CURRENT/BNC_Current_Users`

Each `BNC_Master_YYYY` file contains the detailed yearly tables plus one tab per
calendar month. A manual run can be started on any day. Every successful run is
a complete recovery point, while its source cutoff records how current it is.
Complete recovery points are intentional: a delta-only chain can miss deletions
or become unusable when one older run is lost.

Google Sheets is a readable current-data mirror, not the recovery authority.
Business changes create a `backup_outbox` event in the same database transaction.
Each `scripts/process_all_jobs.py` run coalesces pending events and rebuilds the
yearly/monthly Sheets from one consistent data snapshot. Run it every minute for
near-real-time Sheets. Failed syncs retry with backoff; Google is never called
inside payment, expense or member requests. Because the mirror also propagates
deletions, it cannot replace immutable recovery snapshots.

Sheets values use RAW input. Financial values are integer minor units to avoid
floating-point changes. The yearly workbook contains Dashboard, Contributions,
Payment_Transactions, Expenses, Members and Audit. It is a readable projection;
the versioned JSON and evidence archive remains the recovery source.

Monthly workbooks separate allocation-month contributions from submission-month
transactions and ledger-date cash movement. They contain Overview,
Contributions, Payment_Transactions, Payment_History, Expenses, Audit and
Backup_Metadata. Flexible donations remain unchanged; the backup does not invent
expected rates, partial balances or arrears.

The process exits nonzero when the job fails. It keeps the local staging folder
for diagnosis and never automatically deletes recovery data.

## Recovery limits requiring later work

- Supabase Auth credentials, sessions, push subscription secrets and notification
  queues are excluded. New-project recovery requires Auth reprovision/relinking.
- Source code, migrations, environment secrets and unregistered storage objects
  need separate recovery handling. This command is not a full infrastructure dump.
- Missing/previously deleted evidence makes a snapshot incomplete; never fabricate it.
- Storage objects can change after the database snapshot. Files are expected to be
  immutable; checksum/size errors are detected, but an atomic DB/storage snapshot
  is not claimed.
- No live snapshot, Google upload, migration or restore has been executed by Codex.
- Flexible donations remain unchanged; no fixed rates or top-ups will be introduced.
