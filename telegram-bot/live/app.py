"""Public DND Nights bot: PayNow with staff bank verification. One polling process."""
import binascii
import asyncio
import io
import json
import logging
import os
import re
from html import escape
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

def payment_image(total_cents):
    """Change only the EMV amount and CRC of the private UOB PayNow payload."""
    payload=os.getenv('PAYNOW_QR_PAYLOAD','')
    if not payload or len(payload)>4096 or not payload.startswith('000201') or any(ord(c)<32 for c in payload):
        raise ValueError('Payment QR is unavailable. Contact /help for assistance.')
    if payload[-8:-4]!='6304' or f'{binascii.crc_hqx(payload[:-4].encode(),0xFFFF):04X}'!=payload[-4:].upper():
        raise ValueError('Payment QR checksum mismatch.')
    if not 1<=total_cents<=999999:raise ValueError('Payment amount is out of range.')
    def parse(tlv):
        result=[];pos=0
        while pos<len(tlv):
            if pos+4>len(tlv):raise ValueError('Malformed PayNow QR.')
            tag=tlv[pos:pos+2]
            try:length=int(tlv[pos+2:pos+4])
            except ValueError:raise ValueError('Malformed PayNow QR.') from None
            value=tlv[pos+4:pos+4+length]
            if len(value)!=length:raise ValueError('Malformed PayNow QR.')
            result.append((tag,value));pos+=4+length
        return result
    def encode(fields):return ''.join(f'{tag}{len(value):02d}{value}' for tag,value in fields)
    fields=parse(payload)
    tags=dict(fields)
    if tags.get('53')!='702' or tags.get('58')!='SG' or '26' not in tags or fields[-1][0]!='63':
        raise ValueError('Expected a Singapore PayNow QR.')
    merchant=parse(tags['26']);merchant_tags=dict(merchant)
    if merchant_tags.get('00')!='SG.PAYNOW' or merchant_tags.get('03') not in ('0','1'):
        raise ValueError('Unsupported PayNow QR amount setting.')
    # The UOB amount-specific QRs supplied by the organiser set 26.03 to 0.
    # This changes an editable base QR into the exact fixed-amount UOB variant.
    merchant=encode([(tag,'0' if tag=='03' else value) for tag,value in merchant])
    amount=f'{total_cents/100:.2f}'
    fields=[(tag,merchant if tag=='26' else amount if tag=='54' else value) for tag,value in fields if tag!='63']
    if '54' not in tags:
        currency_index=next(i for i,(tag,_) in enumerate(fields) if tag=='53')
        fields.insert(currency_index+1,('54',amount))
    output=encode(fields)+'6304'
    output+=f'{binascii.crc_hqx(output.encode(),0xFFFF):04X}'
    image=qrcode.make(output)
    result=io.BytesIO();image.save(result,format='PNG');result.seek(0)
    return result

def opened():return os.getenv('SALES_OPEN','false').lower()=='true'
def offer():
    today=now().date();event=date.fromisoformat(os.getenv('EVENT_DATE','2026-11-28'))
    if today>event:return None
    if today==event:return 'Walk-in',35
    return ('Early bird',25) if today<=date.fromisoformat(os.getenv('EARLY_BIRD_CUTOFF','2026-11-14')) else ('Presale',30)
def keys(*items):return InlineKeyboardMarkup([[InlineKeyboardButton(label,callback_data=value)] for label,value in items])
def quantity_keys():
    return InlineKeyboardMarkup([[InlineKeyboardButton(str(n),callback_data=f'qty:{n}') for n in row]
                                 for row in (range(1,6),range(6,11))]
                                +[[InlineKeyboardButton('← Back',callback_data='back:quantity')]])
