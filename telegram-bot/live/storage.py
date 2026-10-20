"""Single-event live ledger. Every payment/seat/check-in mutation is transactional."""
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Singapore')
def now(): return datetime.now(TZ)

class Ledger:
    def __init__(self, path, capacity=230, event_id='DND26', hold_minutes=30):
        self.path, self.capacity, self.event_id, self.hold_minutes = str(path), capacity, event_id, hold_minutes
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS contacts(user_id INTEGER PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS drafts(user_id INTEGER PRIMARY KEY,state TEXT NOT NULL,data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS orders(
                serial TEXT PRIMARY KEY,user_id INTEGER NOT NULL,day TEXT NOT NULL,seq INTEGER NOT NULL,
                details TEXT NOT NULL,quantity INTEGER NOT NULL,total_cents INTEGER NOT NULL,
                status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,UNIQUE(day,seq));
              CREATE TABLE IF NOT EXISTS tickets(
                token TEXT PRIMARY KEY,serial TEXT NOT NULL REFERENCES orders(serial),label INTEGER NOT NULL UNIQUE,
                used_at TEXT,used_by INTEGER,delivered_at TEXT);
              CREATE TABLE IF NOT EXISTS payments(
                reference TEXT PRIMARY KEY,serial TEXT NOT NULL UNIQUE REFERENCES orders(serial),
                amount_cents INTEGER NOT NULL,admin_id INTEGER NOT NULL,created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,serial TEXT,action TEXT NOT NULL,
                actor INTEGER NOT NULL,created_at TEXT NOT NULL,note TEXT NOT NULL DEFAULT '');
            ''')
            existing = db.execute("SELECT value FROM meta WHERE key='event_id'").fetchone()
            if existing and existing[0] != event_id:
                raise ValueError('This database belongs to a different event.')
            db.execute("INSERT OR IGNORE INTO meta VALUES('event_id',?)", (event_id,))
    def db(self):
        db=sqlite3.connect(self.path,timeout=20)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db
    def audit(self,db,serial,action,actor,note=''):
        db.execute('INSERT INTO audit(serial,action,actor,created_at,note) VALUES(?,?,?,?,?)',(serial,action,actor,now().isoformat(),note))
    def expire(self,db):
        db.execute("UPDATE orders SET status='expired' WHERE status='pending' AND expires_at<?",(now().isoformat(),))
    def draft(self,user):
        with self.db() as db:
            r=db.execute('SELECT * FROM drafts WHERE user_id=?',(user,)).fetchone()
            return (r['state'],json.loads(r['data'])) if r else (None,{})
    def save(self,user,state,data):
        with self.db() as db:db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?,?)',(user,state,json.dumps(data)))
    def clear(self,user):
        with self.db() as db:db.execute('DELETE FROM drafts WHERE user_id=?',(user,))
    def create(self,user,expected_offer):
        t=now(); day=t.strftime('%Y-%m-%d')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE'); self.expire(db)
            r=db.execute('SELECT * FROM drafts WHERE user_id=?',(user,)).fetchone()
            if not r or r['state']!='confirm':raise ValueError('This confirmation is old. Use /orders.')
            d=json.loads(r['data']);qty=d['quantity']
            if (d['tier'],d['price'])!=expected_offer:raise ValueError('The offer changed. Please start again with /buy.')
            if qty not in (1,2):raise ValueError('Invalid quantity.')
            active=db.execute("SELECT serial FROM orders WHERE user_id=? AND status IN ('pending','review','review_late')",(user,)).fetchone()
            if active:raise ValueError('You already have an unpaid booking. Use /orders or /help.')
            occupied=db.execute("SELECT COALESCE(SUM(quantity),0) FROM orders WHERE status IN ('pending','review','paid')").fetchone()[0]
            if occupied+qty>self.capacity:raise ValueError('There are not enough available tickets. Please contact /help.')
            used={r[0] for r in db.execute('SELECT label FROM tickets')}
            pool=[n for n in range(100,1000) if n not in used]
            if len(pool)<qty:raise ValueError('Ticket number pool is full. Contact /help.')
            labels=secrets.SystemRandom().sample(pool,qty)
            seq=db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM orders WHERE day=?',(day,)).fetchone()[0]
            if seq>999:raise ValueError('Daily booking limit reached. Contact /help.')
            serial=f'{self.event_id}-{t:%d%m}{seq:03d}{labels[0]:03d}'
            db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',(serial,user,day,seq,json.dumps(d),qty,d['price']*qty*100,'pending',t.isoformat(),(t+timedelta(minutes=self.hold_minutes)).isoformat()))
            for label in labels:db.execute('INSERT INTO tickets(token,serial,label) VALUES(?,?,?)',(secrets.token_urlsafe(32),serial,label))
            self.audit(db,serial,'created',user)
            db.execute('DELETE FROM drafts WHERE user_id=?',(user,))
        return self.order(serial)
    def order(self,serial):
        with self.db() as db:
            self.expire(db)
            return db.execute('SELECT * FROM orders WHERE serial=?',(serial,)).fetchone()
    def orders(self,user):
        with self.db() as db:
            self.expire(db)
            return db.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created_at DESC',(user,)).fetchall()
    def tickets(self,serial):
        with self.db() as db:return db.execute('SELECT * FROM tickets WHERE serial=? ORDER BY label',(serial,)).fetchall()
    def submit(self,serial,user):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self.expire(db)
            r=db.execute('SELECT * FROM orders WHERE serial=? AND user_id=?',(serial,user)).fetchone()
            if not r or r['status'] not in ('pending','expired'):raise ValueError('This booking is already submitted or unavailable.')
            status='review' if r['status']=='pending' else 'review_late'
            db.execute('UPDATE orders SET status=? WHERE serial=?',(status,serial));self.audit(db,serial,'payment_claimed',user)
            return status
    def queue(self):
        with self.db() as db:return db.execute("SELECT * FROM orders WHERE status IN ('review','review_late') ORDER BY created_at LIMIT 50").fetchall()
    def approve(self,serial,reference,amount,admin):
        ref=reference.strip().upper()
        if not 4<=len(ref)<=120 or ref.startswith('TEST-'):raise ValueError('Use the actual bank transaction reference, not a TEST reference.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self.expire(db)
            r=db.execute('SELECT * FROM orders WHERE serial=?',(serial,)).fetchone()
            if not r or r['status'] not in ('review','review_late'):raise ValueError('Order is not awaiting review, or is already approved.')
            if r['total_cents']!=amount:raise ValueError('Amount mismatch. Approval blocked.')
            occupied=db.execute("SELECT COALESCE(SUM(quantity),0) FROM orders WHERE status IN ('pending','review','paid') AND serial<>?",(serial,)).fetchone()[0]
            if occupied+r['quantity']>self.capacity:raise ValueError('Capacity reached. Do not issue a ticket; resolve this payment with the guest.')
            try:db.execute('INSERT INTO payments VALUES(?,?,?,?,?)',(ref,serial,amount,admin,now().isoformat()))
            except sqlite3.IntegrityError:raise ValueError('Bank reference already used. Approval blocked.') from None
            db.execute("UPDATE orders SET status='paid' WHERE serial=?",(serial,));self.audit(db,serial,'bank_verified',admin,ref)
        return self.order(serial)
    def reject(self,serial,admin,note):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute('SELECT * FROM orders WHERE serial=?',(serial,)).fetchone()
            if not r or r['status'] not in ('pending','review','review_late','expired'):raise ValueError('Booking cannot be rejected in this state.')
            db.execute("UPDATE orders SET status='rejected' WHERE serial=?",(serial,));self.audit(db,serial,'rejected',admin,note)
            return r
    def void(self,serial,admin,note):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute("SELECT * FROM orders WHERE serial=? AND status='paid'",(serial,)).fetchone()
            if not r:raise ValueError('Only paid bookings can be voided.')
            if db.execute('SELECT 1 FROM tickets WHERE serial=? AND used_at IS NOT NULL',(serial,)).fetchone():raise ValueError('This booking has admitted guests. Do not release their seats by voiding it.')
            db.execute("UPDATE orders SET status='void' WHERE serial=?",(serial,));self.audit(db,serial,'voided',admin,note)
            return r
    def lookup(self,token):
        with self.db() as db:return db.execute('SELECT tickets.*,orders.details,orders.status FROM tickets JOIN orders USING(serial) WHERE token=?',(token,)).fetchone()
    def admit(self,token,admin):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            cur=db.execute("UPDATE tickets SET used_at=?,used_by=? WHERE token=? AND used_at IS NULL AND serial IN (SELECT serial FROM orders WHERE status='paid')",(now().isoformat(),admin,token))
            if cur.rowcount:
                serial=db.execute('SELECT serial FROM tickets WHERE token=?',(token,)).fetchone()[0];self.audit(db,serial,'admitted',admin)
            return bool(cur.rowcount)
    def delivered(self,token):
        with self.db() as db:db.execute('UPDATE tickets SET delivered_at=? WHERE token=?',(now().isoformat(),token))
    def undelivered(self):
        with self.db() as db:return db.execute("SELECT DISTINCT orders.* FROM orders JOIN tickets USING(serial) WHERE status='paid' AND delivered_at IS NULL LIMIT 10").fetchall()
    def backup(self,path):
        with self.db() as source, sqlite3.connect(path) as target:source.backup(target)

    def remember(self,user):
        with self.db() as db:db.execute('INSERT OR IGNORE INTO contacts VALUES(?)',(user,))
    def known(self,user):
        with self.db() as db:return bool(db.execute('SELECT 1 FROM contacts WHERE user_id=?',(user,)).fetchone())
