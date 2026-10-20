"""DND Nights stage 2. TEST ONLY: simulated approval and test QR check-in."""
import io
import json
from decimal import Decimal, InvalidOperation
import qrcode
from PIL import Image, ImageDraw, ImageFont
import logging
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from store import Store

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
store = Store(ROOT / 'test_bookings.sqlite3')
store.stage2()
logging.basicConfig(level=logging.WARNING)
# HTTP request URLs contain the bot token; do not enable HTTP debug logging.
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)

def buttons(*items):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=key)] for label, key in items])

def offer():
    today = datetime.now(ZoneInfo('Asia/Singapore')).date()
    cutoff = date.fromisoformat(os.getenv('EARLY_BIRD_CUTOFF', '2026-11-14'))
    event = date.fromisoformat(os.getenv('EVENT_DATE', '2026-11-28'))
    if today > event:
        return None
    return ('Walk-in', 35) if today == event else (('Early bird', 25) if today <= cutoff else ('Presale', 30))

async def say(update, text, markup=None):
    await update.effective_chat.send_message(text, reply_markup=markup)

async def allowed(update):
    if update.effective_chat.type != 'private':
        return False
    ids = {int(x.strip()) for x in os.getenv('TEST_USER_IDS', '').split(',') if x.strip().isdigit()}
    if update.effective_user.id not in ids:
        await say(update, 'DND Nights is being tested. Sales are not open yet. Use /whoami to find your testing ID.')
        return False
    return True

async def whoami(update, context):
    if update.effective_chat.type == 'private':
        await say(update, f'Your Telegram user ID: {update.effective_user.id}\nAdd it to TEST_USER_IDS in your local .env, then restart the bot.')

async def start(update, context):
    if not await allowed(update):
        return
    await say(update, 'Welcome to DND Nights!\n\nTEST MODE — no money will be collected.\nBook through a few quick questions.',
              buttons(('Buy tickets', 'buy'), ('My test orders', 'orders'), ('Event details', 'event')))

async def buy(update, context):
    if not await allowed(update):
        return
    await say(update, 'DND Nights · Dance and Desi\n28 November 2026 · Singapore\n\nChoose the current offer. Test prices only; final terms and capacity must be confirmed before sales open.',
              buttons(('Continue', 'select'), ('Cancel', 'cancel')))

async def cancel(update, context):
    if not await allowed(update):
        return
    store.clear(update.effective_user.id)
    await say(update, 'Booking cancelled. Existing orders are unchanged. Use /buy to begin again.')

async def orders(update, context):
    if not await allowed(update):
        return
    rows = store.orders(update.effective_user.id)
    text = '\n\n'.join(f"TEST order {r['serial']}\nTicket label reserved: #{r['suffix']:03d}\nStatus: {r['status']}" for r in rows)
    await say(update, text or 'No test orders yet. Use /buy.')
    for row in rows:
        if row['status'] == 'test_pending':
            await say(update, f"Order {row['serial']} — do not pay.", buttons(('Simulate payment submitted', f"review:{row['serial']}")))

