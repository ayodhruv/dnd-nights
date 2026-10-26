"""Door scanner bridge. Render SQLite remains the only ticket authority."""
import asyncio
import hashlib
import os
import secrets
import time
from urllib.parse import urlparse
import httpx

DEFAULT_URL='https://deepavali-afterglow-2026-sg.ayodhruv.chatgpt.site'

class DoorBridge:
    def __init__(self, ledger, admins, bot_token):
        self.ledger, self.admins = ledger, admins
        self.url=os.getenv('SCANNER_URL',DEFAULT_URL).rstrip('/')
        if urlparse(self.url).scheme!='https':raise ValueError('Scanner requires HTTPS')
        self.key=hashlib.sha256(('dnd-door-bridge-v1:'+bot_token).encode()).hexdigest()
        self.client=httpx.AsyncClient(timeout=12,follow_redirects=False,headers={'Authorization':'Bearer '+self.key})
    async def call(self, path, body):
        response=await self.client.post(self.url+'/door/api/bridge/'+path,json=body)
        response.raise_for_status()
        return response.json()
    async def login(self, admin):
        token=secrets.token_urlsafe(32)
        await self.call('session',{'token':token,'admin':admin})
        return self.url+'/door#'+token
    async def revoke(self, admin):
        await self.call('revoke',{'admin':admin})
    async def run(self):
        announced=False
        while True:
            try:
                data=await self.call('poll',{})
                if not announced:
                    print('Door scanner connected to live Render ledger.',flush=True);announced=True
                for job in data.get('jobs',[]):
                    admin=job.get('admin')
                    if not self.ledger.door_authorized(admin,self.admins):
                        result={'status':'forbidden'}
                    elif job.get('action')=='scan':
                        result=self.ledger.door_admit(job['id'],job.get('token',''),admin,job['created'])
                    elif job.get('action')=='guests':
                        result=self.ledger.door_guests()
                    else:result={'status':'invalid'}
                    await self.call('result',{'id':job['id'],'result':result})
                await asyncio.sleep(.6)
            except asyncio.CancelledError:raise
            except Exception:
                if announced:print('Door scanner connection interrupted; admissions require live confirmation.',flush=True)
                announced=False
                await asyncio.sleep(3)
    async def close(self):await self.client.aclose()
