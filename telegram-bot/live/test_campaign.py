"""Run: cd telegram-bot/live && python -m unittest -v test_campaign.py"""
import asyncio
import binascii
import io
import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from PIL import Image
import app
from storage import Ledger, PROMOTERS, now

EVENT=date(2026,11,28)

class CampaignFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'test.sqlite3'
        self.ledger=Ledger(self.path)
        self.user=0
    def tearDown(self):self.tmp.cleanup()
    def booking(self,qty=1,code=None):
        self.user+=1
        offer=self.ledger.sales_offer(date(2026,10,30),EVENT)
        d=dict(name=f'Guest {self.user}',contact='@guest',source='Promoter' if code else 'Friend',tier=offer[0],quantity=qty)
        d.update(self.ledger.quote(code,offer))
        self.ledger.save(self.user,'confirm',d)
        return self.ledger.create(self.user,offer)
    def approve(self,r,db=None):
        db=db or self.ledger
        db.submit(r['serial'],r['user_id'])
        return db.approve_matched(r['serial'],f"Guest {r['user_id']}",now().date().isoformat(),r['total_cents'],999)
    def sold(self,n,code=None):
        rows=[]
        while n:
            qty=min(n,10);n-=qty
            rows.append(self.approve(self.booking(qty,code)))
        return rows

