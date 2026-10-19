import assert from "node:assert/strict";
import app from "../worker/index.js";

const storedObjects = new Map();
const env = {
  TELEGRAM_BOT_TOKEN: "telegram-test-token",
  TELEGRAM_WEBHOOK_SECRET: "telegram-hook-secret",
  TELEGRAM_BOT_USERNAME: "DND_Nights_Bot",
  TELEGRAM_ADMIN_CHAT_ID: "987654321",
  TELEGRAM_SETUP_KEY: "telegram-setup-secret",
  TICKET_SIGNING_SECRET: "0123456789abcdef0123456789abcdef",
  STRIPE_SECRET_KEY: "sk_test_example",
  STRIPE_WEBHOOK_SECRET: "whsec_test_example",
  STRIPE_PAYMENT_METHODS: "paynow,card",
  EARLY_BIRD_CUTOFF: "2099-10-31",
  EVENT_DATE: "2099-11-14",
  BUCKET: {
    async get(key) {
      const stored = storedObjects.get(key);
      if (!stored) return null;
      return {
        body: stored.body,
        httpMetadata: stored.httpMetadata,
        async text() { return new TextDecoder().decode(stored.body); },
      };
    },
    async put(key, body, options = {}) {
      const bytes = typeof body === "string" ? new TextEncoder().encode(body) : new Uint8Array(body);
      storedObjects.set(key, { body: bytes, httpMetadata: options.httpMetadata || {} });
    },
  },
};

const calls = [];
let checkoutNumber = 0;
let nextTelegramMessageId = 1;
globalThis.fetch = async (url, options = {}) => {
  const target = String(url);
  if (target === "https://api.stripe.com/v1/checkout/sessions") {
    const params = new URLSearchParams(options.body);
    calls.push({ service: "stripe", url: target, params, headers: options.headers });
    checkoutNumber += 1;
    return Response.json({ id: `cs_test_${checkoutNumber}`, url: `https://checkout.stripe.test/c/pay/${checkoutNumber}` });
  }
  if (target.startsWith("https://api.telegram.org/")) {
    const body = JSON.parse(options.body);
    calls.push({ service: "telegram", url: target, body, headers: options.headers });
    return Response.json({ ok: true, result: { message_id: nextTelegramMessageId++ } });
  }
  throw new Error(`Unexpected external request: ${target}`);
};

const buyer = { id: 123456789, first_name: "Test" };
const buyerChat = { id: 123456789, type: "private" };

function telegramRequest(text, from = buyer, chat = buyerChat, updateId = 1) {
  return new Request("https://example.test/telegram/webhook", {
    method: "POST",
    headers: { "x-telegram-bot-api-secret-token": env.TELEGRAM_WEBHOOK_SECRET, "content-type": "application/json" },
    body: JSON.stringify({ update_id: updateId, message: { message_id: updateId + 10, from, chat, date: 1, text } }),
  });
}

async function stripeHeader(rawBody, timestamp = Math.floor(Date.now() / 1000)) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(env.STRIPE_WEBHOOK_SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(`${timestamp}.${rawBody}`)));
  const hex = Array.from(signature, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `t=${timestamp},v1=${hex}`;
}

async function stripeWebhook(session, eventId = "evt_test_1") {
  const rawBody = JSON.stringify({ id: eventId, type: "checkout.session.completed", data: { object: session } });
  return new Request("https://example.test/stripe/webhook", {
    method: "POST",
    headers: { "content-type": "application/json", "stripe-signature": await stripeHeader(rawBody) },
    body: rawBody,
  });
}

let response = await app.fetch(telegramRequest("/start"), env, {});
assert.equal(response.status, 200);
const firstCheckout = calls.find((call) => call.service === "stripe");
assert.equal(firstCheckout.params.get("line_items[0][price_data][unit_amount]"), "2500");
assert.equal(firstCheckout.params.get("payment_method_types[0]"), "paynow");
assert.equal(firstCheckout.params.get("payment_method_types[1]"), "card");
const intro = calls.find((call) => call.service === "telegram" && call.body.text?.includes("Welcome to DND Nights"));
assert.ok(intro);
assert.equal(intro.body.reply_markup.inline_keyboard[0][0].url, "https://checkout.stripe.test/c/pay/1");

