# Promoter campaign — launched 30 October 2026

The live SQLite ledger is the authority. `/promoters` shows the current phase,
approved ticket count, awarded drinks and attribution by promoter.

* Early bird is S$25 until 100 tickets have been approved, across all sources.
  The old calendar-based early-bird cutoff is replaced by this approval limit.
* Before that limit, a valid `NAMEFREE` records a free-drink request at the normal
  ticket price. A drink is awarded only if that ticket is among the first 100
  approvals. Booking time and pressing “I have paid” do not reserve a drink.
* After 100 approvals, new bookings use General S$30; `NAMEFREE` closes and
  `NAME10` gives 10% off (S$27 General). These discount codes are accepted but
  are not advertised in the public booking intro or Prices menu.
* Walk-in pricing on 28 November remains S$35 (S$31.50 with an active `NAME10`).
* Existing orders keep their saved payment total. For example, if a five-ticket
  FREE order is approved after 98 approvals, only two of its tickets get drinks.
* All approved quantities, including non-promoter bookings, count toward 100.
  Voiding an order does not reopen the campaign or recycle the first-100 places.
* Old `NAME20` and legacy `DND-...` codes cannot start new bookings. Historical
  orders and attribution remain intact. Promotion offers cannot be combined.

## Codes

| Promoter | Free-drink phase | Later 10% phase |
| --- | --- | --- |
| Adeep | ADEEPFREE | ADEEP10 |
| Nirbhay | NIRBHAYFREE | NIRBHAY10 |
| Ishwar | ISHWARFREE | ISHWAR10 |
| Shalu | SHALUFREE | SHALU10 |
| Austin | AUSTINFREE | AUSTIN10 |
| Ira | AIRAFREE | AIRA10 |
| Jeswant | JESWANTFREE | JESWANT10 |
| Aesha | AESHAFREE | AESHA10 |
| Meera | MEERAFREE | MEERA10 |
| Hrehan | HREHANFREE | HREHAN10 |
| Dhruv | DHRUVFREE | DHRUV10 |
| Niheela | NIHEELAFREE | NIHEELA10 |
| Sachin | SACHINFREE | SACHIN10 |
| Dheena | DHEENAFREE | DHEENA10 |

Codes are exact apart from case and surrounding whitespace. `/addpromoter NAME Full Name`
creates both code variants for a new promoter. `/promodiscounts off` manually
pauses the later 10% codes; `on` enables them subject to the 100-approval gate.

## Drinks and admission

Each awarded drink is stored against one ticket token in `drink_benefits` and
appears in that ticket's image and caption. Resending a ticket does not create
another drink. Payment approval and drink allocation use one SQLite write
transaction so concurrent approvals cannot exceed the cap.

A full bot admin can scan/open the ticket's Telegram QR link, press Start (or use
`/check TOKEN`), and tap **Redeem free drink** only when serving it. Redemption
is recorded once and audited. The drink action does not mark entry; admission
does not redeem the drink. An admitted guest can still redeem an unclaimed
drink. The web door scanner continues to record admission only.

Only full bot admins can use the Telegram drink action; scanner-only staff
permissions are unchanged. A void ticket cannot claim a drink.

## Deployment and verification

The first startup takes a private SQLite backup in
`/var/data/backups/pre-promoter-launch-*.sqlite3` before additive migration.
It preserves orders, tickets, payment evidence, promoter history and staff.
The launch marker makes subsequent starts preserve manual campaign settings.

Run `python -m unittest -v test_campaign.py` from `telegram-bot/live`.
Tests use temporary databases and fake Telegram transports, never live orders
or bank credentials. They cover migration, old orders, pricing, group boundaries,
concurrent approvals, one-time drinks, guest Back navigation, payment QR cents,
public copy, authorization, and scanner admission.
