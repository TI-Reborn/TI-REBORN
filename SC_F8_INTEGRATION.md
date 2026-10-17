# SC original GUI + explicit F8/v1

The original DLL rejects all BD receive subcodes, proved in `SC_NATIVE_RECEIVER.md`.
`deploy/client_sc_auction.py` adds an explicitly new receiver, based only on the
exact phase3 DLL SHA256 `2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f`,
7753216 bytes. `patch(bytes)` returns a candidate, never installs/publishes.
Idempotence restores the exact prior release hash. `patch_plan` permits only the
chained PacketHandler call, three PE size fields and 8192 appended bytes.
All other four phase3 hooks, old F6/F7 code and every stock BD builder remain.

## Backend integration

`PrivateMarketSession.handle_sc(packet, allow_mutation=city_mutations_allowed)`
returns **a tuple of outbound packet bytes**. Root must enqueue those packets,
not send them as chat. Construct the adapter with the authenticated selected
character save owner and shops/auction stores using the same SQLite database.
The packet decoder rejects BD05, including administrator deletion mode3.
`clear_sc()` resets recipient quotes and returns the F8 clear packet; call/send
it at authenticated slot selection and reconnect before new full snapshots.
Root's ordinary clock must call `auction.tick()` even without online viewers;
`refresh()` supplies two-second catalogue pushes while the recipient opened SC.
Combat/results must pass `allow_mutation=False`. Existing inventories and balances
are refreshed by the returned balance/warehouse packets after payments.

Use `tio.protocol.sc_auction_view`:

* `encode_clear()` at authenticated slot selection/reconnect, with adapter quotes reset.
* `lot_view(lot, bidder_name=public_character_name, personal=is_owner,
  notes=description, now=authoritative_unix_time)` then `encode_catalogue(views)`.
  Send a full bounded snapshot after BD01, changed lots/bids/timer closures and
  successful claims. Include active and own unclaimed won lots first; fill the
  rest with bounded recent closed history. Maximum200 records/65533 payload bytes.
  Owner/database identity strings must never become public names. Resolve names
  from the authoritative character store; empty bidder uses empty name.
* `history_view(event, public_name=name, currency=0_or_1)` returns None for
  ledger-only events with no original display action. Page the remaining native
  rows; `encode_history(lot, views, page=1, pages=1, remaining_ms=...)` after BD03.
* `encode_bot(lot, fee, from_price, to_price, remaining_bids)` after BD14/mode0.
  Only that recipient's bot is shown. Apply/delete update wallet and catalogue;
  the original callbacks close the form, so acknowledgements do not reopen it.
* `encode_claim(lot, final_price, currency, actual_expires_at, can_pay=...)` after
  BD07 **for a won lot owned by this character**. Original claim form includes
  an expiry promise. The backend must enforce the supplied actual expiry; agreed
  seven-day period is explicit server policy, not a numerical manual rule.
  Insufficient money sets can_pay=False; both quote and final claim revalidate.
* Currency0=credits,1=gold. Prices/counts remain authoritative backend values.

The backend now persists `expires_at`, using seven days from its real closing
event. Old unclaimed wins migrate from the durable `closed` event (recorded ends
only if the old event is missing). Tick expires the win once and withdraws the
system-owned prize. No final-price debit/refund occurs on expiry; spent bid fees
remain spent and unused bot escrow was already refunded at close. Receipt and
mail delivery are in the same claim transaction. Deferring clears the recipient's
claim quote; the winner must reopen the actual claim form before paying later.

Config limits simultaneous active+unclaimed won lots to200; replenishment pauses
at that bound. Every live lot is included in recipient snapshots, with own wins
first, then bounded archived rows. Existing data above the configured cap fails
explicitly instead of silently omitting a claim. Prices and bot thresholds are
bounded by the original signed Delphi Integer; duration/extension milliseconds
must fit that same limit. These are explicit server compatibility policies.

`lot_view` uses exact original tab keys “Фановый за кредиты”, “Фановый за золото”,
“Дорогой за кредиты”, “Дорогой за золото”. Default explicit catalogue policy puts
enhanced equipment in expensive and other prizes in fun. `resource_id=0`, weight0,
discount0 and no below-reserve deficit are explicit unsupported-value defaults,
not recovered tariffs. It uses the real serialized prize template/count/enhance.

The runtime RTTI names base_duration/duration cannot be treated as raw duration
seconds: original renderer896b42 uses +0x28 as remaining milliseconds when
ac490d=False; +0x2c as local tick deadline when True. The receiver converts the
remaining supplied by the server to `*ac5fe4+remaining` for each record and the
history window. Original countdown execution proves it decreases over time.
Calendar dates are Delphi days since1899-12-30 projected from UTC timestamps.

## Original outgoing callbacks: corrections required

* Ordinary bid click899e3b →89d5f4 sends **BD06 lot:u32**. Tooltip89739c is
  m739("Сделать ставку") at the same rectangle x19d-54.
* Bot-open click899e9b →89dd2c sends **BD14 mode0 lot:u32**. Tooltip8974ad is
  m796("Автоставка") at the same rectangle x19d-7e. It does not cancel a bot.
* BD07 is the native own-won-lot claim form request.
* Callback899a94 →89d670 BD05/mode3 is **administrative lot deletion**, confirmed
  by m727("Вы уверены, что хотите удалить лот...") and admin/paused GUI guards.
  It must be rejected by ordinary city routing.
* Bot setup89430c →89dd2c sends **BD14 mode1, lot:u32, FROM:u32, N:u32, TO:u32**.
  Normalize this order into the store's `(from_price,to_price,count)` arguments.
* Original delete894410 sends **BD14 mode2, lot:u32**, with no trailing values.
  This releases unused holds.
* Original claim891444/defer891458 →89d730 send BD09 lot:u32, buy:u8(1/0).
* History previous/next891830/891848 →89d62c sends BD03 lot:u32,page:u16.

No client nonce is added to these old BD requests. Adapter-held revisions/quotes
and operation tokens reject replay/stale actions; the store's receipts remain the
once-only payment/delivery authority. A repeated identical bid against an unchanged
recipient quote is one operation, even after a rival bids. Passive pushes do not
advance that quote: reopen/refresh the native tab (BD01) before a new bid. Opening
the bot/claim form gives a fresh operation token. This is a usability limit of
keeping stock outgoing requests; login/character change clears every quote.

## Verification and limits

`tools/verify_sc_view_native.py` executes exported PacketHandler9f5548, the new
validator/writer, original605df4 string reader, original89a514 tab filters, original
countdown arithmetic and original GUI hit-tests/native bid/bot/delete/claim/defer callbacks at base400000
and relocated500000. `evidence/sc_view_native.json` lists all isolated Delphi
heap/string primitives, GUI collection/painting and transport handles. Native
numeric writers are unchanged. `tests/test_sc_auction_view.py` checks codec bounds,
all truncations, malformed snapshots preserve state, strict base/idempotence and
delegation to existing F7/BD gates. This is native execution proof; it does not
claim rendered GUI, installed client or hosted acceptance.
