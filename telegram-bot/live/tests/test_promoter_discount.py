"""Confirmed promoter discounts on new bookings, including migration of the live schema."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Ledger


def booking(ledger,user,offer,code=None,unit_price=None):
    tier,base=offer
    details={'name':'Test Guest','contact':'@test','source':'Promoter' if code else 'Friend',
             'tier':tier,'price':base if unit_price is None else unit_price,'quantity':2}
    if code:details['promoter_code']=code
    ledger.save(user,'confirm',details)
    return ledger.create(user,offer)


def blocked(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Invalid price or promoter code was accepted')


with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'live.sqlite3'
    # Render already has a three-column promoters table. Migration must keep its records.
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE promoters(code TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL)')
        db.execute("INSERT INTO promoters VALUES('DND-ADEEP','Adeep','2026-10-20')")
    ledger=Ledger(path)
    assert ledger.promoter('DND-ADEEP') is None
    for code in ('ADEEP20','NIRBHAY20','ISHWAR20','SHALU20','AUSTIN20','AIRA20'):
        assert ledger.promoter(code.lower())['discount_percent']==20
    for user,offer,price in ((1,('Early bird',25),20),(2,('Presale',30),24),(3,('Walk-in',35),28)):
        order=booking(ledger,user,offer,'adeep20',price)
        assert order['total_cents']==price*2*100
        assert json.loads(order['details'])['promoter_code']=='ADEEP20'
    assert booking(ledger,4,('Early bird',25))['total_cents']==5000
    blocked(lambda:booking(ledger,5,('Early bird',25),'DND-ADEEP',20))
    blocked(lambda:booking(ledger,6,('Early bird',25),'ADEEP20',25))
    blocked(lambda:booking(ledger,7,('Early bird',25),unit_price=20))
    with ledger.db() as db:
        assert db.execute("SELECT name FROM promoters WHERE code='DND-ADEEP'").fetchone()[0]=='Adeep'
    assert ledger.promoter_stats()
print('PASS: confirmed codes, case-insensitive 20% pricing across offers, exact totals, legacy migration, invalid-code and price guards.')
