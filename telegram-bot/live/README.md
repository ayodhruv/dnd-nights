# DND Nights live bot

Public Telegram bookings with PayNow and **manual verification in the receiving bank account**. No TEST_USER_IDS setting. This version is separate from the earlier prototype; start `app.py`, not the parent `bot.py`.

Confirmed configuration: event 28 November 2026, early bird S$25 through 14 November inclusive (Singapore), presale S$30, event-day walk-in S$35, maximum 230 tickets. One or two tickets per order. This code handles this single event. Price values are defined in `offer()`; changing price env vars alone does not change them.

## What is ready

- Guest Q&A and per-order PayNow QR delivery. The static QR does not embed the total or serial. Remarks remain optional.
- One active unpaid booking per Telegram user, 30-minute unpaid holds, atomic capacity enforcement. Submitted payments hold capacity for review. Expired payments can be reported and are explicitly reviewed against remaining capacity.
- Staff approve only after checking the actual incoming bank transaction and identifying its payer/order. Exact amounts and unique bank references enforced in one SQLite transaction. Identical amounts or screenshots alone are not sufficient.
- One secret QR per guest; ticket labels are unique. Public order IDs include `DND26-` followed by DDMM + daily sequence + first label. Labels are not the QR secret.
- QR contains a Telegram link: staff camera scan -> open bot -> Start -> validation -> explicit Admit. Ordinary guests cannot validate/admit. Repeated or concurrent admission blocked.
- `/tickets` resends existing tickets. Undelivered tickets retry every minute after approval. A crash between a successful Telegram send and recording delivery can resend the same ticket, never create an additional entitlement.
- Separate `/var/data/dnd-live.sqlite3`; old test databases and personal UOB receipts are not migrated or used as live sales.
- Audit trail for staff actions. Daily local backups, last seven retained, plus staff `/backup` download for an off-server copy.

## Deploy on Render

Hosting is a paid background worker with a 1 GB persistent disk, one instance. Review the current price in Render before creating it. No hosting account or paid service is created merely by adding these files to GitHub.

1. Create a Render account using the `ayodhruv` GitHub account.
2. New -> Blueprint -> connect `ayodhruv/dnd-nights`, branch `main`, Blueprint Path `render.yaml`.
3. Review the worker/disk charges. The blueprint uses `rootDir: telegram-bot/live`, build `pip install -r requirements.txt`, start `python app.py`, Singapore region, disk `/var/data`.
4. Set the secret `TELEGRAM_BOT_TOKEN` in Render, privately. Keep admin ID `5117903901` (comma-separated for extra staff).
5. Add private `PAYNOW_QR_PAYLOAD` in Render. On your desktop, in the folder containing your paynow.png, run:

   In the desktop's existing telegram-bot folder, install the extraction helper (desktop only):

   ```powershell
   .\.venv\Scripts\python.exe -m pip install zxing-cpp
   Set-Clipboard (.\.venv\Scripts\python.exe -c "import zxingcpp; from PIL import Image; r=zxingcpp.read_barcode(Image.open('paynow.png')); assert r is not None, 'QR not readable'; print(r.text)")
   ```

   Paste the clipboard into Render's PAYNOW_QR_PAYLOAD variable. DELETE any old PAYNOW_QR_BASE64 variable before building: a full image as a variable can exceed Linux exec limits and cause `argument list too long` before Python even starts. The payload is the much smaller original QR text. The server checks its CRC and recreates a QR with exactly that payload; no receiving destination, amount or reference is changed. The image/payload are not in the public repo. Locally you can instead place paynow.png beside app.py.

   Set `PAYNOW_RECIPIENT_NAME` to the exact name verified when scanning your QR. Set `EVENT_TERMS` to your actual venue, admission conditions, support/refund/cancellation terms. These are shown before booking; do not invent policies.
6. Keep `SALES_OPEN=false` for the first deployment. Stop every local bot using this token before starting the worker. An existing webhook blocks startup; do not delete it without first stopping its backend.
7. In Render logs, look for `Connected @...; live ledger; sales CLOSED; capacity 230.` This is the deployment success check. No public website URL is needed for a polling bot; guests use your existing Telegram bot link.
8. In Telegram send `/start`. It is public, but /buy says bookings are closed. Send `/whoami` to check your admin ID. Staff /review should work. Do not copy the laptop test DB to the live disk.
9. Set `SALES_OPEN=true` in Render and redeploy when the receiving name, terms and service/storage configuration are confirmed. Anyone can now /buy. The first live payment must be checked against UOB before approval.
10. Verify a ticket arrives, scan with staff Telegram account and check one-time admission; keep that check-in test separate from a paying guest's entry entitlement. Do not test-admit an actual guest's ticket prematurely.
11. Run `/backup`, store it privately outside Render, and repeat after sales sessions/before event check-in. On-disk copies do not protect against losing the whole disk/account.

