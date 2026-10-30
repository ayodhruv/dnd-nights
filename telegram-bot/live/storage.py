"""Single-event live ledger. Every payment/seat/check-in mutation is transactional."""
import json
import hashlib
import re
import secrets
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Singapore')
def now(): return datetime.now(TZ)
def bank_name(value):
    name=' '.join(unicodedata.normalize('NFKC',value).split())
    if not 2<=len(name)<=80 or not any(c.isalpha() for c in name):
        raise ValueError('Enter the full name shown for the paying bank account (2–80 characters).')
    return name
def name_key(value):return bank_name(value).casefold()

PROMOTERS=(('ADEEP','Adeep'),('NIRBHAY','Nirbhay'),('ISHWAR','Ishwar'),
           ('SHALU','Shalu'),('AUSTIN','Austin'),('AIRA','Ira'),
           ('JESWANT','Jeswant'),('AESHA','Aesha'),('MEERA','Meera'),
           ('HREHAN','Hrehan'),('DHRUV','Dhruv'),('NIHEELA','Niheela'),('SACHIN','Sachin'))
PROMO_LIMIT=100

class Ledger:
    def __init__(self, path, capacity=230, event_id='DND26', hold_minutes=30):
        self.path, self.capacity, self.event_id, self.hold_minutes = str(path), capacity, event_id, hold_minutes
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._backup_before_campaign()
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS door_requests(id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS door_staff(user_id INTEGER PRIMARY KEY,granted_by INTEGER NOT NULL,created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS contacts(user_id INTEGER PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS promoters(code TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL,
                discount_percent INTEGER NOT NULL DEFAULT 0);
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
              CREATE TABLE IF NOT EXISTS drink_benefits(
                token TEXT PRIMARY KEY REFERENCES tickets(token),granted_at TEXT NOT NULL,
                claimed_at TEXT,claimed_by INTEGER);
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
            db.execute("INSERT OR IGNORE INTO meta VALUES('promoter_discounts_enabled','false')")
            # Preserve old orders and promoter attribution while migrating the live SQLite file.
            if 'discount_percent' not in {r['name'] for r in db.execute('PRAGMA table_info(promoters)')}:
                db.execute('ALTER TABLE promoters ADD COLUMN discount_percent INTEGER NOT NULL DEFAULT 0')
            # Older codes remain in the ledger for historical orders, but cannot start new discounted bookings.
            for code,name in (('DND-ADEEP','Adeep'),('DND-NIRBHAY','Nirbhay')):
                db.execute('INSERT OR IGNORE INTO promoters(code,name,created_at) VALUES(?,?,?)',(code,name,now().isoformat()))
            # Keep historical NAME20 rows and orders; only FREE/10 codes accept new bookings.
            for stem,name in PROMOTERS:
                for suffix,discount in (('FREE',0),('10',10)):
                    db.execute('INSERT OR IGNORE INTO promoters(code,name,created_at,discount_percent) VALUES(?,?,?,?)',
                               (stem+suffix,name,now().isoformat(),discount))
            if not db.execute("SELECT 1 FROM meta WHERE key='promo_campaign_v1'").fetchone():
                db.execute("INSERT INTO meta VALUES('promo_campaign_v1',?)",(now().isoformat(),))
                db.execute("UPDATE meta SET value='true' WHERE key='promoter_discounts_enabled'")
                self.audit(db,None,'promoter_campaign_launched',0,'First 100 approved tickets; NAMEFREE then NAME10')
    def _backup_before_campaign(self):
        path=Path(self.path)
        if not path.exists():return
        with sqlite3.connect(self.path) as source:
            try:launched=source.execute("SELECT 1 FROM meta WHERE key='promo_campaign_v1'").fetchone()
            except sqlite3.OperationalError:launched=None
            if launched:return
            folder=path.parent/'backups';folder.mkdir(exist_ok=True,mode=0o700)
            target=folder/f'pre-promoter-launch-{now():%Y%m%d-%H%M%S-%f}.sqlite3'
            with sqlite3.connect(target) as backup:source.backup(backup)
            target.chmod(0o600)
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
    @staticmethod
    def _approved_count(db):
        # Payment rows survive voids, so a used-up promotion cannot reopen after a cancellation.
        return db.execute('SELECT COALESCE(SUM(o.quantity),0) FROM orders o JOIN payments p USING(serial)').fetchone()[0]
    def campaign(self):
        with self.db() as db:
            count=self._approved_count(db)
            return dict(approved=count,remaining=max(0,PROMO_LIMIT-count),free_open=count<PROMO_LIMIT,
                        discount_open=count>=PROMO_LIMIT and self._promoter_discounts_enabled(db),
                        drinks_granted=db.execute('SELECT COUNT(*) FROM drink_benefits').fetchone()[0])
    def sales_offer(self,today,event):
        if today>event:return None
        if today==event:return 'Walk-in',35
        with self.db() as db:
            return ('Early bird',25) if self._approved_count(db)<PROMO_LIMIT else ('General',30)
    @staticmethod
    def _promoter(db,code):
        code=code.strip().upper()
        r=db.execute('SELECT * FROM promoters WHERE code=?',(code,)).fetchone()
        if not r or not ((code.endswith('FREE') and r['discount_percent']==0) or
                         (code.endswith('10') and r['discount_percent']==10)):return None
        return r
    def _quote(self,db,code,expected_offer):
        tier,base=expected_offer
        count=self._approved_count(db)
        if tier=='Early bird' and count>=PROMO_LIMIT:
            raise ValueError('Early bird has ended. New bookings are at the general price. Please restart with /buy; existing orders keep their quoted total.')
        result=dict(price_cents=base*100,discount_percent=0,promotion=None)
        if not code:return result
        p=self._promoter(db,code)
        if not p:raise ValueError('That referral code is not recognised. Check with your promoter, or tap ← Back to choose another source. Old NAME20 codes are no longer valid for new bookings.')
        if p['code'].endswith('FREE'):
            if count>=PROMO_LIMIT:raise ValueError('The first-100 free-drink offer has ended. Ask your promoter about current offers, or tap ← Back to choose another source.')
            result['promotion']='free_drink'
        else:
            if count<PROMO_LIMIT or not self._promoter_discounts_enabled(db):
                raise ValueError('This code is not active yet. Check with your promoter, or tap ← Back to choose another source.')
            result.update(discount_percent=10,price_cents=base*90,promotion='discount')
        result['promoter_code']=p['code']
        return result
    def quote(self,code,expected_offer):
        with self.db() as db:return self._quote(db,code,expected_offer)
    def create(self,user,expected_offer):
        t=now(); day=t.strftime('%Y-%m-%d')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE'); self.expire(db)
            r=db.execute('SELECT * FROM drafts WHERE user_id=?',(user,)).fetchone()
            if not r or r['state']!='confirm':raise ValueError('This confirmation is old. Use /orders.')
            d=json.loads(r['data']);qty=d['quantity']
            tier,base_price=expected_offer
            if d['tier']!=tier:raise ValueError('The offer changed. Please start again with /buy.')
            if type(qty) is not int or not 1<=qty<=10:raise ValueError('Choose 1 to 10 tickets.')
            if d.get('source')=='Promoter':
                if not d.get('promoter_code'):raise ValueError('Enter a valid promoter code or go back and choose another source.')
            elif d.get('promoter_code'):
                raise ValueError('Please start again with /buy to choose your referral source.')
            quote=self._quote(db,d.get('promoter_code'),expected_offer)
            # Accept an in-progress legacy draft only when its price still matches today's rules.
            quoted_cents=d.get('price_cents')
            if quoted_cents is None:quoted_cents=int(Decimal(str(d.get('price',0)))*100)
            if quoted_cents!=quote['price_cents']:raise ValueError('The ticket price changed. Please start again with /buy.')
            d.update(quote);d.pop('price',None)
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
            db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',(serial,user,day,seq,json.dumps(d),qty,quote['price_cents']*qty,'pending',t.isoformat(),(t+timedelta(minutes=self.hold_minutes)).isoformat()))
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
        with self.db() as db:return db.execute('SELECT t.*,b.token IS NOT NULL AS free_drink,b.claimed_at AS drink_claimed_at FROM tickets t LEFT JOIN drink_benefits b USING(token) WHERE serial=? ORDER BY label',(serial,)).fetchall()
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
            approved_before=self._approved_count(db)
            try:db.execute('INSERT INTO payments VALUES(?,?,?,?,?)',(ref,serial,amount,admin,now().isoformat()))
            except sqlite3.IntegrityError:
                raise ValueError('This payer, amount and bank date were already matched to another order. Check for a distinct second credit in UOB; do not approve this one yet.') from None
            if evidence:
                db.execute('INSERT INTO payment_evidence(serial,sender_name,bank_date,match_key) VALUES(?,?,?,?)',(serial,*evidence))
            details=json.loads(r['details'])
            drinks=min(r['quantity'],max(0,PROMO_LIMIT-approved_before)) if details.get('promotion')=='free_drink' else 0
            if drinks:
                tokens=db.execute('SELECT token FROM tickets WHERE serial=? ORDER BY label LIMIT ?',(serial,drinks)).fetchall()
                for t in tokens:db.execute('INSERT INTO drink_benefits(token,granted_at) VALUES(?,?)',(t['token'],now().isoformat()))
            details.update(approval_position_start=approved_before+1,approval_position_end=approved_before+r['quantity'],free_drinks_awarded=drinks)
            db.execute("UPDATE orders SET status='paid',details=? WHERE serial=?",(json.dumps(details),serial))
            self.audit(db,serial,'bank_verified',admin,ref)
            if approved_before<PROMO_LIMIT<=approved_before+r['quantity']:
                self.audit(db,serial,'first_100_closed',admin,'General price active; NAMEFREE closed; NAME10 enabled unless manually paused')
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
        with self.db() as db:return db.execute('SELECT t.*,o.details,o.status,b.token IS NOT NULL AS free_drink,b.claimed_at AS drink_claimed_at FROM tickets t JOIN orders o USING(serial) LEFT JOIN drink_benefits b USING(token) WHERE token=?',(token,)).fetchone()
    def redeem_drink(self,token,admin):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            r=db.execute('SELECT t.serial,t.label,o.status,b.claimed_at FROM tickets t JOIN orders o USING(serial) JOIN drink_benefits b USING(token) WHERE token=?',(token,)).fetchone()
            if not r or r['status']!='paid':raise ValueError('No active free drink is attached to this ticket.')
            if r['claimed_at']:raise ValueError('This free drink has already been redeemed.')
            db.execute('UPDATE drink_benefits SET claimed_at=?,claimed_by=? WHERE token=? AND claimed_at IS NULL',(now().isoformat(),admin,token))
            self.audit(db,r['serial'],'drink_redeemed',admin,f"Ticket #{r['label']:03d}")
            return r['label']
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

    @staticmethod
    def _promoter_discounts_enabled(db):
        row=db.execute("SELECT value FROM meta WHERE key='promoter_discounts_enabled'").fetchone()
        return bool(row and row[0]=='true')
    def promoter_discounts_enabled(self):
        return self.campaign()['discount_open']
    def set_promoter_discounts(self,enabled,admin):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("INSERT INTO meta(key,value) VALUES('promoter_discounts_enabled',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",('true' if enabled else 'false',))
            self.audit(db,None,'promoter_discounts_on' if enabled else 'promoter_discounts_off',admin)
    def promoter(self,code):
        with self.db() as db:return self._promoter(db,code)
    def add_promoter(self,code,name,admin):
        code=code.strip().upper();name=name.strip()
        stem=code[:-4] if code.endswith('FREE') else code[:-2] if code.endswith('10') else code
        if not re.fullmatch(r'[A-Z][A-Z0-9-]{1,26}',stem) or stem.endswith('20') or not 2<=len(name)<=80:
            raise ValueError('Use /addpromoter NAME Promoter full name. This creates NAMEFREE and NAME10.')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM promoters WHERE code IN (?,?)',(stem+'FREE',stem+'10')).fetchone():
                raise ValueError('That promoter already has campaign codes.')
            for suffix,discount in (('FREE',0),('10',10)):
                db.execute('INSERT INTO promoters(code,name,created_at,discount_percent) VALUES(?,?,?,?)',(stem+suffix,name,now().isoformat(),discount))
            self.audit(db,None,'promoter_added',admin,stem)
        return stem
    def promoter_stats(self):
        with self.db() as db:
            promoters=[dict(code=r['code'][:-4],name=r['name']) for r in db.execute("SELECT code,name FROM promoters WHERE code LIKE '%FREE' ORDER BY name")]
            for p in promoters:p.update(booked=0,paid=0,checked_in=0)
            index={p['code']:p for p in promoters}
            for r in db.execute("SELECT details,quantity,status,serial FROM orders WHERE status IN ('pending','review','review_late','paid')"):
                code=json.loads(r['details']).get('promoter_code','')
                code=code[:-4] if code.endswith('FREE') else code[:-2] if code.endswith(('10','20')) else code.removeprefix('DND-')
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