async def click(update, context):
    q = update.callback_query
    await q.answer()
    if not await allowed(update):
        return
    key, user = q.data, update.effective_user.id
    if key.startswith('review:'):
        serial = key.split(':', 1)[1]
        changed = store.request_review(serial, user)
        await say(update, 'TEST payment submitted for review. No real money should be sent.' if changed else 'This order has already been submitted or is unavailable.')
        if changed:
            for admin in admin_ids():
                try:
                    await context.bot.send_message(admin, f'TEST payment review requested: {serial}\nUse /review to inspect. No bank verification has occurred.')
                except Exception:
                    pass  # Persisted review queue remains available through /review.
        return
    if key.startswith('admit:'):
        if not await is_admin(update):
            return
        token = key.split(':', 1)[1]
        ok = store.admit(token, user)
        return await say(update, 'TEST ADMITTED — first use recorded.' if ok else 'BLOCKED — ticket already used or invalid.')
    if key == 'buy':
        return await buy(update, context)
    if key == 'orders':
        return await orders(update, context)
    if key == 'event':
        return await say(update, 'DND Nights · 28 November 2026\nThis is a private testing flow. Final event and refund terms will appear before payment.')
    if key == 'cancel':
        return await cancel(update, context)
    state, data = store.draft(user)
    if key in ('select', 'edit'):
        current = offer()
        if not current:
            return await say(update, 'Sales period has ended.')
        tier, price = current
        store.save(user, 'name', {'tier': tier, 'price': price})
        return await say(update, f'TEST · {tier}: S${price}\n\nQuestion 1 of 4: What is your full name?\nUse /cancel to stop.')
    if key.startswith('source:') and state == 'source':
        source = key.split(':', 1)[1]
        if source not in ('Instagram', 'Friend', 'Other'):
            return
        data['source'] = source
        store.save(user, 'quantity', data)
        return await say(update, 'Question 4 of 4: How many tickets?', buttons(('1', 'qty:1'), ('2', 'qty:2')))
    if key.startswith('qty:') and state == 'quantity':
        if key not in ('qty:1', 'qty:2'):
            return
        data['quantity'] = int(key[-1])
        store.save(user, 'confirm', data)
        return await say(update,
            f"Please confirm:\nName: {data['name']}\nContact: {data['contact']}\nSource: {data['source']}\n"
            f"Offer: {data['tier']}\nQuantity: {data['quantity']}\nTotal: S${data['price'] * data['quantity']}\n\n"
            'TEST ONLY. This creates an unpaid test booking. No valid entry ticket is issued. Your answers are stored locally for testing.',
            buttons(('Looks good — save test booking', 'confirm'), ('Make a change', 'edit'), ('Cancel', 'cancel')))
    if key == 'confirm' and state == 'confirm':
        try:
            serial, suffix, data = store.create(user)
        except ValueError as exc:
            return await say(update, str(exc))
        await q.edit_message_reply_markup(reply_markup=None)
        return await say(update, f'TEST booking saved!\n\nOrder serial: {serial}\nReserved first ticket label: #{suffix:03d}\n'
                         f"Quantity: {data['quantity']}\nTotal: S${data['price'] * data['quantity']}\n\n"
                         'Do not pay. Tap below to simulate submitting a payment for admin review.\nUse /orders to retrieve this booking.', buttons(('Simulate payment submitted', f'review:{serial}')))
    await say(update, 'That button belongs to an older step. Continue with the latest question, or use /buy.')

async def answer(update, context):
    if not await allowed(update):
        return
    user, text = update.effective_user.id, update.message.text.strip()
    state, data = store.draft(user)
    if state == 'name':
        if not 2 <= len(text) <= 80:
            return await say(update, 'Please enter a name between 2 and 80 characters.')
        data['name'] = text
        store.save(user, 'contact', data)
        return await say(update, f'Thanks, {text}!\n\nQuestion 2 of 4: Your phone number or Instagram handle?')
    if state == 'contact':
        if not 3 <= len(text) <= 80:
            return await say(update, 'Please enter a contact between 3 and 80 characters.')
        data['contact'] = text
        store.save(user, 'source', data)
        return await say(update, 'Question 3 of 4: Where did you hear about us?', buttons(('Instagram', 'source:Instagram'), ('Friend', 'source:Friend'), ('Other', 'source:Other')))
    await say(update, 'Please use the latest buttons, or /buy to begin. Use /cancel to clear a draft.')

def admin_ids():
    return {int(x.strip()) for x in os.getenv('ADMIN_USER_IDS', '').split(',') if x.strip().isdigit()}

async def is_admin(update):
    if not await allowed(update):
        return False
    if update.effective_user.id not in admin_ids():
        await say(update, 'This command is for authorised staff only.')
        return False
    return True

async def review(update, context):
    if not await is_admin(update):
        return
    rows = store.review()
    if not rows:
        return await say(update, 'No test payments awaiting review.')
    for row in rows:
        data = json.loads(row['details'])
        total = data['price'] * data['quantity']
        await say(update, f"TEST REVIEW\nOrder: {row['serial']}\nName: {data['name']}\nQuantity: {data['quantity']}\nExpected: S${total}\n\n"
                  f"Simulate approval:\n/approve {row['serial']} TEST-{row['serial']} {total}\n\n"
                  f"Return to pending:\n/reject {row['serial']}\n\nNo bank connection exists. These commands record a staff decision only.")

def ticket_image(row):
    qr = qrcode.make('DNDTEST:' + row['token']).convert('RGB').resize((480, 480), Image.Resampling.NEAREST)
    canvas = Image.new('RGB', (560, 640), 'white')
    canvas.paste(qr, (40, 70))
    draw = ImageDraw.Draw(canvas)
    draw.font = ImageFont.load_default(size=18)
    draw.text((30, 20), f"TEST ONLY - DND Nights - Ticket #{row['label']:03d}", fill='black')
    draw.text((30, 565), f"Order: {row['serial']}", fill='black')
    draw.text((30, 595), 'NOT VALID FOR REAL EVENT ENTRY', fill='black')
    result = io.BytesIO()
    canvas.save(result, format='PNG')
    result.seek(0)
    return result