def source_keys():return keys(('Instagram','source:Instagram'),('Friend','source:Friend'),('Promoter','source:Promoter'),('Other','source:Other'),('← Back','back:source'))
def back_keys(state):return keys(('← Back','back:'+state))
def confirmation_keys():return keys(('Confirm booking','confirm'),('← Back','back:confirm'),('Start again','begin'),('Cancel draft','cancel'))
async def booking_question(u,state):
    if state=='name':return await say(u,'Question 1 of 4: What is your full name?',back_keys(state))
    if state=='contact':return await say(u,'Question 2 of 4: Your phone number or Instagram handle?',back_keys(state))
    if state=='source':return await say(u,'Question 3 of 4: Where did you hear about us?',source_keys())
    if state=='promoter_code':
        note='A valid code gives 20% off.' if ledger.promoter_discounts_enabled() else 'Discounts are currently unavailable.'
        return await say(u,'Enter your promoter’s referral code. This records who referred you. '+note+' Capitalisation does not matter. No code? Tap ← Back to choose another source.',back_keys(state))
    if state=='quantity':return await say(u,'Question 4 of 4: How many tickets? Choose 1–10.',quantity_keys())
async def say(u,text,markup=None,parse_mode=None):await u.effective_chat.send_message(text,reply_markup=markup,parse_mode=parse_mode)
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
def approval_command(r):
    """Prefill known booking details; the admin must confirm them against UOB."""
    details=json.loads(r['details'])
    sender=' '.join((details.get('payer_name') or details['name']).split())
    return f"/approve {r['serial']} {now().date().isoformat()} {r['total_cents']/100:.2f} {sender}"
def bank_review_details(r):
    details=json.loads(r['details'])
    clean=lambda value:' '.join(str(value).split())
    referral=f"\nPromoter referral: {clean(details['promoter_code'])}" if details.get('promoter_code') else ''
    return (f"Order: {r['serial']}\n"
            f"Guest name: {clean(details['name'])}\n"
            f"Contact: {clean(details['contact'])}"
            f"{referral}\n"
            f"Declared bank sender: {clean(details.get('payer_name') or details['name'])}\n"
            f"Quantity: {r['quantity']}\n"
            f"Expected: S${r['total_cents']/100:.2f}\n"
            f"State: {r['status']}")
async def notify_payment_claim(bot,r):
    for admin in ADMINS:
        try:
            await bot.send_message(admin,'PAYMENT CLAIMED — BANK CHECK REQUIRED\n'
                +bank_review_details(r)+'\n\nCheck the incoming credit in UOB first. A guest claim is not payment confirmation. '
                'Edit the date or sender in the next message if UOB shows different details. Use /review to retrieve this order.')
            await bot.send_message(admin,approval_command(r))
        except Exception:print('Staff notification failed; the saved /review queue is available.',flush=True)
async def start(u,c):
    if not await private(u):return
    if c.args and c.args[0].startswith('check_'):
        return await check_token(u,c.args[0][6:])
    await say(u,'Welcome to DND Nights!\nSaturday, 28 November 2026 · Singapore\n\nChoose an option below:',keys(('Book tickets','buy'),('My orders','orders'),('Date & location','event'),('Prices','prices'),('Terms & conditions','terms'),('Help','help')))
async def event_cmd(u,c):
    if await private(u):await say(u,'DND Nights\nSaturday, 28 November 2026 · 6:30–10:30pm\nSkyfall Rooftop Restrobar\n50 Telok Blangah Road, Singapore\n\nUse /buy to book.',keys(('Book tickets','buy'),('Main menu','menu')))
async def prices_cmd(u,c):
    if not await private(u):return
    current=offer()
    await say(u,'Prices per guest:\nEarly bird: S$25 through 14 November\nPresale: S$30 on 15–27 November\nWalk-in: S$35 on 28 November, subject to availability.\n\n'
              +('A confirmed promoter code gives 20% off: S$20 early bird, S$24 presale, or S$28 walk-in. Select Promoter during booking and enter the exact code (letters are case insensitive).\n\n' if ledger.promoter_discounts_enabled() else 'Promoter discounts are temporarily paused. Referral codes can still be recorded; standard ticket prices apply.\n\n')
              +(f'Current offer: {current[0]} · S${current[1]} per guest.' if current else 'Sales have ended.'),keys(('Book tickets','buy'),('Main menu','menu')))
