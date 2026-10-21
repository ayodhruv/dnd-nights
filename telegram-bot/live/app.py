"""Public DND Nights bot: PayNow with staff bank verification. One polling process."""
import base64
import asyncio
import io
import json
import logging
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import qrcode
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from storage import Ledger, now
from door import DoorBridge

ROOT=Path(__file__).resolve().parent
load_dotenv(ROOT/'.env')
logging.basicConfig(level=logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
ADMINS={int(v.strip()) for v in os.getenv('ADMIN_USER_IDS','').split(',') if v.strip().isdigit()}
DATA=Path(os.getenv('DATA_DIR',str(ROOT/'data')))
ledger=None
BOT_USERNAME=''

def payment_image():
    # Prefer a private hosting variable; never commit a personal receiving QR.
    payload=os.getenv('PAYNOW_QR_PAYLOAD','')
    if payload:
        if len(payload)>4096 or not payload.startswith('000201') or any(ord(c)<32 for c in payload):
            raise ValueError('Invalid PayNow QR payload. Copy it using the QR extraction command.')
        import binascii
        if payload[-8:-4]!='6304' or f'{binascii.crc_hqx(payload[:-4].encode(),0xFFFF):04X}'!=payload[-4:].upper():
            raise ValueError('Payment QR checksum mismatch. Copy the full payload again.')
        image=qrcode.make(payload)
        result=io.BytesIO();image.save(result,format='PNG');result.seek(0)
        return result
    encoded=os.getenv('PAYNOW_QR_BASE64','').strip()
    if encoded:
        try:data=base64.b64decode(encoded,validate=True)
        except Exception:raise ValueError('PAYNOW_QR_BASE64 is not valid base64.') from None
    else:
        path=ROOT/'paynow.png'
        if not path.is_file():raise ValueError('Set private PAYNOW_QR_PAYLOAD or add local paynow.png.')
        data=path.read_bytes()
    if len(data)>2000000:raise ValueError('Payment QR file is too large.')
    Image.open(io.BytesIO(data)).verify()
    return io.BytesIO(data)

def opened():return os.getenv('SALES_OPEN','false').lower()=='true'
def offer():
    today=now().date();event=date.fromisoformat(os.getenv('EVENT_DATE','2026-11-28'))
    if today>event:return None
    if today==event:return 'Walk-in',35
    return ('Early bird',25) if today<=date.fromisoformat(os.getenv('EARLY_BIRD_CUTOFF','2026-11-14')) else ('Presale',30)
def keys(*items):return InlineKeyboardMarkup([[InlineKeyboardButton(label,callback_data=value)] for label,value in items])
async def say(u,text,markup=None):await u.effective_chat.send_message(text,reply_markup=markup)
async def private(u):return bool(u.effective_chat and u.effective_chat.type=='private')
async def staff(u):
    if not await private(u):return False
    if u.effective_user.id not in ADMINS:
        await say(u,'Only authorised event staff can use this action.');return False
    return True
async def notify(bot,text):
    for admin in ADMINS:
        try:await bot.send_message(admin,text)
        except Exception:print('Staff notification failed; the saved /review queue is available.',flush=True)
async def start(u,c):
    if not await private(u):return
    if c.args and c.args[0].startswith('check_'):
        return await check_token(u,c.args[0][6:])
    await say(u,'Welcome to DND Nights!\n28 November 2026 · Singapore\n\nBook tickets below. PayNow payments are checked by staff before entry tickets are issued.',keys(('Book tickets','buy'),('My orders','orders'),('Help','help')))
async def buy(u,c):
    if not await private(u):return
    if not opened():return await say(u,'Bookings are temporarily closed. Use /help for assistance.')
    current=offer()
    if not current:return await say(u,'Ticket sales have ended.')
    tier,price=current
    await say(u,f'DND Nights · 28 November 2026\n{tier}: S${price} per guest. Maximum 2 tickets per booking.\n\n'
        'PayNow only. Staff verify the payment in the receiving bank account before issuing tickets. '
        'Bank emails can be delayed. Do not pay twice while waiting.\n\n'
        'Your name, contact and Telegram ID are stored to fulfil your booking and provide support. '
        'Each ticket admits one guest once. Keep the QR private.\n\n'
        +os.getenv('EVENT_TERMS','For event details and refund enquiries, use /help before paying.'),keys(('Continue','begin'),('Cancel draft','cancel')))
async def cancel(u,c):
    if await private(u):ledger.clear(u.effective_user.id);await say(u,'Draft cancelled. Existing orders remain in /orders. Contact /help to resolve an existing payment.')
async def help_cmd(u,c):
    if not await private(u):return
    if c.args:
        ledger.remember(u.effective_user.id)
        msg=' '.join(c.args)[:1000]
        await notify(c.bot,f"Guest support request\nTelegram ID: {u.effective_user.id}\nName: {u.effective_user.full_name}\n{msg}")
        return await say(u,'Your message was sent to the organisers. Keep this chat open for their reply.')
    await say(u,'Send /help followed by your question and order serial. The organisers will reply here.\n\nIf already paid, do not pay again. Tell us if the payment came from someone else. Never send a bank password or OTP.')
async def orders(u,c):
    if not await private(u):return
    rows=ledger.orders(u.effective_user.id)
    if not rows:return await say(u,'No live orders yet. Use /buy. Earlier TEST tickets are not part of live sales.')
    for r in rows[:20]:
        markup=keys(('View payment QR','pay:'+r['serial']),('I have paid','paid:'+r['serial'])) if r['status']=='pending' else None
        if r['status']=='expired':markup=keys(('I already paid — request review','paid:'+r['serial']))
        await say(u,f"Order {r['serial']}\nQuantity: {r['quantity']}\nTotal: S${r['total_cents']/100:.2f}\nStatus: {r['status']}",markup)
async def payment(u,r):
    if r['user_id']!=u.effective_user.id:return await say(u,'Order unavailable.')
    if r['status']!='pending':return await say(u,'Payment window is closed or this order was submitted. Do not pay again. Use /orders or /help.')
    caption=(f"DND Nights — PayNow\nOrder: {r['serial']}\nTotal: S${r['total_cents']/100:.2f}\nQuantity: {r['quantity']}\n"
        f"Pay before: {r['expires_at'][11:16]} Singapore time\n\n"
        f"Check recipient: {os.environ['PAYNOW_RECIPIENT_NAME']}\n"
        'Enter the exact total shown above. This QR does not set the amount automatically. '
        'Remarks are optional; your order serial helps if you include it.\n\n'
        'After transferring, tap I have paid. Staff verify your incoming bank transaction before issuing entry tickets. '
        'The button itself does not confirm payment. If the payment window has passed, contact /help before transferring.')
    with payment_image() as f:
        await u.effective_chat.send_document(document=f,filename='DND_PayNow.png',caption=caption,reply_markup=keys(('I have paid','paid:'+r['serial'])))
async def click(u,c):
    q=u.callback_query;await q.answer()
    if not await private(u):return
    key=q.data;user=u.effective_user.id
    try:
        if key=='buy':return await buy(u,c)
        if key=='orders':return await orders(u,c)
        if key=='help':return await help_cmd(u,c)
        if key=='cancel':return await cancel(u,c)
        if key.startswith('admit:'):
            if await staff(u):await say(u,'ADMITTED — first entry recorded.' if ledger.admit(key[6:],user) else 'BLOCKED — ticket is already used, void or invalid.')
            return
        if key.startswith('pay:'):
            r=ledger.order(key[4:])
            return await payment(u,r) if r else await say(u,'Order unavailable.')
        if key.startswith('paid:'):
            serial=key[5:];status=ledger.submit(serial,user)
            await say(u,'Payment submitted for staff review. Your entry ticket will arrive here after verification. Do not pay again.\n\n'
                'If someone else paid, send /help with the order serial and the payer name shown by their bank.'+ ('\nThe payment window expired; staff must also check available capacity.' if status=='review_late' else ''))
            await notify(c.bot,f'Payment claimed: {serial}\nUse /review. A guest claim is not bank confirmation.');return
        state,d=ledger.draft(user)
        if key=='begin':
            if not opened() or not offer():return await say(u,'Sales are closed.')
            tier,price=offer();ledger.save(user,'name',dict(tier=tier,price=price))
            return await say(u,'Question 1 of 4: What is your full name?')
        if key.startswith('source:') and state=='source':
            source=key[7:]
            if source not in ('Instagram','Friend','Other'):return
            d['source']=source;ledger.save(user,'quantity',d)
            return await say(u,'Question 4 of 4: How many tickets?',keys(('1','qty:1'),('2','qty:2')))
        if key in ('qty:1','qty:2') and state=='quantity':
            d['quantity']=int(key[-1]);ledger.save(user,'confirm',d)
            return await say(u,f"Please confirm:\nName: {d['name']}\nContact: {d['contact']}\nOffer: {d['tier']}\nQuantity: {d['quantity']}\nTotal: S${d['price']*d['quantity']}\n\nConfirm to reserve tickets for 30 minutes and receive payment instructions.",keys(('Confirm booking','confirm'),('Start again','begin'),('Cancel draft','cancel')))
        if key=='confirm' and state=='confirm':
            if not opened() or not offer():return await say(u,'Sales are closed.')
            r=ledger.create(user,offer());await q.edit_message_reply_markup(reply_markup=None)
            await say(u,f"Booking saved: {r['serial']}\nUse /orders to retrieve it.")
            return await payment(u,r)
        await say(u,'That step is no longer current. Use /orders or /buy.')
    except ValueError as exc:await say(u,str(exc))
async def answer(u,c):
    if not await private(u):return
    user=u.effective_user.id;text=u.message.text.strip();state,d=ledger.draft(user)
    if state=='name':
        if not 2<=len(text)<=80:return await say(u,'Enter a name between 2 and 80 characters.')
        d['name']=text;ledger.save(user,'contact',d)
        return await say(u,'Question 2 of 4: Your phone number or Instagram handle?')
    if state=='contact':
        if not 3<=len(text)<=80:return await say(u,'Enter a contact between 3 and 80 characters.')
        d['contact']=text;ledger.save(user,'source',d)
        return await say(u,'Question 3 of 4: Where did you hear about us?',keys(('Instagram','source:Instagram'),('Friend','source:Friend'),('Other','source:Other')))
    await say(u,'Use /buy to book, /orders for your bookings, or /help followed by a question.')
async def review(u,c):
    if not await staff(u):return
    rows=ledger.queue()
    if not rows:return await say(u,'No payments awaiting review.')
    for r in rows:
        d=json.loads(r['details'])
        await say(u,f"REQUIRES BANK VERIFICATION\nOrder: {r['serial']}\nName: {d['name']}\nContact: {d['contact']}\nQuantity: {r['quantity']}\nExpected: S${r['total_cents']/100:.2f}\nState: {r['status']}\n\n"
            'Open UOB and confirm the money arrived and belongs to this guest. Resolve identical amounts/payer differences before approval. Do not approve from a screenshot or email amount alone.\n\n'
            f"After checking, use:\n/approve {r['serial']} BANK_TRANSACTION_REFERENCE {r['total_cents']/100:.2f}\n\n"
            'Replace BANK_TRANSACTION_REFERENCE with the actual incoming bank transaction ID. If unavailable, contact the guest and obtain enough bank evidence; do not invent a reference.')
def render_ticket(t):
    link=f"https://t.me/{BOT_USERNAME}?start=check_{t['token']}"
    qr=qrcode.make(link).convert('RGB')
    canvas=Image.new('RGB',(max(620,qr.width+80),qr.height+220),'white');canvas.paste(qr,((canvas.width-qr.width)//2,90))
    dr=ImageDraw.Draw(canvas);font=ImageFont.load_default(size=22)
    dr.text((24,20),f"DND Nights | Ticket #{t['label']:03d}",font=font,fill='black')
    dr.text((24,qr.height+110),'28 November 2026 | One guest, one entry',font=ImageFont.load_default(size=19),fill='black')
    dr.text((24,qr.height+145),f"Order: {t['serial']}",font=ImageFont.load_default(size=18),fill='black')
    dr.text((24,qr.height+180),'Keep this QR private. Staff scan at entry.',font=ImageFont.load_default(size=18),fill='black')
    buf=io.BytesIO();canvas.save(buf,'PNG');buf.seek(0);return buf
async def deliver(bot,r,only_missing=False):
    if r['status']!='paid':return
    for t in ledger.tickets(r['serial']):
        if only_missing and t['delivered_at']:continue
        await bot.send_document(r['user_id'],document=render_ticket(t),filename=f"DND_ticket_{t['label']:03d}.png",caption=f"Payment verified by event staff.\nTicket #{t['label']:03d}\nOrder: {r['serial']}\nOne guest per QR. /tickets resends this same ticket; it does not create another entry.")
        ledger.delivered(t['token'])
async def approve(u,c):
    if not await staff(u):return
    if len(c.args)!=3:return await say(u,'After verifying in UOB: /approve ORDER BANK_REFERENCE AMOUNT\nThis records your bank verification and issues live tickets.')
    serial,ref,amount=c.args
    if ref.upper() in ('BANK_REFERENCE','BANK_TRANSACTION_REFERENCE','REFERENCE'):
        return await say(u,'Replace the placeholder with the actual incoming bank transaction reference.')
    try:
        money=Decimal(amount)
        if not money.is_finite() or money<=0 or money*100!=(money*100).to_integral_value():raise ValueError('Invalid payment amount.')
        r=ledger.approve(serial,ref,int(money*100),u.effective_user.id)
    except (ValueError,InvalidOperation) as exc:return await say(u,str(exc))
    await say(u,'Bank verification saved. Sending tickets.')
    try:await deliver(c.bot,r)
    except Exception:await say(u,'Approval saved but delivery failed. Automatic retry runs every minute. /resend ORDER retries the same tickets.')
async def tickets(u,c):
    if not await private(u):return
    rows=[r for r in ledger.orders(u.effective_user.id) if r['status']=='paid']
    if not rows:return await say(u,'No paid live tickets yet. Use /orders for payment status.')
    for r in rows:await deliver(c.bot,r)
async def resend(u,c):
    if not await staff(u):return
    r=ledger.order(c.args[0]) if len(c.args)==1 else None
    if not r or r['status']!='paid':return await say(u,'Use /resend ORDER for a paid order.')
    await deliver(c.bot,r);await say(u,'Same tickets resent.')
async def check_token(u,token):
    if not await staff(u):return
    r=ledger.lookup(token)
    if not r or r['status']!='paid':return await say(u,'INVALID — not a paid active ticket.')
    if r['used_at']:return await say(u,f"ALREADY USED — #{r['label']:03d}\nFirst entry: {r['used_at']}")
    d=json.loads(r['details'])
    await say(u,f"VALID — Ticket #{r['label']:03d}\nBooker: {d['name']}\nOrder: {r['serial']}\nTap below to admit one guest.",keys(('Admit guest','admit:'+token)))
async def check(u,c):
    if not c.args:
        if await staff(u):await say(u,'Scan a guest QR with your phone camera, open its Telegram link and press Start. Or /check TOKEN.')
        return
    token=c.args[0].split('check_')[-1].removeprefix('DND:')
    await check_token(u,token)
async def resolve(u,c):
    if not await staff(u):return
    if len(c.args)<2:return await say(u,'Use /reject ORDER reason, or /void ORDER reason. Voiding does not refund money.')
    serial=c.args[0];note=' '.join(c.args[1:])[:500]
    try:
        r=ledger.void(serial,u.effective_user.id,note) if u.message.text.startswith('/void') else ledger.reject(serial,u.effective_user.id,note)
    except ValueError as exc:return await say(u,str(exc))
    await say(u,'Booking updated. No money was moved. Handle any refund in the bank and keep its reference.')
    await c.bot.send_message(r['user_id'],f'Booking {serial} updated by staff. Reason: {note}\nContact /help with any payment or refund question.')
async def reply(u,c):
    if not await staff(u):return
    if len(c.args)<2 or not c.args[0].isdigit():return await say(u,'Use /reply TELEGRAM_USER_ID message')
    # Only reply to a person who has contacted/booked with this bot. Avoid arbitrary IDs.
    target=int(c.args[0])
    known=ledger.orders(target) or ledger.known(target)
    if not known:return await say(u,'That user has not booked or requested support through this bot.')
    await c.bot.send_message(target,'DND Nights organiser: '+' '.join(c.args[1:])[:3000]);await say(u,'Reply sent.')
async def whoami(u,c):
    if await private(u):await say(u,f'Your Telegram ID: {u.effective_user.id}')
async def backup_cmd(u,c):
    if not await staff(u):return
    buf=io.BytesIO()
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'backup.sqlite3';ledger.backup(p);buf.write(p.read_bytes())
    buf.seek(0)
    await u.effective_chat.send_document(document=buf,filename=f'dnd-live-backup-{now():%Y%m%d-%H%M%S}.sqlite3',caption='Private live backup: guest details and active ticket secrets. Store privately; never put on GitHub.')
async def scanner_cmd(u,c):
    if not await staff(u):return
    bridge=c.application.bot_data.get('door_bridge')
    if not bridge:return await say(u,'Scanner connection is unavailable. Use /check as backup.')
    try:
        if c.args and c.args[0]=='revoke':
            await bridge.revoke(u.effective_user.id)
            return await say(u,'All scanner sessions for your account have been signed out.')
        link=await bridge.login(u.effective_user.id)
        await u.effective_chat.send_message('Private door scanner link (8 hours). Open in Safari or Chrome, then enable the camera. Valid ticket scans immediately record entry. Keep this link private. /scanner revoke signs out your devices.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Open door scanner',url=link)]]),protect_content=True)
    except Exception:await say(u,'Scanner connection is unavailable. Try again shortly; /check remains available.')

