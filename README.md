# DND Nights — Dance and Desi

An event landing page and Telegram ticket bot in one Cloudflare Worker.

## Ticket flow

1. A buyer sends `/start` or `/restart` to the Telegram bot.
2. The bot introduces DND Nights, calculates the current S$25/S$30/S$35 tier and creates a new Stripe Checkout Session.
3. Stripe Checkout offers PayNow and card in SGD. The Checkout Session expires after 30 minutes.
4. Stripe sends a signed webhook after a completed payment. The success page never issues a ticket by itself.
5. The bot creates a unique ticket for that paid Checkout Session, stores it in the private R2 bucket and sends its QR code in Telegram.
6. At the door, the organiser scans the QR. It opens the bot with a signed ticket token; the configured organiser account can mark it used. A second scan returns `DO NOT ADMIT`.

Repeated Stripe webhooks do not create a second ticket or resend a delivered ticket. One Checkout transaction creates one entry ticket.

## Bot commands

- `/start` — introduce the event and open the current ticket offer.
- `/restart` — start the introduction and checkout flow again.
- `/tickets` — open the current ticket offer.
- `/event` — show date and venue status.
- `/drinks` — show the drinks policy.
- `/support` — show organiser support details.
- `/whoami` — show the Telegram user and chat IDs needed for configuration.

## Required configuration

Copy the keys from `.env.example` into the Site environment settings. Keep all secret values out of Git.

The Telegram token previously shared in chat must be revoked in BotFather and replaced with a new token before deployment. Set `TELEGRAM_ADMIN_USER_ID` to the personal Telegram user ID allowed to check tickets in. `TELEGRAM_ADMIN_CHAT_ID` can still be used for organiser notifications and is the check-in fallback when no separate user ID is set.

Create a Stripe Singapore account, finish its verification and enable PayNow. Set:

- `STRIPE_SECRET_KEY` to the Stripe test or live secret key.
- `STRIPE_WEBHOOK_SECRET` to the signing secret for the deployed `/stripe/webhook` endpoint.
- `STRIPE_PAYMENT_METHODS` to `paynow,card` (the default) or another account-supported list.

In Stripe Workbench, add this webhook endpoint:

```text
https://YOUR-SITE-DOMAIN/stripe/webhook
```

Subscribe it to:

```text
checkout.session.completed
checkout.session.async_payment_succeeded
```

After deployment, register the Telegram webhook and command menu by making a `POST` request to `/telegram/setup` with `Authorization: Bearer <TELEGRAM_SETUP_KEY>`.

## Local verification

```text
npm install
npm test
npm run build
npm run validate
```

The integration test covers Stripe Checkout creation, `/restart`, Stripe signature verification, payment-to-ticket issuance, duplicate webhook handling, unique QRs and one-use organiser check-in.

## Launch checks

Before switching from Stripe test mode to live mode, confirm the final event date, venue, approved capacity, ticket/refund terms and required venue/licensing approvals. Make sure `EARLY_BIRD_CUTOFF`, `EVENT_DATE` and `EVENT_DATE_LABEL` all describe the same confirmed event schedule.