async def terms_cmd(u,c):
    if not await private(u):return
    await say(u,'DND Nights · Terms & conditions\n\n'
              'Each paid ticket admits one guest for one entry. A ticket QR works only once. Keep it private; copied or forwarded QRs cannot provide another entry.\n\n'
              'Guest cancellations and change of plans are non-refundable. If the organiser cancels the event, ticket payments will be refunded. '
              'If the organiser reschedules, you may keep your ticket for the new date or request a refund. Contact /help with your order serial for those cases.\n\n'
              'Bookings depend on remaining capacity. Tickets are issued after a staff member confirms the incoming PayNow credit. '
              'We store the name, contact and Telegram ID supplied for booking, payment support and admission.',
              keys(('Book tickets','buy'),('Main menu','menu')))
async def buy(u,c):
    if not await private(u):return
    if not opened():return await say(u,'Bookings are temporarily closed. Use /help for assistance.')
    current=offer()
    if not current:return await say(u,'Ticket sales have ended.')
    tier,price=current
    await say(u,f'DND Nights · {tier}: S${price} per ticket.\nChoose up to 10 tickets in one booking.\n\n'
        +('Have a confirmed promoter code? Choose Promoter when asked how you heard about us for 20% off.\n\n' if ledger.promoter_discounts_enabled() else 'Promoter discounts are temporarily paused. Standard ticket prices apply.\n\n')
        +
        'Payment is by PayNow. After paying, tap I have paid and wait for a staff member to check the transaction. Your tickets arrive here after approval.\n\n'
        'Please read /terms before booking.',keys(('Continue booking','begin'),('Terms & conditions','terms'),('Main menu','menu')))
async def cancel(u,c):
    if await private(u):ledger.clear(u.effective_user.id);await say(u,'Draft cancelled. Existing orders remain in /orders. Contact /help to resolve an existing payment.')
async def help_cmd(u,c):
    if not await private(u):return
    await say(u,'Message one of our <a href="https://t.me/austisms">Admins</a>.',parse_mode='HTML')
def guest_order_status(status):
    return {
        'paid':'✅ Paid',
        'review':'⏳ Pending approval from DND staff',
        'review_late':'⏳ Pending approval from DND staff',
        'pending':'❌ Not paid',
        'expired':'❌ Payment window expired',
        'rejected':'❌ Booking rejected',
        'void':'❌ Ticket voided',
    }.get(status,'Status unavailable — contact /help')
async def orders(u,c):
    if not await private(u):return
    rows=ledger.orders(u.effective_user.id)
    if not rows:return await say(u,'No live orders yet. Use /buy. Earlier TEST tickets are not part of live sales.')
    for r in rows[:20]:
        markup=keys(('View payment QR','pay:'+r['serial']),('I have paid','paid:'+r['serial'])) if r['status']=='pending' else None
        if r['status']=='expired':markup=keys(('I already paid — request review','paid:'+r['serial']))
        d=json.loads(r['details'])
        await say(u,f"Order {escape(r['serial'])}\nQuantity: {r['quantity']}\nTotal: <b>S${r['total_cents']/100:.2f}</b>\nExpected bank sender: {escape(d.get('payer_name') or d['name'])}\nStatus: {guest_order_status(r['status'])}",markup,parse_mode='HTML')