async def maintenance(app):
    last_backup=None
    while True:
        try:
            for r in ledger.undelivered():
                try:await deliver(app.bot,r,only_missing=True)
                except Exception:print('Ticket delivery retry pending.',flush=True)
            day=now().date()
            if day!=last_backup:
                folder=DATA/'backups';folder.mkdir(exist_ok=True)
                ledger.backup(folder/f'dnd-{day}.sqlite3');last_backup=day
                for old in sorted(folder.glob('dnd-*.sqlite3'))[:-7]:old.unlink()
        except Exception:print('Maintenance failed; inspect storage and /review.',flush=True)
        await asyncio.sleep(60)
async def setup(app):
    global BOT_USERNAME
    hook=await app.bot.get_webhook_info()
    if hook.url:raise RuntimeError('Existing webhook found. Stop the old backend and remove the webhook deliberately before running this polling bot.')
    BOT_USERNAME=app.bot.username
    await app.bot.set_my_commands([BotCommand('start','Main menu'),BotCommand('buy','Book tickets'),BotCommand('orders','My orders'),BotCommand('tickets','Resend paid tickets'),BotCommand('help','Contact organisers'),BotCommand('cancel','Cancel booking draft')])
    app.bot_data['maintenance']=asyncio.create_task(maintenance(app))
    bridge=DoorBridge(ledger,ADMINS,os.environ['TELEGRAM_BOT_TOKEN'])
    app.bot_data['door_bridge']=bridge
    app.bot_data['door_task']=asyncio.create_task(bridge.run())
    print(f'Connected @{BOT_USERNAME}; live ledger; sales {"OPEN" if opened() else "CLOSED"}; capacity {ledger.capacity}.',flush=True)
