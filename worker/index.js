import QRCode from "qrcode";

const TICKETS = {
  early: { label: "Early bird", price: 25, note: "Limited first release" },
  regular: { label: "Regular", price: 30, note: "General release" },
  walkin: { label: "Walk-in", price: 35, note: "Subject to capacity" },
};

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });

const escapeHtml = (value = "") =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

const compact = (value, max = 180) =>
  String(value || "").replace(/\s+/g, " ").trim().slice(0, max);

function eventConfig(env) {
  return {
    title: env.EVENT_TITLE || "DND Nights",
    date: env.EVENT_DATE_LABEL || "Saturday, 28 November 2026 · 6:30–10:30pm",
    venue: env.EVENT_VENUE_LABEL || "Skyfall Rooftop Restrobar · 50 Telok Blangah Road, Singapore",
    botUsername: String(env.TELEGRAM_BOT_USERNAME || "").replace(/^@/, ""),
    support: env.SUPPORT_HANDLE || "Organiser contact coming soon",
    status: env.EVENT_STATUS || "planning",
  };
}

function renderPage(config) {
  const publicConfig = JSON.stringify({
    botUsername: config.botUsername,
    status: config.status,
  }).replaceAll("<", "\\u003c");
  const isLive = config.status === "on-sale";

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#061425">
  <meta name="description" content="${escapeHtml(config.title)} — a culture-first Deepavali celebration in Singapore.">
  <title>${escapeHtml(config.title)}</title>
  <style>
    :root {
      --ink: #061425; --wine: #0a2342; --wine-2: #123e70; --saffron: #dda52d;
      --gold: #f7cf68; --cream: #fff5d6; --paper: #fffaf0; --muted: #596579;
      --line: rgba(10, 35, 66, .16); --shadow: 0 24px 70px rgba(6, 20, 37, .18);
      --serif: Georgia, "Times New Roman", serif;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; color: var(--ink); background: var(--paper); font-family: var(--sans); line-height: 1.55; }
    button, input, select { font: inherit; }
    a { color: inherit; }
    .skip { position: absolute; left: -999px; top: .5rem; z-index: 20; padding: .7rem 1rem; background: white; }
    .skip:focus { left: .5rem; }
    .nav { position: absolute; inset: 0 0 auto; z-index: 10; display: flex; align-items: center; justify-content: space-between; width: min(1180px, calc(100% - 40px)); margin: auto; padding: 24px 0; color: white; }
    .brand { display: flex; gap: 12px; align-items: center; text-decoration: none; font-weight: 800; letter-spacing: .02em; }
    .brand-mark { display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid rgba(255,214,118,.6); border-radius: 50%; color: var(--gold); }
    .brand-mark svg { width: 24px; height: 24px; }
    .nav-links { display: flex; gap: 24px; align-items: center; font-size: .9rem; }
    .nav-links a { text-decoration: none; color: rgba(255,255,255,.84); }
    .nav-links a:hover { color: white; }
    .nav-cta { border: 1px solid rgba(255,214,118,.75); border-radius: 999px; padding: 9px 16px; color: var(--gold) !important; }
    .page-progress { position: fixed; inset: 0 auto auto 0; z-index: 100; width: 0; height: 3px; background: linear-gradient(90deg, #b98316, var(--gold)); box-shadow: 0 0 16px rgba(247,207,104,.7); }
    .hero { position: relative; min-height: 800px; overflow: hidden; color: white; background: radial-gradient(circle at 82% 18%, rgba(247,207,104,.18), transparent 25%), radial-gradient(circle at 9% 80%, rgba(31,85,142,.42), transparent 32%), linear-gradient(135deg, #030c18 0%, #0a2342 52%, #061425 100%); }
    .hero:before { content: ""; position: absolute; width: 560px; height: 560px; right: -80px; top: 90px; opacity: .28; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 300 300'%3E%3Cg fill='none' stroke='%23ffd676' stroke-width='1'%3E%3Ccircle cx='150' cy='150' r='112'/%3E%3Ccircle cx='150' cy='150' r='82'/%3E%3Cpath d='M150 18c21 39 21 75 0 107-21-32-21-68 0-107Zm0 264c21-39 21-75 0-107-21 32-21 68 0 107ZM18 150c39-21 75-21 107 0-32 21-68 21-107 0Zm264 0c-39-21-75-21-107 0 32 21 68 21 107 0Z'/%3E%3Cpath d='M57 57c42 13 68 39 76 77-38-8-64-34-76-77Zm186 186c-42-13-68-39-76-77 38 8 64 34 76 77ZM57 243c13-42 39-68 77-76-8 38-34 64-77 76ZM243 57c-13 42-39 68-77 76 8-38 34-64 77-76Z'/%3E%3C/g%3E%3C/svg%3E"); background-size: contain; animation: turn 42s linear infinite; }
    @keyframes turn { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } .hero:before { animation: none; } }
    .hero-inner { position: relative; z-index: 1; width: min(1180px, calc(100% - 40px)); margin: auto; padding: 176px 0 96px; }
    .status { display: inline-flex; align-items: center; gap: 8px; border: 1px solid rgba(255,214,118,.34); border-radius: 999px; padding: 8px 13px; color: var(--gold); background: rgba(255,255,255,.05); font-size: .82rem; font-weight: 750; text-transform: uppercase; letter-spacing: .09em; }
    .status i { width: 7px; height: 7px; border-radius: 50%; background: var(--saffron); box-shadow: 0 0 0 5px rgba(244,165,28,.12); }
    h1 { max-width: 800px; margin: 28px 0 20px; font: 400 clamp(4rem, 10vw, 8.4rem)/.84 var(--serif); letter-spacing: -.065em; }
    .hero-copy { max-width: 620px; margin: 0; color: rgba(255,255,255,.78); font-size: clamp(1.05rem, 2vw, 1.35rem); }
    .hero-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 34px; }
    .button { display: inline-flex; align-items: center; justify-content: center; gap: 9px; min-height: 48px; border: 1px solid transparent; border-radius: 999px; padding: 12px 20px; text-decoration: none; font-weight: 800; cursor: pointer; }
    .button-primary { color: var(--ink); background: var(--gold); }
    .button-primary:hover { background: white; }
    .button-ghost { color: white; border-color: rgba(255,255,255,.3); background: rgba(255,255,255,.05); }
    .hero-meta { display: grid; grid-template-columns: repeat(3, 1fr); max-width: 820px; margin-top: 70px; border-top: 1px solid rgba(255,255,255,.16); }
    .meta { padding: 20px 24px 0 0; }
    .meta small { display: block; color: rgba(255,255,255,.48); font-size: .73rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    .meta strong { display: block; margin-top: 6px; font-family: var(--serif); font-size: 1.1rem; font-weight: 400; }
    .notice { color: #4f3d32; background: #ffecbb; border-bottom: 1px solid #f0d38b; }
    .notice-inner { display: flex; gap: 12px; align-items: flex-start; width: min(1180px, calc(100% - 40px)); margin: auto; padding: 15px 0; font-size: .9rem; }
    .notice strong { color: var(--ink); white-space: nowrap; }
    main section { padding: 92px 0; }
    .wrap { width: min(1180px, calc(100% - 40px)); margin: auto; }
    .eyebrow { margin: 0 0 10px; color: var(--wine-2); font-size: .78rem; font-weight: 850; letter-spacing: .15em; text-transform: uppercase; }
    h2 { margin: 0; font: 400 clamp(2.5rem, 6vw, 5.4rem)/.95 var(--serif); letter-spacing: -.045em; }
    .section-intro { max-width: 680px; margin: 20px 0 0; color: var(--muted); font-size: 1.05rem; }
    .hero-kicker { margin: 0 0 18px; color: var(--gold); font-size: .77rem; font-weight: 850; letter-spacing: .2em; text-transform: uppercase; }
    .hero h1 em { color: var(--gold); font-style: italic; font-weight: 400; }
    .scrolly { position: relative; padding: 0; color: white; background: #061425; }
    .scrolly-grid { display: grid; grid-template-columns: .92fr 1.08fr; gap: clamp(50px, 9vw, 130px); }
    .scrolly-sticky { position: sticky; top: 0; display: grid; align-content: center; min-height: 100vh; padding: 90px 0; }
    .scrolly-sticky .eyebrow { color: var(--gold); }
    .scrolly-sticky h2 { max-width: 560px; font-size: clamp(3.6rem, 8vw, 7.2rem); }
    .scene-word { display: block; color: var(--gold); font-style: italic; }
    .scene-visual { position: relative; display: grid; place-items: center; width: min(360px, 78vw); aspect-ratio: 1; margin-top: 42px; }
    .scene-visual:before, .scene-visual:after, .scene-ring { content: ""; position: absolute; border: 1px solid rgba(247,207,104,.28); border-radius: 50%; transition: transform .8s ease, opacity .8s ease; }
    .scene-visual:before { inset: 0; }
    .scene-visual:after { inset: 15%; border-style: dashed; }
    .scene-ring { inset: 31%; background: radial-gradient(circle, rgba(247,207,104,.23), rgba(247,207,104,.02) 58%, transparent 60%); box-shadow: 0 0 80px rgba(247,207,104,.12); }
    .scene-glyph { position: relative; z-index: 2; color: var(--gold); font: 400 4.8rem var(--serif); }
    .scrolly-sticky[data-scene="2"] .scene-visual:before { transform: rotate(45deg) scale(.86); }
    .scrolly-sticky[data-scene="2"] .scene-visual:after { transform: rotate(-55deg) scale(1.16); }
    .scrolly-sticky[data-scene="3"] .scene-visual:before { transform: scale(.7); }
    .scrolly-sticky[data-scene="3"] .scene-visual:after { transform: scale(1.28); opacity: .65; }
    .scrolly-sticky[data-scene="4"] .scene-visual:before { transform: rotate(90deg) scale(1.12); }
    .scrolly-sticky[data-scene="4"] .scene-visual:after { transform: rotate(-90deg) scale(.76); }
    .chapters { border-left: 1px solid rgba(247,207,104,.16); }
    .chapter { display: grid; align-content: center; min-height: 78vh; padding: 90px 0 90px clamp(28px, 6vw, 80px); opacity: .38; transform: translateY(28px); transition: opacity .55s ease, transform .55s ease; }
    .chapter.active { opacity: 1; transform: translateY(0); }
    .chapter-num { color: var(--gold); font-size: .78rem; font-weight: 850; letter-spacing: .16em; }
    .chapter h3 { max-width: 560px; margin: 20px 0 16px; font: 400 clamp(2.4rem, 5vw, 4.7rem)/1 var(--serif); letter-spacing: -.035em; }
    .chapter p { max-width: 520px; margin: 0; color: rgba(255,255,255,.64); font-size: 1.06rem; }
    .tickets { color: white; background: var(--ink); }
    .tickets .eyebrow { color: var(--gold); }
    .tickets .section-intro { color: rgba(255,255,255,.64); }
    .tier-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 46px; }
    .tier { position: relative; overflow: hidden; display: flex; flex-direction: column; min-height: 330px; padding: 28px; border: 1px solid rgba(255,255,255,.14); border-radius: 24px; background: rgba(255,255,255,.055); }
    .tier.featured { border-color: rgba(255,214,118,.5); background: linear-gradient(155deg, rgba(255,214,118,.16), rgba(255,255,255,.05)); }
    .tier-tag { width: fit-content; border-radius: 999px; padding: 5px 9px; color: var(--gold); background: rgba(255,214,118,.13); font-size: .72rem; font-weight: 800; text-transform: uppercase; letter-spacing: .09em; }
    .tier h3 { margin: 24px 0 0; font: 400 2rem var(--serif); }
    .price { display: flex; gap: 4px; align-items: baseline; margin: 10px 0 16px; }
    .price span { color: rgba(255,255,255,.5); }
    .price strong { font: 400 3.7rem/1 var(--serif); color: var(--gold); }
    .tier p { margin: 0; color: rgba(255,255,255,.62); }
    .tier .button { width: 100%; margin-top: auto; }
    .fine { margin-top: 20px; color: rgba(255,255,255,.5); font-size: .85rem; }
    .info { background: #eef2f7; }
    .info-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 46px; }
    .info-card { padding: 28px; border-top: 3px solid var(--wine); background: white; }
    .info-card .num { color: var(--saffron); font: 400 2.3rem var(--serif); }
    .info-card h3 { margin: 26px 0 10px; font: 400 1.45rem var(--serif); }
    .info-card p { margin: 0; color: var(--muted); }
    .reserve-grid { display: grid; grid-template-columns: .78fr 1.22fr; gap: 70px; align-items: start; }
    .reserve-aside { padding: 30px; border-radius: 26px; color: white; background: var(--wine); }
    .reserve-aside h3 { margin: 0; font: 400 2rem var(--serif); }
    .reserve-aside ol { margin: 22px 0 0; padding-left: 20px; color: rgba(255,255,255,.72); }
    .reserve-aside li + li { margin-top: 12px; }
    form { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .field { display: grid; gap: 7px; }
    .field.full { grid-column: 1 / -1; }
    label { font-size: .86rem; font-weight: 800; }
    input, select { width: 100%; min-height: 50px; border: 1px solid var(--line); border-radius: 12px; padding: 11px 13px; color: var(--ink); background: white; }
    input:focus, select:focus { outline: 3px solid rgba(244,165,28,.24); border-color: var(--saffron); }
    .check { display: flex; gap: 10px; align-items: flex-start; color: var(--muted); font-size: .85rem; }
    .check input { flex: 0 0 auto; width: 18px; min-height: 18px; margin-top: 2px; }
    .honeypot { position: absolute; left: -9999px; }
    .form-actions { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
    .form-actions .button { border: 0; background: var(--wine); color: white; }
    .form-actions .button:hover { background: var(--wine-2); }
    .form-result { display: none; grid-column: 1 / -1; padding: 18px; border-radius: 14px; background: #fff5dc; }
    .form-result.show { display: block; }
    .form-result strong { display: block; margin-bottom: 5px; }
    .form-result .button { margin-top: 12px; color: white; background: #229ed9; }
    .faq-list { max-width: 860px; margin-top: 38px; border-top: 1px solid var(--line); }
    details { border-bottom: 1px solid var(--line); }
    summary { cursor: pointer; padding: 21px 0; font-weight: 800; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary:after { content: "+"; float: right; color: var(--wine-2); font-size: 1.3rem; }
    details[open] summary:after { content: "−"; }
    details p { max-width: 720px; margin: -4px 0 22px; color: var(--muted); }
    footer { padding: 50px 0 34px; color: rgba(255,255,255,.64); background: var(--ink); }
    .footer-top { display: flex; justify-content: space-between; gap: 40px; align-items: end; }
    .footer-title { max-width: 650px; margin: 0; color: white; font: 400 clamp(2rem, 5vw, 4rem)/1 var(--serif); }
    .footer-bottom { display: flex; justify-content: space-between; gap: 30px; margin-top: 60px; padding-top: 18px; border-top: 1px solid rgba(255,255,255,.12); font-size: .8rem; }
    @media (max-width: 860px) {
      .nav-links a:not(.nav-cta) { display: none; }
      .hero { min-height: 720px; }
      .hero:before { width: 430px; height: 430px; right: -180px; }
      .hero-meta, .tier-grid, .info-grid { grid-template-columns: 1fr; }
      .hero-meta { gap: 15px; }
      .meta { border-bottom: 1px solid rgba(255,255,255,.12); padding-bottom: 14px; }
      .scrolly-grid, .reserve-grid { grid-template-columns: 1fr; gap: 0; }
      .scrolly-sticky { position: relative; min-height: auto; padding: 100px 0 30px; }
      .scene-visual { width: min(300px, 72vw); }
      .chapters { border-left: 0; }
      .chapter { min-height: 58vh; padding-left: 0; }
      .tier { min-height: 280px; }
      form { grid-template-columns: 1fr; }
      .field.full { grid-column: auto; }
      .footer-top, .footer-bottom { align-items: flex-start; flex-direction: column; }
    }
    @media (max-width: 560px) {
      .nav { width: min(100% - 28px, 1180px); }
      .brand span:last-child { max-width: 130px; font-size: .85rem; line-height: 1.1; }
      .hero-inner, .wrap, .notice-inner { width: min(100% - 28px, 1180px); }
      .hero-inner { padding-top: 150px; }
      h1 { font-size: 3.75rem; }
      .hero-actions .button { width: 100%; }
      main section { padding: 72px 0; }
      .notice-inner { display: block; }
      .notice strong { display: block; margin-bottom: 4px; }
    }
  </style>
</head>
<body>
  <div class="page-progress" id="page-progress" aria-hidden="true"></div>
  <a class="skip" href="#main">Skip to content</a>
  <header class="hero" id="top">
    <nav class="nav" aria-label="Primary navigation">
      <a class="brand" href="#top" aria-label="${escapeHtml(config.title)} home">
        <span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3c3 3.1 4.1 5.7 3.2 7.9-.7 1.7-2 2.6-3.2 2.6s-2.5-.9-3.2-2.6C7.9 8.7 9 6.1 12 3Z"/><path d="M5 14h14M7 14c0 4 2 7 5 7s5-3 5-7"/></svg></span>
        <span>DND Nights</span>
      </a>
      <div class="nav-links">
        <a href="#experience">Experience</a><a href="#tickets">Tickets</a><a href="#faq">FAQ</a>
        <a class="nav-cta" href="#reserve">${isLive ? "Reserve now" : "Join first access"}</a>
      </div>
    </nav>
    <div class="hero-inner">
      <span class="status"><i></i>${isLive ? "Tickets available" : "Event details confirmed"}</span>
      <p class="hero-kicker">DND Nights presents</p>
      <h1>Dance <em>&amp;</em><br>Desi.</h1>
      <p class="hero-copy">A Diwali night in Singapore told through rhythm, colour and connection—built for the dance floor and rooted in the culture.</p>
      <div class="hero-actions">
        <a class="button button-primary" href="#tickets">See ticket tiers <span aria-hidden="true">→</span></a>
        <a class="button button-ghost" href="#experience">Explore the night</a>
      </div>
      <div class="hero-meta" aria-label="Event summary">
        <div class="meta"><small>When</small><strong>${escapeHtml(config.date)}</strong></div>
        <div class="meta"><small>Where</small><strong>${escapeHtml(config.venue)}</strong></div>
        <div class="meta"><small>From</small><strong>S$25 early bird</strong></div>
      </div>
    </div>
  </header>

  <div class="notice" role="note"><div class="notice-inner"><strong>Event details confirmed:</strong><span>DND Nights takes place on 28 November 2026 at Skyfall Rooftop Restrobar. Ticket sales will open through the official Telegram bot after payment setup is complete; entry remains subject to the venue’s approved capacity and event terms.</span></div></div>

  <main id="main">
    <section class="scrolly" id="experience">
      <div class="wrap scrolly-grid">
        <div class="scrolly-sticky" id="scrolly-stage" data-scene="1">
          <p class="eyebrow">Scroll into the night</p>
          <h2>The night moves through <span class="scene-word" id="scene-word">light.</span></h2>
          <div class="scene-visual" aria-hidden="true"><span class="scene-ring"></span><span class="scene-glyph" id="scene-glyph">01</span></div>
        </div>
        <div class="chapters">
          <article class="chapter active" data-scene="1" data-word="light." data-glyph="01"><span class="chapter-num">01 · THE ARRIVAL</span><h3>Gold at the door.</h3><p>You step out of Singapore and into the glow: warm light, festive detail and an entrance that makes dressing up feel worth it.</p></article>
          <article class="chapter" data-scene="2" data-word="rhythm." data-glyph="02"><span class="chapter-num">02 · THE BUILD</span><h3>Desi in every beat.</h3><p>The room starts social, then the tempo climbs—familiar hooks, new mixes and enough range to pull every group toward the floor.</p></article>
          <article class="chapter" data-scene="3" data-word="people." data-glyph="03"><span class="chapter-num">03 · THE CIRCLE</span><h3>Come with friends. Meet more.</h3><p>DND Nights is designed as a shared night, not a faceless crowd: clear hosting, room to connect and a floor that keeps opening up.</p></article>
          <article class="chapter" data-scene="4" data-word="dance." data-glyph="04"><span class="chapter-num">04 · THE RELEASE</span><h3>This is Dance and Desi.</h3><p>The final stretch belongs to the floor. Bright, high-energy and unmistakably ours—one more night for the Diwali feeling.</p></article>
        </div>
      </div>
    </section>

    <section class="tickets" id="tickets"><div class="wrap"><p class="eyebrow">Ticket plan</p><h2>Same celebration.<br>Three ways in.</h2><p class="section-intro">Ticket sales will run through the official DND Nights Telegram bot. Every successful online payment will receive a unique entry QR code.</p>
      <div class="tier-grid">
        <article class="tier featured"><span class="tier-tag">Best value</span><h3>Early bird</h3><div class="price"><span>S$</span><strong>25</strong></div><p>Limited first release for people ready to commit early.</p><button class="button button-primary choose-tier" data-tier="early" type="button">Choose early bird</button></article>
        <article class="tier"><span class="tier-tag">Main release</span><h3>Regular</h3><div class="price"><span>S$</span><strong>30</strong></div><p>Standard online ticket once the early release closes.</p><button class="button button-ghost choose-tier" data-tier="regular" type="button">Choose regular</button></article>
        <article class="tier"><span class="tier-tag">At the door</span><h3>Walk-in</h3><div class="price"><span>S$</span><strong>35</strong></div><p>Door price, available only if the venue has remaining capacity.</p><button class="button button-ghost choose-tier" data-tier="walkin" type="button">Choose walk-in</button></article>
      </div><p class="fine">All prices are in Singapore dollars. Final ticket terms, refund policy and inclusions will be shown before checkout opens.</p></div></section>

    <section class="info"><div class="wrap"><p class="eyebrow">What we are committing to</p><h2>Clear before clever.</h2><div class="info-grid">
      <article class="info-card"><span class="num">01</span><h3>Capacity-led ticketing</h3><p>No overselling. Online inventory and door entry will follow the venue’s approved capacity.</p></article>
      <article class="info-card"><span class="num">02</span><h3>Truthful drink information</h3><p>Non-alcoholic choices will be available. If alcohol is sold, it will be supplied only by the approved licence holder, to guests aged 18+, within approved hours.</p></article>
      <article class="info-card"><span class="num">03</span><h3>Respectful hosting</h3><p>Clear conduct expectations, sober operational staff and a practical route for help or incident reporting.</p></article>
    </div></div></section>

    <section id="reserve"><div class="wrap reserve-grid"><aside class="reserve-aside"><h3>${isLive ? "Start your reservation" : "Get first access"}</h3><ol><li>Choose your preferred ticket tier.</li><li>Leave one contact channel for event updates.</li><li>Continue through the official Telegram bot when secure ticket checkout opens.</li></ol></aside>
      <form id="interest-form" novalidate>
        <div class="field"><label for="name">Name</label><input id="name" name="name" autocomplete="name" maxlength="80" required></div>
        <div class="field"><label for="contact">Email or phone</label><input id="contact" name="contact" autocomplete="email" maxlength="120" required></div>
        <div class="field"><label for="tier">Preferred tier</label><select id="tier" name="tier"><option value="early">Early bird — S$25</option><option value="regular">Regular — S$30</option><option value="walkin">Walk-in — S$35</option></select></div>
        <div class="field"><label for="quantity">Number of tickets</label><select id="quantity" name="quantity"><option>1</option><option>2</option><option>3</option><option>4</option><option>5</option><option>6</option></select></div>
        <div class="honeypot" aria-hidden="true"><label for="website">Website</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>
        <label class="check field full"><input type="checkbox" name="consent" required><span>I agree that the organisers may use these details to contact me about this event. I understand this is not yet a paid ticket.</span></label>
        <div class="form-actions field full"><button class="button" type="submit">${isLive ? "Request reservation" : "Join first access"}</button><span id="form-status" aria-live="polite"></span></div>
        <div class="form-result" id="form-result" aria-live="polite"></div>
      </form>
    </div></section>

    <section id="faq"><div class="wrap"><p class="eyebrow">Useful answers</p><h2>Before you ask.</h2><div class="faq-list">
      <details><summary>Is the date confirmed?</summary><p>Yes. DND Nights takes place on Saturday, 28 November 2026, from 6:30pm to 10:30pm at Skyfall Rooftop Restrobar, 50 Telok Blangah Road, Singapore.</p></details>
      <details><summary>Is this a sober or alcohol-free event?</summary><p>The event is not being advertised as alcohol-free while the beverage plan is undecided. Non-alcoholic choices will be available. Any alcohol service will happen only if the relevant venue and licensing requirements are confirmed.</p></details>
      <details><summary>Does this form charge me?</summary><p>No. It records interest and your preferred tier. A ticket exists only after the organisers issue official terms and your payment is confirmed.</p></details>
      <details><summary>Can I buy at the door?</summary><p>The proposed walk-in price is S$35, but door sales will depend on remaining approved capacity.</p></details>
      <details><summary>How will Telegram be used?</summary><p>The bot will answer common questions, show ticket tiers and route support. It will not ask you to send card numbers or government identification in chat.</p></details>
      <details><summary>Who is organising the event?</summary><p>DND Nights is an independent Singapore event organised by the DND Nights team. For event and ticket assistance, contact the official Telegram bot at @${escapeHtml(config.botUsername || "DND_Nights_Bot")}.</p></details>
    </div></div></section>
  </main>

  <footer><div class="wrap"><div class="footer-top"><p class="footer-title">Dance. Desi. DND Nights.</p><a class="button button-primary" href="#reserve">Join first access</a></div><div class="footer-bottom"><span>© 2026 DND Nights · Singapore</span><span>${escapeHtml(config.support)}</span></div></div></footer>

  <script>
    window.__EVENT__ = ${publicConfig};
    const form = document.querySelector('#interest-form');
    const tier = document.querySelector('#tier');
    const status = document.querySelector('#form-status');
    const result = document.querySelector('#form-result');
    const progress = document.querySelector('#page-progress');
    const stage = document.querySelector('#scrolly-stage');
    const sceneWord = document.querySelector('#scene-word');
    const sceneGlyph = document.querySelector('#scene-glyph');
    const chapters = Array.from(document.querySelectorAll('.chapter'));
    function updateProgress() {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      progress.style.width = (max > 0 ? (window.scrollY / max) * 100 : 0) + '%';
    }
    window.addEventListener('scroll', updateProgress, { passive: true });
    updateProgress();
    if ('IntersectionObserver' in window) {
      const observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          chapters.forEach(function (item) { item.classList.toggle('active', item === entry.target); });
          stage.dataset.scene = entry.target.dataset.scene;
          sceneWord.textContent = entry.target.dataset.word;
          sceneGlyph.textContent = entry.target.dataset.glyph;
        });
      }, { rootMargin: '-32% 0px -48% 0px', threshold: 0 });
      chapters.forEach(function (chapter) { observer.observe(chapter); });
    }
    document.querySelectorAll('.choose-tier').forEach(function (button) {
      button.addEventListener('click', function () { tier.value = button.dataset.tier; document.querySelector('#reserve').scrollIntoView({ behavior: 'smooth' }); setTimeout(function () { document.querySelector('#name').focus(); }, 500); });
    });
    function telegramLink(reference, selectedTier, quantity) {
      const username = window.__EVENT__.botUsername;
      if (!username) return '';
      const payload = ['r', selectedTier, quantity, reference.slice(-8)].join('_');
      return 'https://t.me/' + encodeURIComponent(username) + '?start=' + encodeURIComponent(payload);
    }
    form.addEventListener('submit', async function (event) {
      event.preventDefault(); result.className = 'form-result'; if (!form.reportValidity()) return;
      const button = form.querySelector('button[type="submit"]'); button.disabled = true; status.textContent = 'Sending…';
      const payload = Object.fromEntries(new FormData(form).entries()); payload.quantity = Number(payload.quantity);
      try {
        const response = await fetch('/api/reserve', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
        const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Unable to send request');
        localStorage.setItem('dnd-nights-interest', JSON.stringify({ reference: data.reference, tier: payload.tier, quantity: payload.quantity }));
        const link = telegramLink(data.reference, payload.tier, payload.quantity);
        result.innerHTML = '<strong>' + (data.notified ? 'Request sent.' : 'Draft recorded on this device.') + '</strong><span>Your reference is ' + data.reference + '. This is not a paid ticket yet.</span>' + (link ? '<br><a class="button" href="' + link + '" target="_blank" rel="noopener">Continue in Telegram</a>' : '');
        result.className = 'form-result show'; status.textContent = ''; if (data.notified) form.reset();
      } catch (error) { status.textContent = error.message; } finally { button.disabled = false; }
    });
  </script>
</body>
</html>`;
}

async function telegramApi(env, method, body) {
  if (!env.TELEGRAM_BOT_TOKEN) throw new Error("Telegram bot token is not configured");
  const response = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.description || "Telegram API request failed");
  return data.result;
}

const toBase64Url = (bytes) => {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
};

const toHex = (bytes) => Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");

async function hmacSha256(secret, payload) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(payload)));
}

function safeEqual(left, right) {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  return difference === 0;
}

function singaporeDate(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(date)
    .filter((part) => part.type !== "literal")
    .reduce((result, part) => ({ ...result, [part.type]: part.value }), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function currentTicket(env, date = new Date()) {
  const today = singaporeDate(date);
  const earlyBirdCutoff = env.EARLY_BIRD_CUTOFF || "2026-11-14";
  const eventDate = env.EVENT_DATE || "2026-11-28";
  if (today <= earlyBirdCutoff) return { price: 25, code: "early", label: "Early bird" };
  if (today < eventDate) return { price: 30, code: "regular", label: "Regular" };
  if (today === eventDate) return { price: 35, code: "walkin", label: "Walk-in" };
  return null;
}

function stripePaymentMethods(env) {
  const requested = String(env.STRIPE_PAYMENT_METHODS || "paynow,card")
    .split(",")
    .map((method) => method.trim().toLowerCase())
    .filter((method) => /^[a-z0-9_]+$/.test(method));
  return [...new Set(requested)].slice(0, 6);
}

async function createStripeCheckoutSession(message, ticket, env, origin) {
  if (!env.STRIPE_SECRET_KEY) throw new Error("Stripe is not configured");
  const orderId = `DND-${crypto.randomUUID()}`;
  const params = new URLSearchParams({
    mode: "payment",
    success_url: `${origin}/stripe/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${origin}/stripe/cancelled`,
    client_reference_id: orderId,
    "line_items[0][price_data][currency]": "sgd",
    "line_items[0][price_data][product_data][name]": `DND Nights — ${ticket.label} entry ticket`,
    "line_items[0][price_data][unit_amount]": String(ticket.price * 100),
    "line_items[0][quantity]": "1",
    "metadata[kind]": "dnd_ticket",
    "metadata[order_id]": orderId,
    "metadata[telegram_user_id]": String(message.from.id),
    "metadata[telegram_chat_id]": String(message.chat.id),
    "metadata[ticket_price]": String(ticket.price),
    "metadata[ticket_tier]": ticket.code,
    expires_at: String(Math.floor(Date.now() / 1000) + 30 * 60),
  });
  stripePaymentMethods(env).forEach((method, index) => params.set(`payment_method_types[${index}]`, method));
  const response = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "content-type": "application/x-www-form-urlencoded",
      "idempotency-key": orderId,
    },
    body: params.toString(),
  });
  const result = await response.json();
  if (!response.ok || !result?.id || !result?.url) throw new Error(result?.error?.message || "Stripe Checkout could not be created");
  return result;
}

function botCopy(command, config) {
  const copies = {
    event: `✨ *Event status*\n\n${config.date}\n${config.venue}\n\nThe final programme, capacity and entry terms will be published before the event.`,
    drinks: `🥤 *Drinks policy*\n\nNon-alcoholic options will be available. If alcohol is sold, it will be supplied only by the approved licence holder, to guests aged 18+, during approved hours.`,
    help: `Use /start to buy one entry ticket, /restart to begin again, /event for event details, /drinks for the drinks policy or /support for an organiser. Payment is handled by Stripe; never send bank passwords, card numbers or identity documents in chat.`,
    support: `👋 *Organiser support*\n\n${config.support}\n\nPlease include your DND ticket reference. Never send bank passwords, card numbers or identity documents.`,
  };
  return copies[command] || copies.help;
}

async function sendTicketOffer(message, env, origin) {
  const ticket = currentTicket(env);
  if (!ticket) {
    await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: "DND Nights ticket sales are closed. Use /support if you need help with an existing ticket." });
    return;
  }
  if (!env.STRIPE_SECRET_KEY || !env.STRIPE_WEBHOOK_SECRET || !env.BUCKET) {
    await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: "Ticket checkout is being configured. Please try /start again shortly." });
    return;
  }
  const checkout = await createStripeCheckoutSession(message, ticket, env, origin);
  await telegramApi(env, "sendMessage", {
    chat_id: message.chat.id,
    text: `🪔 *Welcome to DND Nights — Dance and Desi*\n\nYour current entry ticket price is *S$${ticket.price}*.\n\nTap below to pay securely through Stripe using PayNow or card. After Stripe confirms payment, this bot will automatically send your unique entry QR code.`,
    parse_mode: "Markdown",
    protect_content: true,
    reply_markup: {
      inline_keyboard: [
        [{ text: `Pay S$${ticket.price} with Stripe`, url: checkout.url }],
        [{ text: "Start again", callback_data: "restart" }],
        [{ text: "Event details", callback_data: "event" }, { text: "Drinks policy", callback_data: "drinks" }],
      ],
    },
  });
}

async function createTicketToken(stripeSessionId, env) {
  if (!env.TICKET_SIGNING_SECRET) throw new Error("Ticket signing secret is not configured");
  const digest = await hmacSha256(env.TICKET_SIGNING_SECRET, `dnd-ticket:${stripeSessionId}`);
  return toBase64Url(digest.slice(0, 18));
}

const ticketKey = (token) => `tickets/${token}.json`;

async function readTicket(token, env) {
  if (!env.BUCKET || !/^[A-Za-z0-9_-]{20,32}$/.test(String(token || ""))) return null;
  const stored = await env.BUCKET.get(ticketKey(token));
  if (!stored) return null;
  try { return JSON.parse(await stored.text()); } catch { return null; }
}

async function writeTicket(ticket, env) {
  if (!env.BUCKET) throw new Error("Ticket storage is not configured");
  await env.BUCKET.put(ticketKey(ticket.token), JSON.stringify(ticket), { httpMetadata: { contentType: "application/json" } });
}

function ticketReference(token) {
  return `DND-${String(token).replace(/[-_]/g, "").slice(0, 10).toUpperCase()}`;
}

function telegramAdminId(env) {
  return String(env.TELEGRAM_ADMIN_USER_ID || env.TELEGRAM_ADMIN_CHAT_ID || "");
}

async function issueEntryTicket(session, env, origin) {
  const metadata = session?.metadata || {};
  const price = Number(metadata.ticket_price);
  const amountTotal = Number(session?.amount_total);
  if (metadata.kind !== "dnd_ticket" || session?.payment_status !== "paid") return { issued: false, reason: "not-paid" };
  if (![25, 30, 35].includes(price) || amountTotal !== price * 100 || String(session.currency).toLowerCase() !== "sgd") {
    throw new Error("Paid Checkout Session does not match a valid DND ticket amount");
  }
  if (!/^[-0-9]{1,32}$/.test(String(metadata.telegram_user_id || "")) || !/^[-0-9]{1,32}$/.test(String(metadata.telegram_chat_id || ""))) {
    throw new Error("Paid Checkout Session is missing Telegram ownership metadata");
  }

  const token = await createTicketToken(session.id, env);
  let ticket = await readTicket(token, env);
  if (!ticket) {
    ticket = {
      version: 1,
      token,
      reference: ticketReference(token),
      stripeSessionId: session.id,
      paymentIntentId: session.payment_intent || null,
      orderId: metadata.order_id || session.client_reference_id || null,
      userId: String(metadata.telegram_user_id),
      chatId: String(metadata.telegram_chat_id),
      tier: metadata.ticket_tier || "entry",
      price,
      currency: "sgd",
      status: "valid",
      createdAt: new Date().toISOString(),
      deliveredAt: null,
      usedAt: null,
      usedBy: null,
    };
    await writeTicket(ticket, env);
  }
  if (ticket.deliveredAt) return { issued: true, duplicate: true, ticket };

  const qrUrl = `${origin}/ticket/qr/${token}.png`;
  await telegramApi(env, "sendPhoto", {
    chat_id: ticket.chatId,
    photo: qrUrl,
    caption: `✅ *Payment confirmed — entry ticket issued*\n\nTicket: *${ticket.reference}*\nPaid: *S$${ticket.price}*\n\nThis QR code is unique and admits one person once. Keep it private and show it at the door.`,
    parse_mode: "Markdown",
    protect_content: true,
  });
  ticket.deliveredAt = new Date().toISOString();
  await writeTicket(ticket, env);
  return { issued: true, duplicate: false, ticket };
}

async function verifyStripeWebhook(rawBody, signatureHeader, secret) {
  if (!signatureHeader || !secret) return false;
  const fields = signatureHeader.split(",").map((part) => part.trim().split("=", 2));
  const timestamp = Number(fields.find(([key]) => key === "t")?.[1]);
  const signatures = fields.filter(([key]) => key === "v1").map(([, value]) => value);
  if (!Number.isFinite(timestamp) || Math.abs(Date.now() / 1000 - timestamp) > 300 || !signatures.length) return false;
  const expected = toHex(await hmacSha256(secret, `${timestamp}.${rawBody}`));
  return signatures.some((signature) => safeEqual(expected, signature));
}

async function handleStripeWebhook(request, env) {
  const rawBody = await request.text();
  const verified = await verifyStripeWebhook(rawBody, request.headers.get("stripe-signature"), env.STRIPE_WEBHOOK_SECRET);
  if (!verified) return json({ ok: false, error: "Invalid Stripe signature" }, 400);
  let event;
  try { event = JSON.parse(rawBody); } catch { return json({ ok: false, error: "Invalid JSON" }, 400); }
  if (!["checkout.session.completed", "checkout.session.async_payment_succeeded"].includes(event.type)) return json({ ok: true, ignored: true });
  const result = await issueEntryTicket(event.data?.object, env, new URL(request.url).origin);
  return json({ ok: true, issued: result.issued, duplicate: Boolean(result.duplicate) });
}

function u32(value) {
  return new Uint8Array([(value >>> 24) & 255, (value >>> 16) & 255, (value >>> 8) & 255, value & 255]);
}

function joinBytes(...parts) {
  const output = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) { output.set(part, offset); offset += part.length; }
  return output;
}

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data = new Uint8Array()) {
  const typeBytes = new TextEncoder().encode(type);
  const body = joinBytes(typeBytes, data);
  return joinBytes(u32(data.length), body, u32(crc32(body)));
}

async function qrPng(text) {
  const qr = QRCode.create(text, { errorCorrectionLevel: "M" });
  const border = 4;
  const scale = 8;
  const modules = qr.modules.size;
  const width = (modules + border * 2) * scale;
  const raw = new Uint8Array((width + 1) * width);
  for (let y = 0; y < width; y += 1) {
    const rowOffset = y * (width + 1);
    raw[rowOffset] = 0;
    for (let x = 0; x < width; x += 1) {
      const moduleX = Math.floor(x / scale) - border;
      const moduleY = Math.floor(y / scale) - border;
      const dark = moduleX >= 0 && moduleY >= 0 && moduleX < modules && moduleY < modules && qr.modules.get(moduleY, moduleX);
      raw[rowOffset + x + 1] = dark ? 0 : 255;
    }
  }
  const compressor = new CompressionStream("deflate");
  const writer = compressor.writable.getWriter();
  await writer.write(raw);
  await writer.close();
  const compressed = new Uint8Array(await new Response(compressor.readable).arrayBuffer());
  const ihdr = joinBytes(u32(width), u32(width), new Uint8Array([8, 0, 0, 0, 0]));
  return joinBytes(new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]), pngChunk("IHDR", ihdr), pngChunk("IDAT", compressed), pngChunk("IEND"));
}

async function serveTicketQr(token, env) {
  const ticket = await readTicket(token, env);
  if (!ticket) return new Response("Ticket not found.", { status: 404, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
  const username = String(env.TELEGRAM_BOT_USERNAME || "").replace(/^@/, "");
  if (!username) return new Response("Ticket QR is not configured.", { status: 503 });
  const image = await qrPng(`https://t.me/${username}?start=check_${token}`);
  return new Response(image, {
    headers: {
      "content-type": "image/png",
      "content-disposition": `inline; filename=${ticket.reference}.png`,
      "cache-control": "private, no-store, max-age=0",
      "x-content-type-options": "nosniff",
    },
  });
}

async function handleTicketCheckIn(message, token, env) {
  const ticket = await readTicket(token, env);
  if (!ticket) {
    await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: "❌ Ticket not found. Do not admit this guest." });
    return;
  }
  const isAdmin = telegramAdminId(env) && String(message.from.id) === telegramAdminId(env);
  if (!isAdmin) {
    const owner = String(message.from.id) === ticket.userId;
    await telegramApi(env, "sendMessage", {
      chat_id: message.chat.id,
      text: owner
        ? `${ticket.status === "valid" ? "✅" : "⚠️"} Ticket ${ticket.reference} is ${ticket.status === "valid" ? "valid and ready for entry" : `already used at ${ticket.usedAt}`}. Only the organiser can check it in.`
        : "This ticket can only be checked in by the organiser.",
    });
    return;
  }
  if (ticket.status !== "valid") {
    await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: `⛔ *DO NOT ADMIT*\n\nTicket *${ticket.reference}* was already used at ${ticket.usedAt}.`, parse_mode: "Markdown" });
    return;
  }
  ticket.status = "used";
  ticket.usedAt = new Date().toISOString();
  ticket.usedBy = String(message.from.id);
  await writeTicket(ticket, env);
  await telegramApi(env, "sendMessage", {
    chat_id: message.chat.id,
    text: `✅ *ADMIT GUEST*\n\nTicket: *${ticket.reference}*\nTier: ${ticket.tier}\nPaid: S$${ticket.price}\n\nThis ticket is now marked as used.`,
    parse_mode: "Markdown",
  });
}

async function handleTelegram(request, env) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_WEBHOOK_SECRET || !env.TICKET_SIGNING_SECRET) return json({ ok: false, error: "Telegram is not configured" }, 503);
  if (request.headers.get("x-telegram-bot-api-secret-token") !== env.TELEGRAM_WEBHOOK_SECRET) return json({ ok: false }, 401);
  const update = await request.json();
  const config = eventConfig(env);
  const origin = new URL(request.url).origin;
  if (update.callback_query) {
    const callback = update.callback_query;
    if (callback.data === "restart") {
      await telegramApi(env, "answerCallbackQuery", { callback_query_id: callback.id, text: "Starting again…" });
      await sendTicketOffer({ from: callback.from, chat: callback.message.chat }, env, origin);
      return json({ ok: true });
    }
    const command = ["event", "drinks"].includes(callback.data) ? callback.data : "help";
    await telegramApi(env, "answerCallbackQuery", { callback_query_id: callback.id });
    await telegramApi(env, "sendMessage", { chat_id: callback.message.chat.id, text: botCopy(command, config), parse_mode: "Markdown" });
    return json({ ok: true });
  }
  const message = update.message;
  if (!message?.chat?.id) return json({ ok: true });
  const raw = compact(message.text, 200);
  const [first, payload = ""] = raw.split(/\s+/, 2);
  const command = first?.startsWith("/") ? first.toLowerCase().split("@")[0].slice(1) : "help";
  const checkToken = command === "start" ? payload.match(/^check_([A-Za-z0-9_-]{20,32})$/)?.[1] : null;
  if (checkToken) { await handleTicketCheckIn(message, checkToken, env); return json({ ok: true }); }
  if (["start", "restart", "tickets", "prices"].includes(command)) { await sendTicketOffer(message, env, origin); return json({ ok: true }); }
  if (command === "whoami") { await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: `Your Telegram user ID: ${message.from.id}\nThis chat ID: ${message.chat.id}` }); return json({ ok: true }); }
  const supported = ["event", "venue", "drinks", "help", "support"];
  const normalized = supported.includes(command) ? command : "help";
  await telegramApi(env, "sendMessage", { chat_id: message.chat.id, text: botCopy(normalized === "venue" ? "event" : normalized, config), parse_mode: "Markdown" });
  return json({ ok: true });
}