async def payment(u,r):
    if r['user_id']!=u.effective_user.id:return await say(u,'Order unavailable.')
    if r['status']!='pending':return await say(u,'Payment window is closed or this order was submitted. Do not pay again. Use /orders or /help.')
    caption=(f"<b>PayNow · S${r['total_cents']/100:.2f}</b>\n"
        f"{r['quantity']} ticket(s) · Order {r['serial']}\n"
        f"Pay by {r['expires_at'][11:16]} Singapore time. The QR sets this amount for you. Check the recipient in your banking app.\n\n"
        '<b>Your booking name must match the full name on the paying bank account.</b> '
        f"If someone else pays, ask them to write {r['serial']} in the PayNow remarks and send "
        f"/payer {r['serial']} FULL_BANK_SENDER_NAME here. No remarks option? Send /payer with their bank name anyway.\n\n"
        'After paying, tap I have paid and please wait patiently for our team to approve the transaction. '
        'We do not use AI to approve payments; a staff member checks each incoming bank credit before your tickets are sent. '
        'Please do not pay twice while waiting.')
    with payment_image(r['total_cents']) as f:
        await u.effective_chat.send_photo(photo=f,caption=caption,parse_mode='HTML',reply_markup=keys(('I have paid','paid:'+r['serial'])))
async def click(u,c):
    q=u.callback_query;await q.answer()
    if not await private(u):return
    key=q.data;user=u.effective_user.id
    try:
        if key=='buy':return await buy(u,c)
        if key=='menu':return await start(u,c)
        if key=='orders':return await orders(u,c)
        if key=='help':return await help_cmd(u,c)
        if key=='event':return await event_cmd(u,c)
        if key=='prices':return await prices_cmd(u,c)
        if key=='terms':return await terms_cmd(u,c)
        if key=='cancel':return await cancel(u,c)
        if key.startswith('admit:'):
            if await staff(u):await say(u,'ADMITTED — first entry recorded.' if ledger.admit(key[6:],user) else 'BLOCKED — ticket is already used, void or invalid.')
            return
        if key.startswith('pay:'):
            r=ledger.order(key[4:])
            return await payment(u,r) if r else await say(u,'Order unavailable.')
        if key.startswith('paid:'):
            serial=key[5:];status=ledger.submit(serial,user)
            await say(u,'Thanks. Please wait patiently while a staff member checks your payment. Your entry tickets will arrive here once approved. Please do not pay again.\n\n'
                f'If someone else paid, send /payer {serial} FULL_BANK_SENDER_NAME so staff can match the incoming payment.'+ ('\nThe payment window expired; staff must also check available capacity.' if status=='review_late' else ''))
            await notify_payment_claim(c.bot,ledger.order(serial));return
        state,d=ledger.draft(user)
        if key=='begin':
            if not opened() or not offer():return await say(u,'Sales are closed.')
            tier,price=offer();ledger.save(user,'name',dict(tier=tier,price=price))
            return await booking_question(u,'name')
        if key.startswith('back:'):
            if key[5:]!=state or state not in ('name','contact','source','promoter_code','quantity','confirm'):
                return await say(u,'That Back button belongs to an earlier step. Use the buttons on the latest question, or /buy to restart.')
            if state=='name':return await buy(u,c)
            target={'contact':'name','source':'contact','promoter_code':'source',
                    'quantity':'promoter_code' if d.get('source')=='Promoter' else 'source',
                    'confirm':'quantity'}[state]
            ledger.save(user,target,d)
            return await booking_question(u,target)
        if key.startswith('source:') and state=='source':
            source=key[7:]
            if source not in ('Instagram','Friend','Promoter','Other'):return
            current=offer()
            if not current or current[0]!=d['tier']:raise ValueError('The offer changed. Please start again with /buy.')
            d['source']=source
            d['price']=current[1]
            for field in ('promoter_code','discount_percent','quantity'):d.pop(field,None)
            if source=='Promoter':
                ledger.save(user,'promoter_code',d)
                return await booking_question(u,'promoter_code')
            ledger.save(user,'quantity',d)
            return await booking_question(u,'quantity')
        if key.startswith('qty:') and state=='quantity' and key[4:].isdigit() and 1<=int(key[4:])<=10:
            if d.get('promoter_code'):
                promoter=ledger.promoter(d['promoter_code'])
                if not promoter:raise ValueError('This promoter code is unavailable. Please start again with /buy.')
                current=offer()
                if not current or current[0]!=d['tier']:raise ValueError('The offer changed. Please start again with /buy.')
                d['discount_percent']=promoter['discount_percent'] if ledger.promoter_discounts_enabled() else 0
                d['price']=current[1]*(100-d['discount_percent'])//100
            d['quantity']=int(key[4:]);ledger.save(user,'confirm',d)
            referral=f"\nPromoter: {d['promoter_code']}" if d.get('promoter_code') else ''
            discount=(f"\nPromoter discount: 20% (S${d['price']} per ticket)" if d.get('discount_percent') else '\nPromoter discounts are paused; standard price applies.') if d.get('promoter_code') else ''
            return await say(u,f"Please confirm:\nName: {d['name']}\nContact: {d['contact']}\nSource: {d['source']}{referral}\nOffer: {d['tier']}{discount}\nQuantity: {d['quantity']}\nTotal: S${d['price']*d['quantity']}\n\nConfirm to reserve tickets for 30 minutes and receive payment instructions.",confirmation_keys())
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
        if not 2<=len(text)<=80:return await say(u,'Enter a name between 2 and 80 characters.',back_keys(state))
        d['name']=text;ledger.save(user,'contact',d)
        return await booking_question(u,'contact')
    if state=='contact':
        if not 3<=len(text)<=80:return await say(u,'Enter a contact between 3 and 80 characters.',back_keys(state))
        d['contact']=text;ledger.save(user,'source',d)
        return await booking_question(u,'source')
    if state=='source':return await say(u,'Please choose one of these options:',source_keys())
    if state=='promoter_code':
        code=text.upper()
        promoter=ledger.promoter(code)
        if not promoter:return await say(u,'That code was not recognised. Check it with your promoter, or tap ← Back to choose another source.',back_keys(state))
        current=offer()
        if not current or current[0]!=d['tier']:return await say(u,'The offer changed. Please start again with /buy.')
        d['promoter_code']=promoter['code']
        d['discount_percent']=promoter['discount_percent'] if ledger.promoter_discounts_enabled() else 0
        d['price']=current[1]*(100-d['discount_percent'])//100
        ledger.save(user,'quantity',d)
        discount_note="20% off" if d['discount_percent'] else "Referral recorded. Discounts are temporarily paused"
        return await say(u,f"Code accepted: {promoter['code']}. {discount_note} — S${d['price']} per ticket for this offer. How many tickets? Choose 1–10.",quantity_keys())
    if state=='quantity':return await say(u,'Please choose how many tickets (1–10) using a button:',quantity_keys())
    if state=='confirm':return await say(u,'Please use a button to confirm, go back, restart, or cancel:',confirmation_keys())
    await say(u,'Use /buy to book, /orders for your bookings, or /help for assistance.')
