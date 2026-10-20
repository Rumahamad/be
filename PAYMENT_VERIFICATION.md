# Gmail payment verification

Shadow and automatic modes share one authentication and matching engine.
Shadow leaves exact matches pending with **Approve verified payment**; screenshot
viewing is optional. Automatic mode approves through the normal payment service.
Failed or ambiguous matches remain pending for manual review.

## Google setup

1. In the same Google Cloud project used for Drive backup, enable **Gmail API**.
2. Add this production redirect URI to the Web OAuth client:
   `https://api.bnc.pp.ua/api/v1/admin/payment-verification/google/callback`
3. For local development also keep:
   `http://127.0.0.1:8080/api/v1/admin/payment-verification/google/callback`
4. If the OAuth app is still in Testing, add the BNC owner Google account as a
   test user. `gmail.readonly` is a sensitive scope and Google may require app
   verification before unrestricted production use.

## Backend environment

Set these only in the backend environment. Do not put them in the UI or commit
their values.

```dotenv
GMAIL_OAUTH_REDIRECT_URI=https://api.bnc.pp.ua/api/v1/admin/payment-verification/google/callback
GMAIL_HDFC_SEARCH_QUERY=
HDFC_CREDIT_EMAIL_FROM=
HDFC_FORWARDER_EMAIL=
GMAIL_VERIFICATION_ACCOUNT_EMAIL=
TESSERACT_CMD=
TESSERACT_LANGUAGE=eng
HDFC_EXPECTED_ACCOUNT_LAST4=
GMAIL_PAYTM_SEARCH_QUERY=
PAYTM_MERCHANT_EMAIL_FROM=
PAYTM_FORWARDER_EMAIL=
PAYTM_EXPECTED_MERCHANT_NAME=
PAYMENT_AUTO_VERIFY_ENABLED=false
PAYMENT_AUTO_VERIFY_SHADOW_MODE=true
```

Build the Gmail search query and trusted sender from one real HDFC credit email.
Use **Show original** in Gmail and verify its complete `From`, `Subject`,
`Authentication-Results`, and account suffix. Do not guess them. The ingestion
rejects messages unless sender, SPF, DKIM, and recipient account all match.

When a private Gmail account automatically forwards only HDFC alerts to the BNC
mailbox, query the preserved bank `From` address. Keep `HDFC_FORWARDER_EMAIL`
as the exact trusted forwarding source; the backend never connects to that
private account. Connect only the BNC Gmail account.

## Paytm for Business merchant notifications

The supplied Paytm format is accepted as a second, independently authenticated
Gmail source. It verifies the exact `From` address, Gmail SPF/DKIM/DMARC (or a
verified Gmail forwarding chain), Payment Received amount, merchant name,
transaction time, and Paytm Order ID. Configure an exact sender and a dedicated
label where practical:

```env
GMAIL_PAYTM_SEARCH_QUERY='from:no-reply@paytm.com "Payment Received" newer_than:30d'
PAYTM_MERCHANT_EMAIL_FROM=no-reply@paytm.com
PAYTM_FORWARDER_EMAIL=
PAYTM_EXPECTED_MERCHANT_NAME=KAYEF AHAMAD
```

Paytm merchant emails are fetched into the verification inbox but **never
auto-approve** a member payment. This format contains a Paytm Order ID, not the
payer-bank UPI/UTR reference extracted from the member proof, so matching by
amount and time would be unsafe. HDFC remains the only automatic-approval
source until Paytm supplies a stable payer UTR that can be matched exactly.

## Screenshot OCR and reconciliation

Install the Python dependencies from `pyproject.toml` and install the Tesseract
executable on the backend host. On Windows, set `TESSERACT_CMD` to the full
`tesseract.exe` path when it is not available on `PATH`.

Every newly uploaded payment screenshot is processed in the background. The
worker stores OCR evidence, selects a reference only when it appears beside a
UPI/UTR/transaction-reference label, then compares it with a trusted HDFC Gmail
credit. Automatic approval requires exact reference, exact amount, expected
account suffix, trusted email, and an unused credit.