async def deliver(bot, order):
    for ticket in store.tickets(order['serial']):
        await bot.send_document(chat_id=order['user_id'], document=ticket_image(ticket),
            filename=f"TEST_ticket_{ticket['label']:03d}.png",
            caption=f"TEST ONLY — Ticket #{ticket['label']:03d}\nOrder {order['serial']}\nOne QR per guest. Not valid for the real event.\nResend with /tickets; resending keeps the same QR.")
        store.delivered(ticket['token'])

async def approve(update, context):
    if not await is_admin(update):
        return
    if len(context.args) != 3:
        return await say(update, 'Use /approve ORDER TEST-REFERENCE AMOUNT — fictional payments only.')
    serial, reference, amount = context.args
    try:
        value = Decimal(amount)
        if not value.is_finite() or value <= 0 or value * 100 != (value * 100).to_integral_value():
            raise ValueError('Enter a positive amount with at most two decimal places.')
        order = store.approve(serial, reference, int(value * 100), update.effective_user.id)
    except (ValueError, InvalidOperation) as exc:
        return await say(update, str(exc))
    await say(update, 'Test approval saved. Sending QR tickets now.')
    try:
        await deliver(context.bot, order)
    except Exception:
        await say(update, 'Delivery failed; approval is saved. Use /resend ORDER to retry the same tickets. Do not approve again.')

async def tickets(update, context):
    if not await allowed(update):
        return
    rows = [r for r in store.orders(update.effective_user.id) if r['status'] == 'test_approved']
    if not rows:
        return await say(update, 'No approved test tickets yet. Use /orders to see pending bookings.')
    for row in rows:
        await deliver(context.bot, row)

async def resend(update, context):
    if not await is_admin(update):
        return
    row = store.order(context.args[0]) if len(context.args) == 1 else None
    if not row or row['status'] != 'test_approved':
        return await say(update, 'Use /resend ORDER for an approved test order.')
    await deliver(context.bot, row)
    await say(update, 'Same QR tickets resent.')

async def reject(update, context):
    if not await is_admin(update):
        return
    ok = len(context.args) == 1 and store.reject(context.args[0], update.effective_user.id)
    await say(update, 'Returned to pending; no ticket issued.' if ok else 'Use /reject ORDER for an order awaiting review.')

async def check(update, context):
    if not await is_admin(update):
        return
    if len(context.args) != 1:
        return await say(update, 'Scan the TEST QR using a QR reader, copy its text, then send /check DNDTEST:token')
    token = context.args[0].removeprefix('DNDTEST:')
    ticket = store.lookup(token)
    if not ticket:
        return await say(update, 'INVALID — ticket not found.')
    if ticket['used_at']:
        return await say(update, f"ALREADY USED — #{ticket['label']:03d}\nFirst check-in: {ticket['used_at']}")
    data = json.loads(ticket['details'])
    await say(update, f"VALID TEST TICKET #{ticket['label']:03d}\nOrder: {ticket['serial']}\nBooker: {data['name']}\nNot admitted yet. Tap once below to record test entry.",
              buttons(('Admit test guest', 'admit:' + token)))

async def setup(app):
    hook = await app.bot.get_webhook_info()
    if hook.url and os.getenv('ALLOW_WEBHOOK_SWITCH', 'false').lower() != 'true':
        raise RuntimeError('An existing webhook is active. Stop its backend first; then set ALLOW_WEBHOOK_SWITCH=true in .env if you want this local bot to take over.')
    await app.bot.set_my_commands([BotCommand('start','Main menu'), BotCommand('buy','Start a test booking'), BotCommand('orders','My test bookings'), BotCommand('cancel','Cancel the current draft'), BotCommand('whoami','Find my testing ID')])
    print(f'Connected as @{app.bot.username}. TEST MODE. Open Telegram and send /whoami first. Stop with Ctrl+C.')

async def error(update, context):
    print(f'Bot request failed ({type(context.error).__name__}). No payment was verified. Restart if the connection failed; saved test orders remain in the database.')

if __name__ == '__main__':
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token or token == 'paste_your_token_here':
        raise SystemExit('Set TELEGRAM_BOT_TOKEN in the .env file next to bot.py. Do not share the token.')
    app = Application.builder().token(token).concurrent_updates(False).post_init(setup).build()
    for command, handler in [('start',start), ('buy',buy), ('orders',orders), ('tickets',tickets), ('review',review), ('approve',approve), ('reject',reject), ('resend',resend), ('check',check), ('cancel',cancel), ('whoami',whoami)]:
        app.add_handler(CommandHandler(command,handler))
    app.add_handler(CallbackQueryHandler(click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,answer))
    app.add_error_handler(error)
    app.run_polling(allowed_updates=['message','callback_query'], drop_pending_updates=False)