Automatic deploys are off: later GitHub pushes need a deliberate Render deploy. Never run a second worker/replica or local copy against a separate live ledger. GitHub does not synchronise SQLite databases.

## Staff commands

- `/review`: up to 50 awaiting payments, names, contacts, expected amount.
- `/approve ORDER BANK_TRANSACTION_REFERENCE AMOUNT`: attests staff verified UOB; issues real tickets. Replace the placeholder. Bank references are trimmed and uppercased; importers need bank-specific canonicalisation before integration.
- `/reject ORDER reason`: resolve unpaid/incorrect claims and release their hold. If money actually arrived, arrange a refund or resolve with the guest; this command does not move money.
- `/void ORDER reason`: invalidate an unadmitted paid booking. Does not refund money. Bookings with admitted guests cannot be voided to release capacity.
- `/resend ORDER`: send the same paid QRs again.
- `/check TOKEN`, or scan the ticket's Telegram link: verify paid/active/unused, then explicit Admit.
- `/reply TELEGRAM_USER_ID message`: respond to a guest who booked or used /help.
- `/backup`: private database copy containing contact details and ticket secrets; never commit it.

Guests use `/help ORDER question`. Support messages go to staff through the bot; delivery requires staff to have started the bot first. Check /review regularly even if a notification fails.

## Payment limitations

The UOB email reader in the parent folder is **not connected to live approvals** and is not run by this worker. Gmail credentials are not needed here. The email lacks payer identity, order reference and bank transaction ID; amount/time matching is not reliable buyer verification. Staff verify payment in UOB. If the bank provides no unique reference or payer/order cannot be resolved, do not invent one or approve speculatively. Resolve it with the guest.

No card or Apple Pay, automatic refund, chargeback workflow, name transfer, offline check-in or automated bank reconciliation is provided. Check-in needs internet and Telegram. The SQLite ledger is suitable for one persistent worker; horizontally scaling it needs a shared database. Holds and submitted-payment abuse can temporarily consume capacity: monitor /review and resolve false claims. No public bank data or secrets are included in the repository.

## Local use

Create a new `.venv` in this folder and install requirements. Copy `.env.example` to `.env`, set credentials locally, and leave SALES_OPEN=false until ready. Run `python app.py`. Never point a local instance at a second live database while server sales are open. Keep `.env`, `data/` and all database backups out of GitHub.

## Fast door scanner

Staff send `/scanner` in their private bot chat. Open the returned private link in Safari/Chrome, enable the camera once, then scan guest entry QRs continuously. A paid unused ticket is admitted immediately. Green means the admission transaction committed in the live Render SQLite database. Red blocks used/invalid tickets. Amber means do not admit until a live result is confirmed. Admins can use Telegram `/check` as the fallback, with the same ticket state.

The page also provides a fresh guest table: ticket number, booker name, order serial, payment status, entry status, used time and staff Telegram ID. Two-ticket bookings currently share the booker's name; individual guest names were not collected. No ticket secrets, bank references or contacts are returned by this view.

`SCANNER_URL` optionally overrides the event Site origin (HTTPS only); the default is the existing DND Nights Site. Render polls its secure door queue. `DOOR_BRIDGE_KEY` is a secret on the Site equal to SHA-256 of `dnd-door-bridge-v1:` followed by this bot's token. The token itself is never sent to the Site. Keep the Site and bot bridge configuration in sync after a token rotation. Do not add the key to this repository.

SQLite remains the ticket authority. The Site temporarily holds authenticated requests/results, not a second ticket ledger. Scanner sessions expire in 8 hours. `/scanner revoke` invalidates scanner sessions for that person. Admins can use `/grantdoor TELEGRAM_ID`, `/revokedoor TELEGRAM_ID`, and `/doorstaff` to manage scanner-only users in the same Render database. Staff first send `/whoami` in a private bot chat and give their numeric ID to an organiser. A granted user sends `/scanner` in their own private chat; they cannot approve payments, read `/backup`, or use other admin commands. Do not put door-only staff IDs in `ADMIN_USER_IDS`, which grants full admin powers. Use individual authorised staff IDs for attribution. Links grant scanner access: keep them private, sign out shared devices, and revoke them if lost.

The bot stores each scanner result transactionally with entry so a response lost during a connection interruption can be recovered with the same request ID. Concurrent scans can admit a ticket only once. Expired queued scans cannot cause delayed admissions. No offline admissions, automatic refunds, payment approvals, or drink redemptions are added by the scanner.

Tests: `python tests/test_storage.py` and `python tests/test_door.py` (temporary fictional ledgers only).