class CampaignTests(CampaignFixture):
    def test_all_fourteen_promoters_and_case_insensitive_codes(self):
        self.assertEqual(len(PROMOTERS),14)
        for stem,_ in PROMOTERS:
            self.assertEqual(self.ledger.quote((stem+'free').lower(),('Early bird',25))['price_cents'],2500)
            with self.assertRaisesRegex(ValueError,'not active yet'):self.ledger.quote(stem+'10',('Early bird',25))
            self.assertIsNone(self.ledger.promoter(stem+'20'))
    def test_only_approved_tickets_advance_counter(self):
        r=self.booking(10,'AUSTINFREE')
        self.assertEqual(self.ledger.campaign()['approved'],0)
        self.ledger.submit(r['serial'],r['user_id'])
        self.assertEqual(self.ledger.campaign()['approved'],0)
        with self.assertRaisesRegex(ValueError,'mismatch'):
            self.ledger.approve_matched(r['serial'],'Guest 1',now().date().isoformat(),1,999)
        self.assertEqual(self.ledger.campaign()['approved'],0)
        self.ledger.reject(r['serial'],999,'Test only')
        self.assertEqual(self.ledger.campaign()['approved'],0)
        with self.ledger.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM drink_benefits').fetchone()[0],0)
    def test_exact_hundred_switches_price_and_codes(self):
        self.sold(100,'AUSTINFREE')
        self.assertEqual(self.ledger.campaign(),dict(approved=100,remaining=0,free_open=False,discount_open=True,drinks_granted=100))
        self.assertEqual(self.ledger.sales_offer(date(2026,10,30),EVENT),('General',30))
        with self.assertRaisesRegex(ValueError,'ended'):self.ledger.quote('AUSTINFREE',('General',30))
        r=self.booking(2,'austin10')
        self.assertEqual(r['total_cents'],5400)
        self.assertEqual(json.loads(r['details'])['discount_percent'],10)
    def test_all_sources_share_the_limit_but_only_free_code_gets_drink(self):
        self.sold(99)
        r=self.approve(self.booking(1,'NIHEELAFREE'))
        self.assertEqual(self.ledger.campaign()['drinks_granted'],1)
        self.assertEqual(json.loads(r['details'])['approval_position_start'],100)
        self.assertEqual(self.ledger.sales_offer(date(2026,10,30),EVENT),('General',30))
    def test_crossing_group_awards_only_remaining_drinks(self):
        self.sold(98)
        r=self.approve(self.booking(5,'SACHINFREE'))
        self.assertEqual(sum(t['free_drink'] for t in self.ledger.tickets(r['serial'])),2)
        self.assertEqual(r['total_cents'],12500)
        self.assertEqual(json.loads(r['details'])['free_drinks_awarded'],2)
        self.assertEqual(self.ledger.campaign()['approved'],103)
    def test_simultaneous_approvals_cannot_oversubscribe(self):
        self.sold(98)
        a,b=self.booking(2,'AUSTINFREE'),self.booking(2,'SACHINFREE')
        self.ledger.submit(a['serial'],a['user_id']);self.ledger.submit(b['serial'],b['user_id'])
        def approve_row(r):
            other=Ledger(self.path)
            return other.approve_matched(r['serial'],f"Guest {r['user_id']}",now().date().isoformat(),r['total_cents'],999)
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(approve_row,[a,b]))
        self.assertEqual(self.ledger.campaign()['approved'],102)
        self.assertEqual(self.ledger.campaign()['drinks_granted'],2)
        self.assertEqual(sorted(json.loads(r['details'])['free_drinks_awarded'] for r in rows),[0,2])
    def test_existing_early_order_keeps_total_when_paid_after_cutoff(self):
        r=self.booking(3,'MEERAFREE')
        self.sold(100)
        approved=self.approve(r)
        self.assertEqual(approved['total_cents'],7500)
        self.assertEqual(json.loads(approved['details'])['free_drinks_awarded'],0)
    def test_old_confirmation_cannot_create_early_bird_after_cutoff(self):
        d=dict(name='Draft Guest',contact='@draft',source='Friend',tier='Early bird',price_cents=2500,quantity=1)
        self.ledger.save(555,'confirm',d)
        self.sold(100)
        with self.assertRaisesRegex(ValueError,'Early bird has ended'):self.ledger.create(555,('Early bird',25))
        with self.assertRaisesRegex(ValueError,'offer changed'):self.ledger.create(555,('General',30))
    def test_void_and_restart_do_not_reopen_promo_or_change_orders(self):
        rows=self.sold(100,'AES HAFREE'.replace(' ',''))
        self.ledger.void(rows[-1]['serial'],999,'Test refund')
        self.ledger=Ledger(self.path)
        self.assertEqual(self.ledger.campaign()['approved'],100)
        self.assertFalse(self.ledger.campaign()['free_open'])
        self.assertEqual(self.ledger.order(rows[0]['serial'])['total_cents'],25000)
        with self.assertRaisesRegex(ValueError,'No active'):self.ledger.redeem_drink(self.ledger.tickets(rows[-1]['serial'])[0]['token'],999)
    def test_drink_redemption_is_once_and_independent_from_admission(self):
        r=self.approve(self.booking(1,'SHALUFREE'));t=self.ledger.tickets(r['serial'])[0]
        self.assertIsNotNone(self.ledger.redeem_drink(t['token'],999))
        with self.assertRaisesRegex(ValueError,'already been redeemed'):self.ledger.redeem_drink(t['token'],999)
        self.assertTrue(self.ledger.admit(t['token'],999))
        self.assertFalse(self.ledger.admit(t['token'],999))
        self.assertIsNotNone(self.ledger.lookup(t['token'])['drink_claimed_at'])
    def test_admitted_guest_can_still_redeem_drink(self):
        r=self.approve(self.booking(1,'SHALUFREE'));t=self.ledger.tickets(r['serial'])[0]
        self.assertTrue(self.ledger.admit(t['token'],999))
        self.ledger.redeem_drink(t['token'],999)
    def test_manual_discount_pause_persists_without_reopening_free(self):
        self.sold(100);self.ledger.set_promoter_discounts(False,999)
        self.ledger=Ledger(self.path)
        self.assertFalse(self.ledger.campaign()['discount_open'])
        with self.assertRaisesRegex(ValueError,'not active'):self.booking(1,'AUSTIN10')
        self.ledger.set_promoter_discounts(True,999)
        self.assertEqual(self.booking(1,'AUSTIN10')['total_cents'],2700)
    def test_migration_backup_and_old_orders_and_staff_survive(self):
        r=self.sold(5)[0]
        self.ledger.grant_door(123,999)
        with self.ledger.db() as db:
            db.execute("DELETE FROM meta WHERE key='promo_campaign_v1'")
            db.execute("DELETE FROM promoters WHERE code LIKE '%FREE' OR code LIKE '%10'")
            db.execute("INSERT INTO promoters VALUES('AUSTIN20','Austin',?,20)",(now().isoformat(),))
            db.execute('DROP TABLE drink_benefits')
            before=[tuple(x) for x in db.execute('SELECT * FROM orders')]
        self.ledger=Ledger(self.path)
        backup=list((self.path.parent/'backups').glob('pre-promoter-launch-*.sqlite3'))
        self.assertEqual(len(backup),1)
        with sqlite3.connect(backup[0]) as db:self.assertEqual(db.execute('SELECT * FROM orders').fetchall(),before)
        with self.ledger.db() as db:self.assertEqual([tuple(x) for x in db.execute('SELECT * FROM orders')],before)
        self.assertEqual(self.ledger.campaign()['approved'],5)
        self.assertTrue(self.ledger.door_authorized(123,set()))
        self.assertIsNone(self.ledger.promoter('AUSTIN20'))
        self.assertEqual(self.ledger.order(r['serial'])['status'],'paid')
        Ledger(self.path)
        self.assertEqual(len(list((self.path.parent/'backups').glob('pre-promoter-launch-*.sqlite3'))),1)
    def test_walkin_exact_cents_and_event_end(self):
        self.sold(100)
        self.assertEqual(self.ledger.sales_offer(EVENT,EVENT),('Walk-in',35))
        self.assertEqual(self.ledger.quote('AUSTIN10',('Walk-in',35))['price_cents'],3150)
        self.assertIsNone(self.ledger.sales_offer(date(2026,11,29),EVENT))
    def test_new_admin_promoter_pair_and_legacy_stats(self):
        self.ledger.add_promoter('NEW','New Person',999)
        self.assertIsNotNone(self.ledger.promoter('NEWFREE'))
        self.assertIsNotNone(self.ledger.promoter('NEW10'))
        self.sold(2,'SACHINFREE')
        s=next(x for x in self.ledger.promoter_stats() if x['code']=='SACHIN')
        self.assertEqual((s['booked'],s['paid']),(2,2))
    def test_scanner_contract_still_admits_once(self):
        r=self.approve(self.booking(1,'AUSTINFREE'));t=self.ledger.tickets(r['serial'])[0]
        result=self.ledger.door_admit('request1',t['token'],999,time.time())
        self.assertEqual(result['status'],'admitted')
        self.assertEqual(self.ledger.door_admit('request1',t['token'],999,time.time()),result)
        self.assertEqual(self.ledger.door_admit('request2',t['token'],999,time.time())['status'],'used')
        self.assertEqual(self.ledger.door_guests()['guests'][0]['entry_status'],'Used')

