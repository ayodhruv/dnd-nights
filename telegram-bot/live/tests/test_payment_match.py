"""Manual UOB sender/date matching on fictional bookings only."""
import json
import tempfile
from datetime import timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Ledger,now

def booking(ledger,user):
    ledger.save(user,'confirm',{'name':'Test Booker','contact':'@test','source':'Friend',
                                'tier':'Early bird','price':25,'quantity':1})
    row=ledger.create(user,('Early bird',25))
    ledger.submit(row['serial'],user)
    return row['serial']

def denied(fn):
    try:fn()
    except ValueError:return
    raise AssertionError('Expected approval to be blocked')

with tempfile.TemporaryDirectory() as tmp:
    ledger=Ledger(Path(tmp)/'live.sqlite3')
    first=booking(ledger,11)
    today=now().date().isoformat()
    denied(lambda:ledger.approve_matched(first,'Other Sender',today,2500,99))
    denied(lambda:ledger.approve_matched(first,'Test Booker',today,1,99))
    denied(lambda:ledger.approve_matched(first,'Test Booker',(now().date()+timedelta(days=1)).isoformat(),2500,99))
    denied(lambda:ledger.set_payer(first,12,'Other Sender'))
    assert ledger.order(first)['status']=='review'
    ledger.set_payer(first,11,'Other Sender')
    paid=ledger.approve_matched(first,'other   SENDER',today,2500,99)
    assert paid['status']=='paid'
    with ledger.db() as db:
        evidence=db.execute('SELECT * FROM payment_evidence WHERE serial=?',(first,)).fetchone()
        payment=db.execute('SELECT * FROM payments WHERE serial=?',(first,)).fetchone()
        assert evidence['sender_name']=='other SENDER' and evidence['bank_date']==today
        assert payment['reference'].startswith('MANUAL-UOB-')
    denied(lambda:ledger.set_payer(first,11,'New Sender'))
    second=booking(ledger,22)
    ledger.set_payer(second,22,'Other Sender')
    denied(lambda:ledger.approve_matched(second,'Other Sender',today,2500,99))
    assert ledger.order(second)['status']=='review'
    assert ledger.approve_matched(second,'Other Sender',(now().date()-timedelta(days=1)).isoformat(),2500,99)['status']=='paid'
print('PASS: payer ownership, exact name/amount/date checks, duplicate bank row guard, and internal audit key.')
