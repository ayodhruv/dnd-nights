# DND Nights admin dashboard (P0, staging)

Black-and-gold Telegram-authenticated admin dashboard for the existing **live Python bot ledger**. This branch does not change the bot or its Render production deployment.

## Current scope
- Telegram login with server-side verification and numeric admin allowlist.
- Owner/admin identity, overview with actual ledger metrics, order search and status filtering.
- Browser camera QR scanner that calls **the existing** transaction-safe `Ledger.door_admit` method.
- No payment verification or approval actions in this P0 slice. The current `approve_matched` combines verification and issuance; this must be refactored to a two-person sequence before exposing approval UI.
- The existing `/approve` command still works unchanged on production. It must be gated in the follow-up before assuming that only owner-verified orders can be approved.

## Setup (local development with a COPY of the live database)
Use Python 3.12. From repository root:

```bash
pip install -r admin-dashboard/requirements.txt
export DASHBOARD_DB_PATH=/path/to/private/backup.sqlite3
export ADMIN_USER_IDS=123456789,234567890
export DASHBOARD_OWNER_IDS=123456789
export TELEGRAM_BOT_TOKEN=your-real-bot-token
export TELEGRAM_BOT_USERNAME=your_bot_username
export DASHBOARD_ORIGIN=https://your-dashboard.example.com
uvicorn --app-dir admin-dashboard app:app --host 127.0.0.1 --port 8000
```

Telegram Login requires its domain registered with BotFather. Use HTTPS, or a trusted local HTTPS tunnel for development. Avoid placing secrets or database backups into GitHub.

## Deployment caveat (important)
The bot is a Render **background worker** with SQLite at `/var/data/dnd-live.sqlite3` on its persistent disk. A second Render web service cannot mount that worker's same disk. Do **not** deploy this dashboard as a separate web service and assume the file exists. First co-locate an HTTP server with the live worker in one service/process group, or implement a bot-owned authenticated RPC API. The production bot's Render autoDeployTrigger is off. Never change production wiring without staging and backup verification.

## Before production
- Replace in-memory `sessions` with persistent hashed sessions and appropriate expiry/revocation, plus CSRF defense on all mutating routes.
- Gate direct `/approve` behind owner bank verification evidence, preserving idempotency.
- Introduce `payment_verified` record and actor separation, with audit trail.
- End-to-end tests against staging copy for 2 admins racing to approve and to check-in.
- Use safe migrations, backups, and avoid admin PII in logs.
- Validate door QR payloads against actual generated tickets and test browser permissions.
- Configure all 4 numeric Telegram admin IDs, with owner ID designated.
