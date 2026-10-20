DND NIGHTS STAGE 2 — TEST PAYMENT REVIEW AND QR TICKETS

UPDATE YOUR EXISTING INSTALLATION (Windows)
1. Stop bot with Ctrl+C.
2. Back up test_bookings.sqlite3 while the bot is stopped. Keep the backup private.
3. Replace ONLY bot.py and store.py with these new versions.
   Keep your existing .env, .venv and test_bookings.sqlite3.
4. Add to your existing .env:
   ADMIN_USER_IDS=5117903901
   Keep TEST_USER_IDS=5117903901 as well. Do not share the token.
5. Start: .\.venv\Scripts\python.exe bot.py
   Existing tables/bookings are retained; new tables are added automatically.

TEST THE COMPLETE FLOW — DO NOT TRANSFER MONEY
1. /orders — select 'Simulate payment submitted' for a pending booking.
2. /review — staff can see pending simulated payments.
3. Copy the /approve command shown by the bot and send it.
   Example: /approve 2010002369 TEST-2010002369 25
   Use the actual serial/amount from your review message.
4. Receive one TEST QR PNG per guest. No ticket before approval.
5. /tickets — resend the SAME tickets. /resend ORDER is a staff retry.
6. Use another device/QR reader to read the QR's text. It starts DNDTEST:.
   Send /check followed by that full text to the bot as staff.
   Reading/checking does not admit anyone. Tap 'Admit test guest'.
7. Send the same /check again. It must show ALREADY USED.
8. Try a wrong amount or the same TEST-reference on another order.
   Approval must be blocked. /reject ORDER returns a review to pending.

STAFF AND ACCESS
Both TEST_USER_IDS and ADMIN_USER_IDS are comma-separated numeric Telegram
IDs. Staff must be present in both. Only staff can review, approve, reject,
resend other guests' tickets, check or admit. Private Telegram chats only.
Only one bot process should use this token. Use the existing Python environment.

PAYMENT AND SECURITY LIMITS
This build accepts fictional TEST- references only. Approval is a staff action,
not bank verification. UOB email parsing, authenticated email validation, bank
transaction reconciliation, capacity/expiry, refunds, online scanner, scheduled
backups, always-on hosting and live event terms are NOT implemented.
Do not open real sales with this version. Every QR says TEST ONLY and is invalid
for real entry. The QR reader step is manual copy/paste in this test build.

Payments, approvals, unique QR tokens and check-ins are stored in SQLite.
Wrong amounts and reused references are blocked; a payment approval and its
tickets commit together. Admission uses an atomic update so only one concurrent
attempt succeeds. Failed delivery can be retried without re-approving or issuing
new tickets. Audit records retain staff IDs and timestamps. Test references are
trimmed and uppercased. A real importer will need bank-specific reference rules.

Order serial DDMM + daily sequence (3 digits) + first ticket label (3 digits).
Each guest gets a distinct random label and a secret random QR token. For a
2-person booking only the first label forms the order serial. Remaining labels
are assigned on approval. Labels are unique in this single-event database.
This pool has 900 labels (100..999); pending bookings also reserve labels.
Serials need event/year scoping before reusing this system for another event.

/tickets resends tickets for the latest five orders. Staff can use /resend ORDER
for older approved orders. Resending never resets admission.

The bot runs only while this computer, terminal and internet are running.
Back up the database privately; it contains contact information and ticket tokens.
Do not upload .env or databases to GitHub. Do not delete the existing database.
