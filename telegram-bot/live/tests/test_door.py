"""Scanner checks run only against a temporary database with fictional tickets."""
import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from storage import Ledger,now

def main():
 with tempfile.TemporaryDirectory() as tmp:
  ledger=Ledger(Path(tmp)/'db.sqlite3')
  assert ledger.door_authorized(7,{7}) and not ledger.door_authorized(8,{7})
  ledger.grant_door(8,7)
  assert ledger.door_authorized(8,{7}) and [r['user_id'] for r in ledger.door_staff_list()]==[8]
  assert ledger.revoke_door(8,7) and not ledger.door_authorized(8,{7})
  assert not ledger.door_staff_list() and ledger.door_authorized(7,{7})
  with ledger.db() as db:
   for i,status in enumerate(['paid','pending','void'],1):
    serial=f'ORDER{i}'
    db.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?)',(serial,i,'2110',i,json.dumps({'name':'Fictional Booker'}),1,2500,status,now().isoformat(),now().isoformat()))
    db.execute('INSERT INTO tickets(token,serial,label) VALUES(?,?,?)',(str(i)*43,serial,100+i))
  stamp=time.time()
  assert ledger.door_admit('pending','2'*43,7,stamp)['status']=='invalid'
  assert ledger.door_admit('void','3'*43,7,stamp)['status']=='invalid'
  assert ledger.door_admit('unknown','X'*43,7,stamp)['status']=='invalid'
  assert ledger.door_admit('stale','1'*43,7,stamp-20)['status']=='expired'
  assert not ledger.lookup('1'*43)['used_at']
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda i:ledger.door_admit('scan'+str(i),'1'*43,7,stamp),range(16)))
  assert sum(r['status']=='admitted' for r in results)==1
  winning=next(i for i,r in enumerate(results) if r['status']=='admitted')
  assert ledger.door_admit('scan'+str(winning),'1'*43,7,stamp-100)==results[winning]
  assert ledger.door_admit('scan'+str(winning),'2'*43,7,stamp)['status']=='conflict'
  assert not ledger.admit('1'*43,7)
  guests=ledger.door_guests()
  assert guests['status']=='ok' and len(guests['guests'])==3
  assert all('token' not in row and 'contact' not in row for row in guests['guests'])
  assert next(g for g in guests['guests'] if g['label']==101)['entry_status']=='Used'
  with ledger.db() as db:assert db.execute("SELECT COUNT(*) FROM audit WHERE action='admitted'").fetchone()[0]==1
 print('Door tests passed: scanner-only grant/revoke, concurrent entry, replay recovery, invalid/unpaid/void/stale rejection, shared Telegram state, no ticket secrets in guest list.')
if __name__=='__main__':main()
