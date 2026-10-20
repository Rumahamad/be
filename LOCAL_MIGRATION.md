# Local PostgreSQL, authentication, storage and recovery

The local stack uses PostgreSQL 17 on `127.0.0.1:55432`, a non-superuser application
role, backend-owned identities, and private files under `.local/storage`. No database
port or upload directory is exposed publicly. Existing API routes and RBAC remain in
place. The API and scheduled workers must use the same environment file.

## Migration state (2026-09-21)

- Active `.env` remains on Supabase pending cutover approval and recovery decisions.
- `.env.local` configures the staged local database; it is ignored by Git.
- 43 source tables were restored and compared by record count and canonical row hash.
- 52 business users and 45 linked identities were preserved; 2 identities had password
  hashes and 1 had a Google identity. Passwordless/invited users remain passwordless;
  the migration does not invent passwords or bypass approval.
- 211 of 226 registered active attachments were copied and SHA-256 verified.
- 15 attachment objects are missing in Supabase. Their database records are retained.
  See `.local/migration/verification.json`; never silently drop these records.
- The saved Google Drive token currently fails refresh, despite the database marking
  the connection ACTIVE. There are no backup runs recorded. Reconnect Drive and verify
  a successful full backup before relying on it for recovery.
- SMTP settings are absent. Configure `EMAIL_PROVIDER=smtp` and the SMTP settings to
  enable invitations and password recovery. No email is sent by migration or tests.
- Register `https://bnc.pp.ua/api/v1/auth/google/callback` in the existing Google OAuth
  client before testing Google login on the public origin. A local browser using port
  5173 needs its own matching callback URL and `AUTH_COOKIE_SECURE=false`.

## Run and stop (from this backend directory)

```powershell
.\.venv\Scripts\python.exe -m scripts.local_postgres start
.\.venv\Scripts\python.exe -m scripts.run_backend --env .env.local --port 8081
```

Port 8081 is for staged verification. The existing Vite proxy targets 8080. After
verified cutover, use `.env` and port 8080. Stop the API/workers before stopping the DB:

```powershell
.\.venv\Scripts\python.exe -m scripts.local_postgres stop
```

PostgreSQL is not a Windows service and is not automatically started at boot. The PC,
database, API and any existing tunnel must stay running for remote access. Start the
existing job runner too if automatic Drive backup/reminders are required.

## Cutover and rollback

1. Resolve or explicitly acknowledge the existing missing-file inventory. Preserve
   its records even if unavailable files cannot be recovered.
2. Configure SMTP, register the Google login callback, reconnect Drive, and verify
   login/invitation/reset/backup in the staged system.
3. Stop app writes and scheduled workers. Recheck source table hashes against the
   saved inventory; recopy into a new empty target if source records changed.
4. Verify local users, roles, balances, payments and available attachments. Do not
   overwrite an existing local database to repeat the migration.
5. Preserve `.env` as `.env.supabase.local`, then activate `.env.local` as `.env`,
   restart the API on 8080, and sign in again. Supabase sessions are intentionally invalid.
6. Retain Supabase and the previous environment for rollback. After local writes
   begin, rollback requires reconciling those writes; blindly reverting `.env` loses them.

The migration tool refuses a nonempty target unless `--resume` is explicit; resume
still verifies source tables before finishing. Never run Supabase migrations during
this local migration. Existing historical migrations depend on Supabase-specific
roles and current ORM metadata; provisioning from an empty schema is not supported
by this migration. Start from the verified source dump or a complete local backup.

## Google Drive backup and future Admin restore

Business JSON/Sheets remain free of credentials. Full local backups additionally
contain Fernet-encrypted PostgreSQL data (including local identity hashes), encrypted
configuration and a cryptographically authenticated manifest. File artifacts retain
their integrity hashes. A missing attachment makes a full backup PARTIAL; it cannot
pass restore validation or be reported as a successful backup.

Keep `BACKUP_ENCRYPTION_KEY` in a password manager or another secure location outside
this PC. The archive does not contain its own decryption key. Keep the stable Google
token encryption key too (it is also inside the encrypted recovery configuration).
Losing the backup key makes the encrypted database/configuration unrecoverable.

Offline recovery targets a **new empty local database and empty private folder**:

```powershell
.\.venv\Scripts\python.exe -m scripts.restore_local_backup `
  --archive PATH_TO_DOWNLOADED_SNAPSHOT `
  --target-env .env.restore-target.local `
  --output-env .env.restored.local
```

The target env supplies `DATABASE_URL`, `LOCAL_STORAGE_ROOT`, `POSTGRES_BIN`, and the
separately retained `BACKUP_ENCRYPTION_KEY`. Restore validates the encrypted manifest,
checks the database/file inventory, revokes restored sessions/tokens, cancels stale
notification jobs, and disables automatic payment approval. It does not activate the
restored instance. Review it before switching the active environment.

Direct Admin-panel restore is recorded in `../ADMIN_WORKSPACE_TODO.md`; its UI and
orchestration are not implemented in this migration. Legacy business-only/Sheets
exports are not complete local-auth recovery backups.

## Security/operations

- New passwords use scrypt; imported bcrypt hashes are upgraded after successful login.
- Refresh tokens rotate; replay revokes the session. Logout/password reset invalidates
  sessions in the database. Recovery links are hashed, expiring, and single-use.
- Google login uses state cookies, PKCE, nonce, and verified signed ID tokens; only
  approved BNC members can receive sessions.
- Authentication request throttling is per process. Run one API process, or add shared
  ingress throttling before deploying multiple workers. Account lockouts are durable.
- SMTP, Google OAuth and Drive still require internet access; local password login,
  business data and uploaded files do not depend on Supabase.
- `.local`, `.env.local`, and recovery staging contain private data. Do not publish,
  commit, or serve them as static directories.
