"""Single-event live ledger. Every payment/seat/check-in mutation is transactional."""
import json
import hashlib
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Singapore')
def now(): return datetime.now(TZ)
def bank_name(value):
    name=' '.join(unicodedata.normalize('NFKC',value).split())
    if not 2<=len(name)<=80 or not any(c.isalpha() for c in name):
        raise ValueError('Enter the full name shown for the paying bank account (2–80 characters).')
    return name
def name_key(value):return bank_name(value).casefold()

class Ledger:
    def __init__(self, path, capacity=230, event_id='DND26', hold_minutes=30):
        self.path, self.capacity, self.event_id, self.hold_minutes = str(path), capacity, event_id, hold_minutes
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS door_requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS door_staff(user_id INTEGER PRIMARY KEY,granted_by INTEGER NOT NULL,created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS contacts(user_id INTEGER PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS promoters(code TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
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
              CREATE TABLE IF NOT EXISTS payment_evidence(
                serial TEXT PRIMARY KEY REFERENCES orders(serial),sender_name TEXT NOT NULL,
                bank_date TEXT NOT NULL,match_key TEXT NOT NULL UNIQUE);
              CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,serial TEXT,action TEXT NOT NULL,
                actor INTEGER NOT NULL,created_at TEXT NOT NULL,note TEXT NOT NULL DEFAULT '');
            ''')
            existing = db.execute("SELECT value FROM meta WHERE key='event_id'").fetchone()
            if existing and existing[0] != event_id:
                raise ValueError('This database belongs to a different event.')
            db.execute("INSERT OR IGNORE INTO meta VALUES('event_id',?)", (event_id,))
            # Starting roster from the DND Promoters sheet; later codes can be added by staff.
            for code,name in (('DND-ADEEP','Adeep'),('DND-NIRBHAY','Nirbhay')):
                db.execute('INSERT OR IGNORE INTO promoters VALUES(?,?,?)',(code,name,now().isoformat()))
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
            if type(qty) is not int or not 1<=qty<=10:raise ValueError('Choose 1 to 10 tickets.')
            if d.get('source')=='Promoter':
                code=d.get('promoter_code','').strip().upper()
                if not db.execute('SELECT 1 FROM promoters WHERE code=?',(code,)).fetchone():
                    raise ValueError('Unknown promoter code. Ask your promoter for their code.')
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
    def set_payer(self,serial,user,payer):
        payer=bank_name(payer)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self.expire(db)
            r=db.execute('SELECT * FROM orders WHERE serial=? AND user_id=?',(serial,user)).fetchone()
            if not r or r['status'] not in ('pending','expired','review','review_late'):
                raise ValueError('This order cannot change its payer. Use /orders or /help.')
            details=json.loads(r['details']);details['payer_name']=payer
            db.execute('UPDATE orders SET details=? WHERE serial=?',(json.dumps(details),serial))
            self.audit(db,serial,'payer_identified',user,payer)
            return r['status']
    def approve_matched(self,serial,sender,bank_date,amount,admin):
        sender=bank_name(sender)
        try:day=date.fromisoformat(bank_date)
        except ValueError:raise ValueError('Use the bank date as YYYY-MM-DD, as shown in UOB.') from None
        if day.isoformat()!=bank_date or day>now().date():
            raise ValueError('Use a real incoming transaction date shown in UOB, not a future date.')
        match_key=hashlib.sha256(f'{day.isoformat()}|{amount}|{name_key(sender)}'.encode()).hexdigest()
        # An internal reconciliation key, expressly not a bank-issued reference.
        return self.approve(serial,'MANUAL-UOB-'+match_key,amount,admin,(sender,day.isoformat(),match_key))
    def approve(self,serial,reference,amount,admin,evidence=None):
        ref=reference.strip().upper()
        if not 4<=len(ref)<=120 or ref.startswith('TEST-'):raise ValueError('Use the actual bank transaction reference, not a TEST reference.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE');self.expire(db)
            r=db.execute('SELECT * FROM orders WHERE serial=?',(serial,)).fetchone()
            if not r or r['status'] not in ('review','review_late'):raise ValueError('Order is not awaiting review, or is already approved.')
            if r['total_cents']!=amount:raise ValueError('Amount mismatch. Approval blocked.')
            if evidence:
                declared=json.loads(r['details'])
                expected=declared.get('payer_name') or declared['name']
                if name_key(expected)!=name_key(evidence[0]):
                    raise ValueError('Sender name differs from the declared payer. Ask the guest to send /payer ORDER FULL_BANK_NAME, then verify in UOB again.')
            occupied=db.execute("SELECT COALESCE(SUM(quantity),0) FROM orders WHERE status IN ('pending','review','paid') AND serial<>?",(serial,)).fetchone()[0]
            if occupied+r['quantity']>self.capacity:raise ValueError('Capacity reached. Do not issue a ticket; resolve this payment with the guest.')
            try:db.execute('INSERT INTO payments VALUES(?,?,?,?,?)',(ref,serial,amount,admin,now().isoformat()))
            except sqlite3.IntegrityError:
                raise ValueError('This payer, amount and bank date were already matched to another order. Check for a distinct second credit in UOB; do not approve this one yet.') from None
            if evidence:
                db.execute('INSERT INTO payment_evidence(serial,sender_name,bank_date,match_key) VALUES(?,?,?,?)',(serial,*evidence))
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

    def promoter(self,code):
        with self.db() as db:return db.execute('SELECT * FROM promoters WHERE code=?',(code.strip().upper(),)).fetchone()
    def add_promoter(self,code,name,admin):
        code=code.strip().upper();name=name.strip()
        if not re.fullmatch(r'DND-[A-Z0-9-]{2,32}',code) or not 2<=len(name)<=80:
            raise ValueError('Use /addpromoter DND-CODE Promoter name.')
        with self.db() as db:
            try:db.execute('INSERT INTO promoters VALUES(?,?,?)',(code,name,now().isoformat()))
            except sqlite3.IntegrityError:raise ValueError('That promoter code already exists.') from None
            self.audit(db,None,'promoter_added',admin,code)
    def promoter_stats(self):
        with self.db() as db:
            promoters=[dict(r) for r in db.execute('SELECT code,name FROM promoters ORDER BY name')]
            for p in promoters:p.update(booked=0,paid=0,checked_in=0)
            index={p['code']:p for p in promoters}
            for r in db.execute("SELECT details,quantity,status,serial FROM orders WHERE status IN ('pending','review','review_late','paid')"):
                code=json.loads(r['details']).get('promoter_code','')
                if code not in index:continue
                index[code]['booked']+=r['quantity']
                if r['status']=='paid':
                    index[code]['paid']+=r['quantity']
                    index[code]['checked_in']+=db.execute('SELECT COUNT(*) FROM tickets WHERE serial=? AND used_at IS NOT NULL',(r['serial'],)).fetchone()[0]
            return promoters

    def door_authorized(self,user,admins):
        if user in admins:return True
        with self.db() as db:return bool(db.execute('SELECT 1 FROM door_staff WHERE user_id=?',(user,)).fetchone())
    def grant_door(self,user,admin):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO door_staff(user_id,granted_by,created_at) VALUES(?,?,?)',(user,admin,now().isoformat()))
            self.audit(db,None,'door_staff_granted',admin,str(user))
    def revoke_door(self,user,admin):
        with self.db() as db:
            cur=db.execute('DELETE FROM door_staff WHERE user_id=?',(user,))
            if cur.rowcount:self.audit(db,None,'door_staff_revoked',admin,str(user))
            return bool(cur.rowcount)
    def door_staff_list(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT user_id,granted_by,created_at FROM door_staff ORDER BY created_at')]

    def door_admit(self, request_id, token, admin, created):
        """Persist the result with admission; retrying a lost response is safe."""
        import time
        import hashlib
        fingerprint=hashlib.sha256(f'{admin}:{token}'.encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT fingerprint,result FROM door_requests WHERE id=?',(request_id,)).fetchone()
            if old:
                return json.loads(old['result']) if old['fingerprint']==fingerprint else {'status':'conflict'}
            result={'status':'expired'}
            if 0<=time.time()-float(created)<=12:
                r=db.execute('SELECT tickets.*,orders.details,orders.status FROM tickets JOIN orders USING(serial) WHERE token=?',(token,)).fetchone()
                if not r or r['status']!='paid':result={'status':'invalid'}
                else:
                    result={'status':'used' if r['used_at'] else 'admitted','label':r['label'],
                            'booker_name':json.loads(r['details']).get('name',''),
                            'serial':r['serial'],'used_at':r['used_at']}
                    if not r['used_at']:
                        stamp=now().isoformat()
                        db.execute('UPDATE tickets SET used_at=?,used_by=? WHERE token=?',(stamp,admin,token))
                        self.audit(db,r['serial'],'admitted',admin,'Door scanner request '+request_id)
                        result['used_at']=stamp
            db.execute('INSERT INTO door_requests(id,fingerprint,result) VALUES(?,?,?)',(request_id,fingerprint,json.dumps(result)))
            return result

    def door_guests(self):
        """A fresh staff view; never return ticket secrets or bank details."""
        with self.db() as db:
            self.expire(db)
            rows=db.execute('SELECT tickets.label,tickets.used_at,tickets.used_by,orders.serial,orders.details,orders.status FROM tickets JOIN orders USING(serial) ORDER BY orders.created_at DESC,tickets.label LIMIT 1500').fetchall()
            return {'status':'ok','updated_at':now().isoformat(),'guests':[
                {'label':r['label'],'booker_name':json.loads(r['details']).get('name',''),
                 'serial':r['serial'],'payment_status':r['status'],
                 'entry_status':'Used' if r['used_at'] else ('Ready' if r['status']=='paid' else 'Not valid'),
                 'used_at':r['used_at'],'used_by':r['used_by']} for r in rows]}