async def review(u,c):
    if not await staff(u):return
    rows=ledger.queue()
    if not rows:return await say(u,'No payments awaiting review.')
    for r in rows:
        await say(u,"REQUIRES BANK VERIFICATION\n"+bank_review_details(r)+"\n\n"
            'Open your receiving UOB account. Match an incoming credit by bank sender full name, exact amount and bank date. Check any order remark if another person paid. If the name differs, ask the guest to use /payer ORDER FULL_BANK_SENDER_NAME. An email or guest claim alone does not verify payment.\n\n'
            'The next message is a ready-to-copy command. Send it only after checking UOB. Replace the date or sender if the bank shows different details. Identical sender, amount and date used for another order are blocked for manual resolution.')
        await say(u,approval_command(r))
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
        await bot.send_photo(r['user_id'],photo=render_ticket(t),caption=f"Payment verified by event staff.\nTicket #{t['label']:03d}\nOrder: {r['serial']}\nOne guest per QR. /tickets resends this same ticket; it does not create another entry.")
        ledger.delivered(t['token'])
async def add_promoter_cmd(u,c):
    if not await staff(u):return
    if len(c.args)<2:return await say(u,'Use /addpromoter NAME20 Promoter full name. Add the same code to the Promoters sheet.')
    try:ledger.add_promoter(c.args[0],' '.join(c.args[1:]),u.effective_user.id)
    except ValueError as exc:return await say(u,str(exc))
    status='20% discounts are open.' if ledger.promoter_discounts_enabled() else 'Discounts are paused; the code is saved for reopening and can track referrals now.'
    await say(u,f'Promoter code {c.args[0].upper()} saved. {status} Enter it in the Promoters sheet as well.')
