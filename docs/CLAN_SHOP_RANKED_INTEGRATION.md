# Phase 7 shop and ranked integration

This package changes only `tio/shop.py`, `tio/clan_benefits.py`, `tio/ranked.py`
and corresponding tests. It supersedes the pending Gold-item shop, validated
influence multiplier and legacy-week guard notes in
[CLAN_PHASE7_INTEGRATION.md](CLAN_PHASE7_INTEGRATION.md). No runtime, portal,
snapshot, battle reward or hosting files were changed.

## Native item shop: already connected

Existing callers still work without new arguments:

```python
store.purchase(account, native_shop_request)
store.purchase_premium(account, native_78_packet)
store.sell(account, native_sale_request, quote=False)
store.sell(account, native_sale_request, quote=True)
```

The premium native packet still validates its category, current catalog revision,
offer, count, owned recipient, actual balance and capacity. Only after the real
discounted Gold debit and inventory write, inside the same transaction, it calls:

```python
contribution = clan_benefits.premium_gold_spent(
    db, account, operation_id, actual_discounted_gold_debit)
achievements.influence_received(
    db, account, 'gold:'+operation_id, contribution['amount'])
achievements.event(db, account, operation_id, add={'premium_purchase':1})
```

`operation_id` is the server-owned `shop:<SQLite receipt id>`; the actual
achievement identity is `influence:gold:shop:<id>`. Each accepted order counts
once, regardless of quantity. Ordinary purchases retain `shop_purchase` and do
not count as premium purchases. Subscription, currency conversion, bonds and
SC operations never call this Gold-item hook. This patch neither reclassifies
nor removes old earned achievements.

`shop_receipts` is an immutable completed operation ledger. Allocation, personal
wallet/inventory changes, item sequence, clan contribution, achievement progress
and the final receipt all share one transaction. Any serializer, capacity,
inventory, contribution, achievement or enclosing gameplay-unit failure rolls
everything back. There is no independent commit inside a shared gameplay unit.

Root must **not** wrap these shop methods with another Gold contribution or
premium/influence achievement call: that would duplicate the completed work.
The existing native handlers can call the same methods and receive the same
inventory/AssetCount packets. `PurchaseResult` adds only a server-side optional
`operation_id` field; it adds no original wire field or opcode.

## Sale net and authoritative city

Ordinary shop sales calculate the existing gross from the real admissible item
and catalog/material price. The store reads `character_locations.town_id` for
the save owner in the same transaction, then calls:

```python
tax = clan_benefits.sales_tax(db, account, operation_id, actual_town, gross)
seller_credit = tax['net']
```

It credits `net` once and returns `charged_credits=-net`. The controlling clan
safe receives the included tax once. Item removal, clan safe, seller wallet and
receipts roll back together. Wallet overflow applies to net, so a gross exceeding
available wallet space may still succeed if the actual taxed credit fits.
The existing tax exemption for premium sales remains in the backend helper;
the native ordinary sale method uses `premium=False`. Unsupported premium-only
resale pricing, worn/equipped items and nontransferable boosters keep their
existing rejection policy.

Quotes call the new read-only `clan_benefits.sales_quote(db, town, gross,
premium=False)` and return its `net`. It shares the validated claim/history and
rounding calculation with actual settlement, but creates no benefit receipt,
does not change safe/wallet/inventory and cannot earn an achievement. A claim or
price can change between a preview and the subsequent accepted sale.

When `character_locations` or its account row is absent, legacy saves keep the
old untaxed behavior using neutral town 0. Persisted town `-1` rejects a sale
outside a city. Optional `town=` is server-owned; if a persisted town exists it
must match. It must never come from an untrusted client claim. Existing hosted
accounts with saved locations obtain tax through the current native route
without changing `loopback_exchange.py`.

## Explicit server replay keys

New backward-compatible keyword arguments are:

```python
store.purchase(account, request, *, identity=None)
store.purchase_premium(account, packet, *, identity=None)
store.sell(account, request, *, quote=False, identity=None, town=None)
```

