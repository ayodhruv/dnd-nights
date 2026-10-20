import sys,tempfile,sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Ledger,now
D=dict(tier='Early bird',price=25,name='Test Guest',contact='@test',source='Friend',quantity=2)
def draft(l,u,qty=2):l.save(u,'confirm',{**D,'quantity':qty})
with tempfile.TemporaryDirectory() as d:
 l=Ledger(d+'/live.db',capacity=4)
 draft(l,1);r=l.create(1,('Early bird',25));serial=r['serial']
 assert serial.startswith('DND26-') and r['total_cents']==5000
 draft(l,1)
 try:l.create(1,('Early bird',25))
 except ValueError:pass
 else:raise AssertionError('second active booking')
 try:l.submit(serial,999)
 except ValueError:pass
 else:raise AssertionError('wrong owner')
 l.submit(serial,1)
 for ref,amt in [('TEST-123',5000),('BANK-123',2500)]:
  try:l.approve(serial,ref,amt,99)
  except ValueError:pass
  else:raise AssertionError('bad approval')
 assert not l.admit(l.tickets(serial)[0]['token'],99)
 paid=l.approve(serial,'BANK-123',5000,99)
 assert paid['status']=='paid' and len(l.tickets(serial))==2
 draft(l,2);r2=l.create(2,('Early bird',25));l.submit(r2['serial'],2)
 try:l.approve(r2['serial'],'bank-123',5000,99)
 except ValueError:pass
 else:raise AssertionError('reused bank ref')
 assert l.order(r2['serial'])['status']=='review'
 tok=l.tickets(serial)[0]['token']
 with ThreadPoolExecutor(8) as pool:assert sum(pool.map(lambda _:l.admit(tok,99),range(12)))==1
 try:l.void(serial,99,'already admitted')
 except ValueError:pass
 else:raise AssertionError('admitted booking released')
 l.approve(r2['serial'],'BANK-SECOND',5000,99)
 l.void(r2['serial'],99,'refund handled separately')
 assert not l.admit(l.tickets(r2['serial'])[0]['token'],99)
 l.backup(d+'/backup.db');assert Ledger(d+'/backup.db',4).order(r2['serial'])['status']=='void'
 # Concurrent bookings cannot oversell, across independent DB connections.
 l2=Ledger(d+'/cap.db',capacity=10)
 for u in range(1,21):draft(l2,u)
 def attempt(u):
  try:l2.create(u,('Early bird',25));return True
  except ValueError:return False
 with ThreadPoolExecutor(10) as pool:assert sum(pool.map(attempt,range(1,21)))==5
 # Expired hold is released; late payment must recheck capacity.
 l3=Ledger(d+'/late.db',capacity=2)
 draft(l3,1);a=l3.create(1,('Early bird',25))
 with l3.db() as db:db.execute('UPDATE orders SET expires_at=?',( (now()-timedelta(minutes=1)).isoformat(),))
 assert l3.order(a['serial'])['status']=='expired'
 assert l3.submit(a['serial'],1)=='review_late'
 draft(l3,2);b=l3.create(2,('Early bird',25))
 try:l3.approve(a['serial'],'LATE-BANK',5000,99)
 except ValueError:pass
 else:raise AssertionError('late payment oversold')
 # No re-approval after paid and no reset by ticket redelivery.
 l3.reject(b['serial'],99,'unpaid cancellation')
 l3.approve(a['serial'],'LATE-BANK',5000,99)
 token=l3.tickets(a['serial'])[0]['token'];l3.admit(token,99);l3.delivered(token)
 assert l3.lookup(token)['used_at']
 try:l3.approve(a['serial'],'OTHER-BANK',5000,99)
 except ValueError:pass
 else:raise AssertionError('double approval')
 print('PASS: owner checks, amount/ref guards, case-normalised duplicate reference rollback, paid-only admission, concurrent once-only entry, void, backup restore, concurrent capacity, expiry/late capacity, repeated approval blocked.')