class GuestFlowTests(CampaignFixture):
    def setUp(self):
        super().setUp()
        self.patches=[patch.object(app,'ledger',self.ledger),patch.object(app,'offer',lambda:self.ledger.sales_offer(date(2026,10,30),EVENT)),patch.object(app,'opened',lambda:True),patch.object(app,'ADMINS',{999})]
        for p in self.patches:p.start()
        self.chat=NS(type='private',send_message=AsyncMock(),send_photo=AsyncMock())
        self.u=NS(effective_user=NS(id=555),effective_chat=self.chat,message=NS(text=''),callback_query=NS(data='',answer=AsyncMock(),edit_message_reply_markup=AsyncMock()))
        self.c=NS(args=[],bot=NS(send_message=AsyncMock(),send_photo=AsyncMock()))
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        super().tearDown()
    def click(self,key):
        self.u.callback_query.data=key;asyncio.run(app.click(self.u,self.c))
    def answer(self,text):
        self.u.message.text=text;asyncio.run(app.answer(self.u,self.c))
    def message(self):return self.chat.send_message.call_args.args[0]
    def buttons(self):
        return [b.callback_data for row in self.chat.send_message.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
    def test_guest_promoter_back_and_standard_booking(self):
        self.click('begin');self.answer('Arjun Mehta');self.answer('@arjun');self.click('source:Promoter');self.answer('bad')
        self.assertIn('back:promoter_code',self.buttons());self.click('back:promoter_code');self.click('source:Friend');self.click('qty:2')
        self.assertIn('S$50.00',self.message())
        self.assertEqual(self.ledger.create(555,('Early bird',25))['total_cents'],5000)
    def test_free_confirmation_provisional_and_no_discount(self):
        self.click('begin');self.answer('Arjun Mehta');self.answer('@arjun');self.click('source:Promoter');self.answer('sachinfree');self.click('qty:2')
        self.assertIn('S$50.00',self.message());self.assertIn('confirmed on approval',self.message())
        self.assertNotIn('10%',self.message())
    def test_general_discount_and_back_do_not_compound(self):
        self.sold(100)
        self.click('begin');self.answer('Arjun Mehta');self.answer('@arjun');self.click('source:Promoter');self.answer('austin10');self.click('qty:2')
        self.assertIn('S$54.00',self.message())
        self.click('back:confirm');self.click('back:quantity');self.answer('AUSTIN10');self.click('qty:2')
        self.assertIn('S$54.00',self.message())
        self.click('back:confirm');self.click('back:quantity');self.click('back:promoter_code');self.click('source:Other');self.click('qty:2')
        self.assertIn('S$60.00',self.message())
    def test_public_menus_never_advertise_name10(self):
        for count in [0,100]:
            if count:self.sold(count)
            for fn in [app.buy,app.prices_cmd]:
                asyncio.run(fn(self.u,self.c));text=self.message()
                self.assertNotIn('NAME10',text);self.assertNotIn('10%',text);self.assertNotIn('20%',text)
    def test_unauthorised_drink_redemption_is_blocked(self):
        r=self.approve(self.booking(1,'AUSTINFREE'));t=self.ledger.tickets(r['serial'])[0]
        self.click('drink:'+t['token'])
        self.assertIn('Only authorised',self.message())
        self.assertIsNone(self.ledger.lookup(t['token'])['drink_claimed_at'])
    def test_used_ticket_still_shows_drink_button_to_admin(self):
        r=self.approve(self.booking(1,'AUSTINFREE'));t=self.ledger.tickets(r['serial'])[0]
        self.ledger.admit(t['token'],999);self.u.effective_user.id=999
        asyncio.run(app.check_token(self.u,t['token']))
        self.assertIn('ALREADY USED',self.message());self.assertIn('drink:'+t['token'],self.buttons())
        self.click('drink:'+t['token']);self.assertIn('REDEEMED',self.message())
        self.click('drink:'+t['token']);self.assertIn('already been redeemed',self.message())
    def test_payment_photo_caption_fits_telegram_limit(self):
        r=self.booking(10,'AUSTINFREE');self.u.effective_user.id=r['user_id']
        with patch.object(app,'payment_image',lambda amount:io.BytesIO(b'fictional-test-image')):
            asyncio.run(app.payment(self.u,r))
        caption=self.chat.send_photo.call_args.kwargs['caption']
        self.assertLessEqual(len(caption),1024)
        self.assertIn('<b>Your booking name',caption)
        self.assertIn('first 100 approved',caption)
    def test_ticket_generation_and_resend_keep_same_drink(self):
        r=self.approve(self.booking(1,'AUSTINFREE'));t=self.ledger.tickets(r['serial'])[0]
        with app.render_ticket(t) as image:self.assertGreater(Image.open(image).height,400)
        asyncio.run(app.deliver(self.c.bot,r));asyncio.run(app.deliver(self.c.bot,r))
        self.assertEqual(self.ledger.campaign()['drinks_granted'],1)
        self.assertIn('ONE free drink',self.c.bot.send_photo.call_args.kwargs['caption'])
    def test_paynow_amount_exact_and_crc_valid(self):
        def tlv(fields):return ''.join(f'{tag}{len(value):02d}{value}' for tag,value in fields)
        payload=tlv([('00','01'),('26',tlv([('00','SG.PAYNOW'),('03','0')])),('53','702'),('58','SG')])+'6304'
        payload+=f'{binascii.crc_hqx(payload.encode(),0xFFFF):04X}'
        original=app.qrcode.make
        with patch.dict(app.os.environ,{'PAYNOW_QR_PAYLOAD':payload}),patch.object(app.qrcode,'make',wraps=original) as make:
            with app.payment_image(3150) as image:self.assertGreater(Image.open(image).width,100)
        result=make.call_args.args[0]
        self.assertIn('540531.50',result)
        self.assertEqual(result[-4:],f'{binascii.crc_hqx(result[:-4].encode(),0xFFFF):04X}')

if __name__=='__main__':unittest.main()