Original native shop packets have no transaction nonce. Two identical native
purchase calls therefore remain two distinct accepted orders with separate real
debits and separate SQLite IDs; quantity cannot be used as a replay key. Root
may pass `identity=<stable accepted server action key>` when its transport/journal
has one. Never hash just the request fields or create a new key on each retry.

Explicit identity is scoped to the save owner and rejects a retry with a changed
operation, native request or explicit town argument. An unchanged retry returns
the original charge/operation ID with **current** private inventory/wallet
snapshots after intervening actions. It neither rewinds the save nor applies the
original charge again. If the recipient is gone, retry rejects without mutation.
Without an explicit key a fully consumed sale cannot repeat, while partial
stack sales get distinct accepted receipt IDs. Quotes create no operation.

## Ranked results: already connected

Continue calling `ranked.settle(db, actual_match_id, accepted_report, now=stamp)`
within the existing match reward transaction. For each actual participant, after
its validated pre-match snapshot is accepted and new state is stored, it calls:

```python
achievements.ranked_result(
    db, account, actual_match_id,
    result=2 if draw else int(side==winner),
    league_before=original_league,
    league_after=accepted_new_league,
    streak=accepted_new_streak,
)
```

The promotion win counts against the original bronze league; league/streak
achievements use accepted post-match values. Loss/draw use streak 0. Every player
on the two real sides gets one `ranked:<match UUID>` event. Replaying an existing
match-wide `ranked_matches` receipt returns before achievements; changed retries
reject. Legacy match receipts do not get reconstructed from the current league.
Any participant's achievement failure rolls back both sides' ratings, progress
and the ranked receipt together. Existing inference, league hysteresis, draw
policy, public placement and match format remain unchanged.

Root must **not** separately call `ranked_result` after this function in
`battle_rewards` or runtime. Other rating backends remain separate integrations.

## Validated factors and closed weeks

`clan_benefits.influence_multiplier` now uses the validated read-only
`achievement_benefits.influence_multiplier` and preserves its surrounding premium
and permanent medal factors. Duplicate earned IDs do not multiply; conflicting
or malformed relevant snapshots reject the enclosing mutation.

`close_week` still waits for unfinished events. It now settles only finalized
receipts whose `benefits_version` is an actual integer 1. Unmarked/boolean/other
versions are excluded from new rewards and weekly score sums, even if old totals
already exist. Finalized events without a receipt reject instead of inventing
an outcome. Existing completed-week receipts still replay unchanged. New marked
finalized events produce capture/prize/medal/weekly benefits once, with atomic
rollback if the week cannot be closed. Root's hourly `decay`/`close_week` scheduling
remains outside this patch.

## Verification and phase ordering

The phase 6 pre7 shop baseline, including its item-mark guard, was copied before
editing to `reports/gameplay-completion/stage6-economy/runtime/tio/shop.py`:
SHA256 `5c241c2fa5c500e8bbfbad3325aa2553aa9f1514281bbbee06bbb7d85b97623b`.
Phase 6 must pin that copy until its release; the current source includes phase 7.

24 new tests pass with the normal unittest runner:

```powershell
$env:PYTHONPATH='C:\TIO-emulator\tests;C:\TIO-emulator'
python -m unittest tests.test_shop_clan_benefits tests.test_ranked_achievements
```

Tests exercise actual native78 decoding/price revision, discounted debit, two
real orders with equal packet fields, concurrent identified retries/restart,
current private snapshots, ordinary/subscription/conversion exclusions, city
net quotes/tax/stack sales, immutable receipts, faults/overflow, marked versus
legacy week receipts, promotion/loss/draw/team outcomes and rating/achievement
rollback. Existing clan benefit fixtures now carry marked actual final receipts
for the weekly policy checks, rather than counting unmarked synthetic totals.

A combined regression run passed 196 tests covering shop/prices/premium, clans/achievements,
ranked shared-server tests, stacking, bank and admission capacity. The old
`gold_request` fixture hardcodes revision 20260925; only its default revision was
aligned in memory to the actual 20261008 catalog for this regression run. Explicit
bad revision tests and all other assertions were unchanged. No existing shop or
premium test source was edited. Results are automated local database/native
packet checks, not hosted deployment or graphical game-client validation.