async function handleReservation(request, env) {
  const contentLength = Number(request.headers.get("content-length") || 0); if (contentLength > 8000) return json({ error: "Request is too large" }, 413);
  let input; try { input = await request.json(); } catch { return json({ error: "Invalid request" }, 400); }
  if (input.website) return json({ error: "Unable to accept request" }, 400);
  const name = compact(input.name, 80); const contact = compact(input.contact, 120); const tierKey = Object.hasOwn(TICKETS, input.tier) ? input.tier : ""; const quantity = Math.min(6, Math.max(1, Number(input.quantity) || 1));
  if (!name || !contact || !tierKey || !input.consent) return json({ error: "Please complete every required field" }, 400);
  const reference = `DND26-${crypto.randomUUID().slice(0, 8).toUpperCase()}`; let notified = false;
  if (env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_ADMIN_CHAT_ID) {
    const ticket = TICKETS[tierKey];
    try { await telegramApi(env, "sendMessage", { chat_id: env.TELEGRAM_ADMIN_CHAT_ID, text: `🪔 New DND Nights interest\n\nReference: ${reference}\nName: ${name}\nContact: ${contact}\nTier: ${ticket.label} (S$${ticket.price})\nQuantity: ${quantity}\n\nThis is an interest request, not a paid ticket.` }); notified = true; }
    catch (error) { console.error("Reservation notification failed", error.message); }
  }
  return json({ ok: true, reference, notified });
}