calls.length = 0;
response = await app.fetch(telegramRequest("/restart", buyer, buyerChat, 2), env, {});
assert.equal(response.status, 200);
assert.ok(calls.some((call) => call.service === "stripe"));
assert.ok(calls.some((call) => call.service === "telegram" && call.body.text?.includes("Welcome to DND Nights")));

const paidSession = {
  id: "cs_test_paid_1",
  mode: "payment",
  payment_status: "paid",
  amount_total: 2500,
  currency: "sgd",
  payment_intent: "pi_test_paid_1",
  client_reference_id: "DND-order-1",
  metadata: {
    kind: "dnd_ticket",
    order_id: "DND-order-1",
    telegram_user_id: String(buyer.id),
    telegram_chat_id: String(buyerChat.id),
    ticket_price: "25",
    ticket_tier: "early",
  },
};

calls.length = 0;
response = await app.fetch(await stripeWebhook(paidSession), env, {});
assert.equal(response.status, 200);
const issuedPhoto = calls.find((call) => call.service === "telegram" && call.url.endsWith("/sendPhoto"));
assert.ok(issuedPhoto);
assert.match(issuedPhoto.body.caption, /entry ticket issued/);
assert.match(issuedPhoto.body.photo, /^https:\/\/example\.test\/ticket\/qr\/[A-Za-z0-9_-]{20,32}\.png$/);
const ticketToken = issuedPhoto.body.photo.match(/\/ticket\/qr\/([A-Za-z0-9_-]+)\.png$/)[1];

calls.length = 0;
response = await app.fetch(await stripeWebhook(paidSession, "evt_test_duplicate"), env, {});
assert.equal(response.status, 200);
assert.equal(calls.filter((call) => call.service === "telegram" && call.url.endsWith("/sendPhoto")).length, 0);

response = await app.fetch(new Request(`https://example.test/ticket/qr/${ticketToken}.png`), env, {});
assert.equal(response.status, 200);
assert.equal(response.headers.get("content-type"), "image/png");
assert.deepEqual(Array.from(new Uint8Array(await response.arrayBuffer()).slice(0, 8)), [137, 80, 78, 71, 13, 10, 26, 10]);

calls.length = 0;
const admin = { id: 987654321, first_name: "Organiser" };
const adminChat = { id: 987654321, type: "private" };
response = await app.fetch(telegramRequest(`/start check_${ticketToken}`, admin, adminChat, 3), env, {});
assert.equal(response.status, 200);
assert.ok(calls.some((call) => call.body?.text?.includes("ADMIT GUEST")));

calls.length = 0;
response = await app.fetch(telegramRequest(`/start check_${ticketToken}`, admin, adminChat, 4), env, {});
assert.equal(response.status, 200);
assert.ok(calls.some((call) => call.body?.text?.includes("DO NOT ADMIT")));

calls.length = 0;
const secondPaidSession = { ...paidSession, id: "cs_test_paid_2", payment_intent: "pi_test_paid_2", client_reference_id: "DND-order-2", metadata: { ...paidSession.metadata, order_id: "DND-order-2" } };
response = await app.fetch(await stripeWebhook(secondPaidSession, "evt_test_2"), env, {});
assert.equal(response.status, 200);
const secondPhoto = calls.find((call) => call.service === "telegram" && call.url.endsWith("/sendPhoto"));
assert.ok(secondPhoto);
assert.notEqual(secondPhoto.body.photo, issuedPhoto.body.photo);

const invalidBody = JSON.stringify({ id: "evt_bad", type: "checkout.session.completed", data: { object: paidSession } });
response = await app.fetch(new Request("https://example.test/stripe/webhook", { method: "POST", headers: { "stripe-signature": "t=1,v1=bad" }, body: invalidBody }), env, {});
assert.equal(response.status, 400);

console.log(JSON.stringify({ checkout: "Stripe PayNow + card", restart: "introduction replayed", ticketQr: "unique per paid Checkout Session", checkIn: "one use", duplicateWebhook: "idempotent" }));