async def promoter_discounts_cmd(u,c):
    if not await staff(u):return
    if len(c.args)!=1 or c.args[0].lower() not in ('on','off'):
        state='OPEN' if ledger.promoter_discounts_enabled() else 'PAUSED'
        return await say(u,f'Promoter discounts: {state}. Use /promodiscounts on or /promodiscounts off. Existing orders keep their quoted price.')
    enabled=c.args[0].lower()=='on'
    ledger.set_promoter_discounts(enabled,u.effective_user.id)
    await say(u,'Promoter discounts are now '+('OPEN: valid codes give 20% off new bookings.' if enabled else 'PAUSED: new bookings use standard prices; referral tracking remains available.')+' Existing orders keep their quoted price.')

async def promoters_cmd(u,c):
    if not await staff(u):return
    stats=ledger.promoter_stats()
    state='OPEN' if ledger.promoter_discounts_enabled() else 'PAUSED'
    await say(u,f'Promoter discounts: {state}\nPromoter counts (ticket quantities):\n'+'\n'.join(
        f"{p['name']} · {p['code']}: {p['booked']} booked, {p['paid']} paid, {p['checked_in']} checked in"
        for p in stats))
async def approve(u,c):
    if not await staff(u):return
    if len(c.args)<4:return await say(u,'After checking your incoming UOB transaction: /approve ORDER YYYY-MM-DD AMOUNT FULL_BANK_SENDER_NAME\nThis records your bank verification and issues live tickets.')
    serial,bank_date,amount,*sender_parts=c.args
    sender=' '.join(sender_parts)
    if bank_date=='YYYY-MM-DD' or sender.upper()=='FULL_BANK_SENDER_NAME':
        return await say(u,'Replace the date and sender placeholders with the details shown by UOB.')
    try:
        money=Decimal(amount)
        if not money.is_finite() or money<=0 or money*100!=(money*100).to_integral_value():raise ValueError('Invalid payment amount.')
        r=ledger.approve_matched(serial,sender,bank_date,int(money*100),u.effective_user.id)
    except (ValueError,InvalidOperation) as exc:return await say(u,str(exc))
    await say(u,'Bank verification saved. Sending tickets.')
    try:await deliver(c.bot,r)
    except Exception:await say(u,'Approval saved but delivery failed. Automatic retry runs every minute. /resend ORDER retries the same tickets.')