Run the regular recovery worker to process work missed during a restart:

```powershell
.\.venv\Scripts\python.exe scripts\process_all_jobs.py
```

### Test without receiving a new bank credit

OCR a real screenshot without writing anything to the database:

```powershell
.\.venv\Scripts\python.exe -m app.jobs.payment_verification_cli ocr --image C:\path\proof.png
```

Dry-run a redacted HDFC body and redacted OCR text. Use the same fake reference,
amount, and account suffix in both files:

```powershell
.\.venv\Scripts\python.exe -m app.jobs.payment_verification_cli fixture `
  --email C:\path\sample-email.txt `
  --screenshot-text C:\path\sample-ocr.txt `
  --amount 500.00 --account-last4 1234
```

Fixture mode never reads or writes the database and does not authenticate the
email. It verifies parser and deterministic matching logic only. Keep
`PAYMENT_AUTO_VERIFY_SHADOW_MODE=true` while validating real messages. Enable
live approval only after the admin status and audit results are correct:

```env
PAYMENT_AUTO_VERIFY_ENABLED=true
PAYMENT_AUTO_VERIFY_SHADOW_MODE=false
```

Ready-made fake fixtures are available under `examples/payment-verification`.
They contain no real bank, member, or transaction data.

### Authorized Gmail ARC forwarding

Direct delivery is not required. Receiving Gmail must attest a passing ARC chain
with original HDFC-aligned SPF, DKIM and DMARC. The receiving Google ARC seal
must agree. Exact forwarding headers must also agree with Gmail's authenticated
forwarding envelope and configured source/destination. Visible From alone is
never sufficient. Authentication failures stay in manual review.

Drive backup and payment verification may use different Google accounts. Set
`GOOGLE_OWNER_EMAIL` to the BNC Drive owner and set
`GMAIL_VERIFICATION_ACCOUNT_EMAIL` to the BNC mailbox receiving forwarded
payment alerts. The backend queries each configured payment-source query; use
exact senders and dedicated Gmail labels to limit processing:

```env
GMAIL_HDFC_SEARCH_QUERY="label:BNC-HDFC from:alerts@hdfcbank.bank.in newer_than:30d"
```
Leave `HDFC_FORWARDER_EMAIL` empty only for direct delivery.

## Activate the foundation

1. Run `python -m alembic upgrade head` (includes `0021_arc_evidence`).
2. Restart the backend.
3. Open Admin -> Workspace settings -> Payment verification.
4. Select **Connect Gmail**, approve read-only access, then select **Sync Gmail now**.
5. Confirm that trusted credits appear as unmatched and malformed/untrusted mail
   is rejected. Keep shadow mode enabled during this validation.
6. Run `scripts/process_all_jobs.py` every minute for continuous polling. Gmail is
   never called from the payment request path.

## Required before auto-approval

- Extract the UPI reference from the current payment revision screenshot.
- Match exact normalized reference and exact amount against one unused trusted
  bank credit.
- Reject ambiguous, duplicate, missing, reused, or recipient-mismatched records.
- Record the decision, consume the credit atomically, and call the existing
  payment approval service so ledger, receipt, audit, email, and push behavior
  stay identical to manual approval.
- Enable auto-approval only after shadow results have been reviewed.

## Verified approval and reversal

The matching report shows individual UTR, amount, account, authentication and
screenshot extraction checks. `POST /api/v1/payments/{id}/approve?verified=true`
reruns the engine transactionally under the existing approval permission. A stale
match returns a conflict, never an unchecked fallback approval.

Authentication evidence and decision events preserve message IDs, original
authentication, forwarding result, reference, amount, account, payment, mode,
actor and approval timestamp. Permanent UTR claims and transaction locks prevent
reuse, including after reversal. **Reverse approval** in payment history requires
permission and a reason, balances the ledger and voids the receipt without
erasing history or releasing the UTR.