async def shutdown(app):
    door_task=app.bot_data.get('door_task')
    if door_task:
        door_task.cancel()
        try:await door_task
        except asyncio.CancelledError:pass
    if app.bot_data.get('door_bridge'):await app.bot_data['door_bridge'].close()
    task=app.bot_data.get('maintenance')
    if task:
        task.cancel()
        try:await task
        except asyncio.CancelledError:pass
async def error(u,c):
    print(f'Bot request failed: {type(c.error).__name__}. No automatic bank verification is performed.',flush=True)
    if u and u.effective_chat and await private(u):
        try:await say(u,'The request could not finish. Check /orders before trying again. For payments use /help; do not pay twice.')
        except Exception:pass
if __name__=='__main__':
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token or not ADMINS:raise SystemExit('Set TELEGRAM_BOT_TOKEN and ADMIN_USER_IDS in the hosting environment.')
    if opened() and (not os.getenv('PAYNOW_RECIPIENT_NAME','').strip() or not os.getenv('EVENT_TERMS','').strip()):raise SystemExit('Set verified PAYNOW_RECIPIENT_NAME and EVENT_TERMS before opening sales.')
    try:payment_image()
    except (ValueError,OSError):raise SystemExit('Add valid private PAYNOW_QR_PAYLOAD in Render, or local paynow.png.')
    ledger=Ledger(DATA/'dnd-live.sqlite3',int(os.getenv('EVENT_CAPACITY','230')),os.getenv('EVENT_ID','DND26'))
    app=Application.builder().token(token).concurrent_updates(False).post_init(setup).post_stop(shutdown).build()
    for cmd,fn in [('start',start),('buy',buy),('orders',orders),('tickets',tickets),('cancel',cancel),('help',help_cmd),('whoami',whoami),('review',review),('approve',approve),('resend',resend),('check',check),('reject',resolve),('void',resolve),('reply',reply),('backup',backup_cmd),('scanner',scanner_cmd)]:app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,answer))
    app.add_error_handler(error)
    app.run_polling(allowed_updates=['message','callback_query'],drop_pending_updates=False)
