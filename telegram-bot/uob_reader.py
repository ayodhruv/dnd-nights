"""Read-only Gmail receipt importer. Never changes bookings or issues tickets."""
import argparse
import hashlib
import imaplib
import os
import re
import sqlite3
import ssl
from datetime import datetime, timedelta
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
SENDER = 'unialerts@uobgroup.com'
SUBJECT = 'UOB-PayNow transfer received'
PATTERN = re.compile(r'You have received SGD ([0-9]+(?:,[0-9]{3})*\.[0-9]{2}) in your PayNow-linked account ending ([0-9]{4}) on ([0-9]{2}-[A-Z]{3}-[0-9]{4}) ([0-9]{1,2}:[0-9]{2}[AP]M)\.', re.I)

def parse_receipt(raw):
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    senders = getaddresses(msg.get_all('From', []))
    if len(senders) != 1 or senders[0][1].lower() != SENDER or str(msg.get('Subject', '')).strip() != SUBJECT:
        raise ValueError('Sender or subject does not match the expected UOB notification.')
    parts = [p for p in msg.walk() if p.get_content_type() == 'text/plain' and p.get_content_disposition() != 'attachment']
    body = '\n'.join(p.get_content() for p in parts)
    matches = PATTERN.findall(body)
    if len(matches) != 1:
        raise ValueError('Unexpected email format; manual review required.')
    amount, account, day, clock = matches[0]
    paid_at = datetime.strptime(day.upper() + ' ' + clock.upper(), '%d-%b-%Y %I:%M%p').replace(tzinfo=ZoneInfo('Asia/Singapore')).isoformat()
    amount_cents = int(Decimal(amount.replace(',', '')) * 100)
    if amount_cents <= 0:
        raise ValueError('Non-positive receipt amount.')
    # A diagnostic only: does NOT independently authenticate an uploaded EML.
    # Only the first Authentication-Results header is considered. No automatic approvals.
    headers = msg.get_all('Authentication-Results', [])
    auth = str(headers[0]) if headers else ''
    gmail_pass = bool(re.match(r'^\s*mx\.google\.com\s*;', auth, re.I)
        and re.search(r'\bdkim=pass\b[^;]*header\.i=@uobgroup\.com\b', auth, re.I)
        and re.search(r'\bdmarc=pass\b[^;]*header\.from=uobgroup\.com\b', auth, re.I))
    message_id = str(msg.get('Message-ID', '')).strip()
    if not message_id:
        raise ValueError('Message-ID missing; manual review required.')
    fingerprint = hashlib.sha256(f'{account}|{paid_at}|{amount_cents}'.encode()).hexdigest()
    return dict(message_id=message_id, amount_cents=amount_cents, account=account,
        paid_at=paid_at, fingerprint=fingerprint,
        auth_note='gmail_headers_pass' if gmail_pass else 'authentication_review_required')

def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS receipts (
        id INTEGER PRIMARY KEY, message_id TEXT NOT NULL UNIQUE,
        amount_cents INTEGER NOT NULL, account TEXT NOT NULL, paid_at TEXT NOT NULL,
        fingerprint TEXT NOT NULL, auth_note TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'needs_bank_match', imported_at TEXT NOT NULL
    )''')
    db.commit()
    return db

def record(db, receipt):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM receipts WHERE message_id=?', (receipt['message_id'],)).fetchone():
            return 'duplicate_email'
        collision = db.execute('SELECT 1 FROM receipts WHERE fingerprint=?', (receipt['fingerprint'],)).fetchone()
        status = 'possible_duplicate_review' if collision else 'needs_bank_match'
        db.execute('''INSERT INTO receipts(message_id,amount_cents,account,paid_at,fingerprint,auth_note,status,imported_at)
            VALUES(:message_id,:amount_cents,:account,:paid_at,:fingerprint,:auth_note,:status,:imported_at)''',
            {**receipt, 'status': status, 'imported_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat()})
        return status

def fetch_gmail(db):
    address = os.getenv('GMAIL_ADDRESS', '').strip()
    password = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '').strip()
    if not address or not password:
        raise ValueError('Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to the .env beside this script.')
    since = (datetime.now(ZoneInfo('Asia/Singapore')) - timedelta(days=30)).strftime('%d-%b-%Y')
    imported = duplicate = held = failed = 0
    with imaplib.IMAP4_SSL('imap.gmail.com', 993, ssl_context=ssl.create_default_context(), timeout=30) as mail:
        mail.login(address, password)
        # EXAMINE + BODY.PEEK: no read flags, deletions, labels, or outgoing emails.
        status, _ = mail.select('INBOX', readonly=True)
        if status != 'OK':
            raise ValueError('Could not open Gmail inbox.')
        status, result = mail.uid('search', None, 'SINCE', since, 'FROM', '"' + SENDER + '"', 'SUBJECT', '"' + SUBJECT + '"')
        if status != 'OK':
            raise ValueError('Gmail search failed.')
        ids = result[0].split()
        print(f'Found {len(ids)} matching inbox emails in the last 30 days.')
        for uid in ids:
            status, response = mail.uid('fetch', uid, '(BODY.PEEK[])')
            blobs = [r[1] for r in response if isinstance(r, tuple)] if status == 'OK' else []
            if len(blobs) != 1:
                failed += 1
                continue
            try:
                receipt = parse_receipt(blobs[0])
                expected = os.getenv('UOB_ACCOUNT_LAST4', '').strip()
                if expected and receipt['account'] != expected:
                    held += 1
                    continue
                outcome = record(db, receipt)
                if outcome == 'duplicate_email':
                    duplicate += 1
                else:
                    imported += 1
                    print(f"Recorded S${receipt['amount_cents']/100:.2f} | {receipt['paid_at']} | {outcome} | {receipt['auth_note']}")
            except (ValueError, TypeError, UnicodeError):
                held += 1
        print(f'New receipts: {imported}; duplicate emails skipped: {duplicate}; unparsed/other-account emails: {held}; fetch failures: {failed}.')
    print('No tickets issued and no payments assigned to bookings. New mail requires another run.')

def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eml', type=Path, help='Offline parser test; never logs into Gmail')
    parser.add_argument('--list', action='store_true', help='List the last 20 recorded receipts without connecting')
    args = parser.parse_args()
    try:
        with connect(ROOT / 'uob_receipts.sqlite3') as db:
            if args.list:
                for row in db.execute('SELECT * FROM receipts ORDER BY id DESC LIMIT 20'):
                    print(f"#{row['id']} | S${row['amount_cents']/100:.2f} | {row['paid_at']} | {row['status']} | {row['auth_note']}")
            elif args.eml:
                receipt = parse_receipt(args.eml.read_bytes())
                print(f"OFFLINE TEST: S${receipt['amount_cents']/100:.2f} | {receipt['paid_at']} | {receipt['auth_note']}")
                print('No receipt stored. Uploaded files and their headers are not independent proof of payment.')
            else:
                fetch_gmail(db)
    except imaplib.IMAP4.error:
        print('Gmail login or IMAP request failed. Check the Gmail address and app password locally. Do not send credentials here.')
        raise SystemExit(1)
    except (OSError, TimeoutError):
        print('Connection or file access failed. Check internet/file path and try again. No tickets were issued.')
        raise SystemExit(1)
    except ValueError as exc:
        print(str(exc))
        raise SystemExit(1)

if __name__ == '__main__':
    main()