function stripeResultPage(success, env) {
  const username = escapeHtml(String(env.TELEGRAM_BOT_USERNAME || "").replace(/^@/, ""));
  const title = success ? "Payment received" : "Checkout cancelled";
  const copy = success
    ? "Stripe is confirming your payment. Your unique entry QR will be delivered automatically in Telegram—there is no screenshot to upload."
    : "No ticket was issued and no completed payment was recorded. Return to Telegram to start again.";
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#061425"><title>${title} · DND Nights</title><style>
  *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;color:#fff;background:radial-gradient(circle at 50% 15%,#174a7d 0,transparent 32%),#061425;font:16px/1.55 Inter,system-ui,sans-serif}.card{width:min(560px,100%);padding:42px;border:1px solid rgba(247,207,104,.35);border-radius:28px;background:#0a2342;text-align:center;box-shadow:0 30px 90px rgba(0,0,0,.4)}.eyebrow{color:#f7cf68;font-size:.75rem;font-weight:800;letter-spacing:.16em;text-transform:uppercase}h1{margin:12px 0;font:400 clamp(2.5rem,8vw,4rem) Georgia,serif}p{color:rgba(255,255,255,.72)}a{display:inline-block;margin-top:18px;padding:12px 20px;border-radius:999px;color:#061425;background:#f7cf68;text-decoration:none;font-weight:800}
  </style></head><body><main class="card"><div class="eyebrow">DND Nights · Dance and Desi</div><h1>${title}</h1><p>${copy}</p>${username ? `<a href="https://t.me/${username}">Return to Telegram</a>` : ""}</main></body></html>`;
}

async function setupTelegram(request, env) {
  if (!env.TELEGRAM_SETUP_KEY || !env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_WEBHOOK_SECRET) return json({ error: "Telegram setup variables are incomplete" }, 503);
  const auth = request.headers.get("authorization");
  const setupKey = request.headers.get("x-dnd-setup-key");
  if (auth !== `Bearer ${env.TELEGRAM_SETUP_KEY}` && setupKey !== env.TELEGRAM_SETUP_KEY) return json({ error: "Unauthorized" }, 401);
  const origin = new URL(request.url).origin;
  await telegramApi(env, "setWebhook", { url: `${origin}/telegram/webhook`, secret_token: env.TELEGRAM_WEBHOOK_SECRET, allowed_updates: ["message", "callback_query"], drop_pending_updates: false });
  await telegramApi(env, "setMyCommands", { commands: [{ command: "start", description: "Buy a DND Nights ticket" }, { command: "restart", description: "Restart and show the introduction" }, { command: "tickets", description: "Open the current ticket offer" }, { command: "event", description: "View event status" }, { command: "drinks", description: "Read the drinks policy" }, { command: "support", description: "Contact an organiser" }, { command: "whoami", description: "Show your Telegram IDs" }] });
  return json({ ok: true, webhook: `${origin}/telegram/webhook` });
}

export default {
  async fetch(request, env, ctx) {
    void ctx; const url = new URL(request.url);
    const headers = { "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=300", "content-security-policy": "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'", "referrer-policy": "strict-origin-when-cross-origin", "x-content-type-options": "nosniff", "x-frame-options": "DENY" };
    if (request.method === "GET" && url.pathname === "/") return new Response(renderPage(eventConfig(env)), { headers });
    const ticketQrMatch = url.pathname.match(/^\/ticket\/qr\/([A-Za-z0-9_-]{20,32})\.png$/);
    if (request.method === "GET" && ticketQrMatch) return serveTicketQr(ticketQrMatch[1], env);
    if (request.method === "GET" && url.pathname === "/stripe/success") return new Response(stripeResultPage(true, env), { headers: { ...headers, "cache-control": "no-store" } });
    if (request.method === "GET" && url.pathname === "/stripe/cancelled") return new Response(stripeResultPage(false, env), { headers: { ...headers, "cache-control": "no-store" } });
    if (request.method === "GET" && url.pathname === "/health") {
      const ticket = currentTicket(env);
      return json({ ok: true, telegramConfigured: Boolean(env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_WEBHOOK_SECRET), stripeConfigured: Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_WEBHOOK_SECRET), ticketStorageConfigured: Boolean(env.BUCKET && env.TICKET_SIGNING_SECRET), paymentMethods: stripePaymentMethods(env), earlyBirdCutoff: env.EARLY_BIRD_CUTOFF || "2026-11-14", eventDate: env.EVENT_DATE || "2026-11-28", currentPrice: ticket?.price || null, salesOpen: Boolean(ticket) });
    }
    if (request.method === "POST" && url.pathname === "/api/reserve") return handleReservation(request, env);
    if (request.method === "POST" && url.pathname === "/stripe/webhook") return handleStripeWebhook(request, env);
    if (request.method === "POST" && url.pathname === "/telegram/webhook") return handleTelegram(request, env);
    if (request.method === "POST" && url.pathname === "/telegram/setup") return setupTelegram(request, env);
    return new Response("Not found", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