async def payer_cmd(u,c):
    if not await private(u):return
    if len(c.args)<2:return await say(u,'Use /payer ORDER FULL_BANK_SENDER_NAME if the bank account paying differs from your booking name.')
    serial=c.args[0]
    try:status=ledger.set_payer(serial,u.effective_user.id,' '.join(c.args[1:]))
    except ValueError as exc:return await say(u,str(exc))
    await say(u,'Payer name saved for this order. Staff will still verify the incoming payment. Do not pay twice.')
    if status in ('review','review_late'):await notify(c.bot,f'Payer name updated for {serial}. Check /review and verify the bank credit before approval.')
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
    if not await private(u):return
    if not ledger.door_authorized(u.effective_user.id,ADMINS):
        return await say(u,'Scanner access has not been granted. Send /whoami to the organiser so they can add your Telegram ID.')
    bridge=c.application.bot_data.get('door_bridge')
    if not bridge:return await say(u,'Scanner connection is unavailable. Contact an organiser for admission help.')
    try:
        if c.args and c.args[0]=='revoke':
            await bridge.revoke(u.effective_user.id)
            return await say(u,'All scanner sessions for your account have been signed out.')
        link=await bridge.login(u.effective_user.id)
        await u.effective_chat.send_message('Private door scanner link (8 hours). Open in Safari or Chrome, then enable the camera. Valid ticket scans immediately record entry. Keep this link private. /scanner revoke signs out your devices.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('Open door scanner',url=link)]]),protect_content=True)
    except Exception:await say(u,'Scanner connection is unavailable. Try again shortly or contact an organiser.')

async def grant_door_cmd(u,c):
    if not await staff(u):return
    if len(c.args)!=1 or not c.args[0].isdigit() or int(c.args[0])<=0:
        return await say(u,'Use /grantdoor TELEGRAM_ID. Ask the staff member to send /whoami to this bot first.')
    target=int(c.args[0])
    ledger.grant_door(target,u.effective_user.id)
    await say(u,f'Scanner access granted to Telegram ID {target}. They can now send /scanner in their own private chat with this bot. Payment approvals and backups remain admin-only.')

async def revoke_door_cmd(u,c):
    if not await staff(u):return
    if len(c.args)!=1 or not c.args[0].isdigit() or int(c.args[0])<=0:
        return await say(u,'Use /revokedoor TELEGRAM_ID.')
    target=int(c.args[0])
    if target in ADMINS:return await say(u,'That ID is an admin. Remove it from ADMIN_USER_IDS in Render to revoke admin access.')
    removed=ledger.revoke_door(target,u.effective_user.id)
    bridge=c.application.bot_data.get('door_bridge')
    try:
        if bridge:await bridge.revoke(target)
    except Exception:
        return await say(u,f'Door permission removed for {target}, but the browser session could not be signed out now. The bot will reject further admissions from it; retry /revokedoor when the scanner connection returns.')
    await say(u,f'Door access revoked for {target}; existing scanner links have been signed out.' if removed else f'{target} was not on the door staff list. Any existing scanner links were signed out.')

async def door_staff_cmd(u,c):
    if not await staff(u):return
    rows=ledger.door_staff_list()
    await say(u,'Door scanner staff (Telegram IDs):\n'+('\n'.join(str(r['user_id']) for r in rows) if rows else 'None yet. Use /grantdoor TELEGRAM_ID.'))

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
    await app.bot.set_my_commands([BotCommand('start','Main menu'),BotCommand('buy','Book tickets'),BotCommand('orders','My orders'),BotCommand('tickets','Resend paid tickets'),BotCommand('help','Contact an admin')])
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
    if opened() and not os.getenv('PAYNOW_RECIPIENT_NAME','').strip():raise SystemExit('Set verified PAYNOW_RECIPIENT_NAME before opening sales.')
    try:payment_image(2500)
    except (ValueError,OSError):raise SystemExit('Add valid private PAYNOW_QR_PAYLOAD in Render.')
    ledger=Ledger(DATA/'dnd-live.sqlite3',int(os.getenv('EVENT_CAPACITY','230')),os.getenv('EVENT_ID','DND26'))
    app=Application.builder().token(token).concurrent_updates(False).post_init(setup).post_stop(shutdown).build()
    for cmd,fn in [('start',start),('buy',buy),('orders',orders),('event',event_cmd),('prices',prices_cmd),('terms',terms_cmd),('tickets',tickets),('cancel',cancel),('help',help_cmd),('payer',payer_cmd),('whoami',whoami),('review',review),('approve',approve),('resend',resend),('addpromoter',add_promoter_cmd),('promoters',promoters_cmd),('promodiscounts',promoter_discounts_cmd),('check',check),('reject',resolve),('void',resolve),('reply',reply),('backup',backup_cmd),('scanner',scanner_cmd),('grantdoor',grant_door_cmd),('revokedoor',revoke_door_cmd),('doorstaff',door_staff_cmd)]:app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,answer))
    app.add_error_handler(error)
    app.run_polling(allowed_updates=['message','callback_query'],drop_pending_updates=False)

