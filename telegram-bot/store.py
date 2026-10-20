"""Persistent TEST bookings. No bank verification is performed here."""
import json
import secrets
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS drafts (
                    user_id INTEGER PRIMARY KEY, state TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    serial TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    day TEXT NOT NULL, seq INTEGER NOT NULL, suffix INTEGER NOT NULL UNIQUE,
                    details TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'test_pending', UNIQUE(day,seq)
                );
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def draft(self, user):
        with self.connect() as db:
            row = db.execute('SELECT * FROM drafts WHERE user_id=?', (user,)).fetchone()
            return (row['state'], json.loads(row['data'])) if row else (None, {})

    def save(self, user, state, data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO drafts VALUES (?,?,?)',
                       (user, state, json.dumps(data)))

    def clear(self, user):
        with self.connect() as db:
            db.execute('DELETE FROM drafts WHERE user_id=?', (user,))

    def create(self, user):
        now = datetime.now(ZoneInfo('Asia/Singapore'))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM drafts WHERE user_id=?', (user,)).fetchone()
            if not row or row['state'] != 'confirm':
                raise ValueError('This confirmation is old. Use /orders or /buy.')
            data = json.loads(row['data'])
            used = {r[0] for r in db.execute('SELECT suffix FROM orders')}
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tickets'").fetchone():
                used |= {r[0] for r in db.execute('SELECT label FROM tickets')}
            pool = [n for n in range(100, 1000) if n not in used]
            if not pool:
                raise ValueError('Test ticket-number pool exhausted.')
            suffix = secrets.choice(pool)
            day = now.strftime('%Y-%m-%d')
            seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM orders WHERE day=?', (day,)).fetchone()[0]
            if seq > 999:
                raise ValueError('Daily order-number limit reached.')
            serial = f'{now:%d%m}{seq:03d}{suffix:03d}'
            db.execute('INSERT INTO orders(serial,user_id,day,seq,suffix,details,created_at) VALUES(?,?,?,?,?,?,?)',
                       (serial, user, day, seq, suffix, json.dumps(data), now.isoformat()))
            db.execute('DELETE FROM drafts WHERE user_id=?', (user,))
            return serial, suffix, data

    def orders(self, user):
        with self.connect() as db:
            return db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 5', (user,)).fetchall()

    def order(self, serial):
        with self.connect() as db:
            return db.execute('SELECT * FROM orders WHERE serial=?', (serial,)).fetchone()

    def stage2(self):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS payments (
                    reference TEXT PRIMARY KEY, serial TEXT NOT NULL UNIQUE,
                    amount_cents INTEGER NOT NULL, admin_id INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    token TEXT PRIMARY KEY, serial TEXT NOT NULL, label INTEGER NOT NULL UNIQUE,
                    used_at TEXT, used_by INTEGER, delivered_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, serial TEXT, action TEXT NOT NULL,
                    actor INTEGER NOT NULL, created_at TEXT NOT NULL
                );
            ''')

    def request_review(self, serial, user):
        with self.connect() as db:
            cur = db.execute("UPDATE orders SET status='test_review' WHERE serial=? AND user_id=? AND status='test_pending'", (serial, user))
            return bool(cur.rowcount)

    def review(self):
        with self.connect() as db:
            return db.execute("SELECT * FROM orders WHERE status='test_review' ORDER BY created_at LIMIT 30").fetchall()

    def approve(self, serial, reference, amount_cents, admin):
        now = datetime.now(ZoneInfo('Asia/Singapore')).isoformat()
        reference = reference.strip().upper()
        if not reference.startswith('TEST-') or len(reference) < 6:
            raise ValueError('Use a fictional reference beginning TEST-. This build does not accept real payments.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM orders WHERE serial=?', (serial,)).fetchone()
            if not row or row['status'] != 'test_review':
                raise ValueError('Order is not awaiting review. Already-approved orders cannot be approved twice.')
            data = json.loads(row['details'])
            if amount_cents != data['price'] * data['quantity'] * 100:
                raise ValueError('Amount mismatch. Approval blocked.')
            used = {r[0] for r in db.execute('SELECT suffix FROM orders')} | {r[0] for r in db.execute('SELECT label FROM tickets')}
            labels = [row['suffix']]
            for _ in range(data['quantity'] - 1):
                pool = [n for n in range(100, 1000) if n not in used]
                if not pool:
                    raise ValueError('Ticket labels exhausted.')
                label = secrets.choice(pool)
                used.add(label)
                labels.append(label)
            try:
                db.execute('INSERT INTO payments VALUES(?,?,?,?,?)', (reference, serial, amount_cents, admin, now))
            except sqlite3.IntegrityError:
                raise ValueError('Payment reference already used. Approval blocked.') from None
            for label in labels:
                db.execute('INSERT INTO tickets(token,serial,label) VALUES(?,?,?)', (secrets.token_urlsafe(32), serial, label))
            db.execute("UPDATE orders SET status='test_approved' WHERE serial=?", (serial,))
            db.execute('INSERT INTO audit(serial,action,actor,created_at) VALUES(?,?,?,?)', (serial, 'test_approved', admin, now))
        return self.order(serial)

    def tickets(self, serial):
        with self.connect() as db:
            return db.execute('SELECT * FROM tickets WHERE serial=? ORDER BY label', (serial,)).fetchall()

    def delivered(self, token):
        with self.connect() as db:
            db.execute('UPDATE tickets SET delivered_at=? WHERE token=?', (datetime.now(ZoneInfo('Asia/Singapore')).isoformat(), token))

    def lookup(self, token):
        with self.connect() as db:
            return db.execute('SELECT tickets.*,orders.details FROM tickets JOIN orders USING(serial) WHERE token=?', (token,)).fetchone()

    def admit(self, token, admin):
        now = datetime.now(ZoneInfo('Asia/Singapore')).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cur = db.execute('UPDATE tickets SET used_at=?,used_by=? WHERE token=? AND used_at IS NULL', (now, admin, token))
            if cur.rowcount:
                row = db.execute('SELECT serial FROM tickets WHERE token=?', (token,)).fetchone()
                db.execute('INSERT INTO audit(serial,action,actor,created_at) VALUES(?,?,?,?)', (row['serial'], 'test_admitted', admin, now))
            return bool(cur.rowcount)

    def reject(self, serial, admin):
        with self.connect() as db:
            cur = db.execute("UPDATE orders SET status='test_pending' WHERE serial=? AND status='test_review'", (serial,))
            if cur.rowcount:
                db.execute('INSERT INTO audit(serial,action,actor,created_at) VALUES(?,?,?,?)', (serial, 'review_returned', admin, datetime.now(ZoneInfo('Asia/Singapore')).isoformat()))
            return bool(cur.rowcount)
