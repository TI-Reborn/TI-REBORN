# Shared clan and achievement integration contract

`tio/clan_benefits.py` is released backend policy. Every mutation below requires
the caller's existing gameplay SQLite transaction; do not commit helpers
independently. Reuse an authoritative stable operation identity and account save
owner. Receipts reject changed retries and preserve atomic rollback. Shared
runtime integration and native transport are separate from this backend module.

## Authoritative settlement hooks

| Existing operation | Hook |
| --- | --- |
| Final accepted per-soldier XP reward | Replace the legacy clan influence calculation with `settle_experience(db, account, identity, experience, city_coefficient=coefficient, now=stamp)` |
| Successful premium **item** purchase charged in Gold | `premium_gold_spent(db, account, identity, actual_gold_debit)` in the purchase transaction |
| Shared hourly maintenance | `decay(db, now=stamp)`; bounded catch-up and retained fractional charges |
| Ordinary city sale gross | `sales_tax(db, account, identity, city, gross, premium=False)`; use returned `net` as seller's credited amount |
| Premium sale | Same tax helper with `premium=True`; no tax charged |
| Next base event creation | Resolve `scheduled_start(db, base_location, default_start)` before building the event |
| Shared assault finalization | `settle_assault(db, event_id)` after the final warfare receipt is inserted, before the same outer transaction commits |
| Completed UTC calendar week | `close_week(db, week_start, now=stamp)`; waits for unfinished warfare events and settles finalized results once |
| Accepted opponent kill rank reward | Add `rank_per_kill(db, account, now=stamp)` to eligible base kill points before applying existing cap/anti-abuse rules |
| Safe city warehouse refresh | `deliver_prizes(db, account, capacity=3000)`; return its actual private warehouse packets |

`settle_experience` receives `{pet_id: actual_awarded_xp}` and verifies soldier
ownership. Its receipt contains `amount`, `clan_id`, and the applied multiplier.
The calculation includes the city/reservation coefficient, premium influence,
highest earned achievement factor and highest assault medal factor, divided by
20. Do not also run the legacy `clans.settle_influence` for the same reward.
`premium_gold_spent` excludes bank conversion, bonds, paid Gold purchase and
premium subscription purchase. Only the successful premium item shop debit
earns this influence; never use catalog previews or a client-provided amount.

`sales_tax` uses the actual city ID, mapped to its controlling base. Included
tax is `floor(gross * percent / 100)`; the tax helper credits the clan safe and
returns the seller net, so a caller must not credit both net and gross. A replay
returns the same receipt; the whole sale action must also be replay-safe.

`settle_assault` reads finalized `warfare_events`, `warfare_event_receipts`,
`warfare_scores` and frozen `warfare_matches` rosters. It never accepts client
scores or user-supplied side assignments. It awards the 10,000 influence capture
bonus once, top-20 per-side tokens/boosters, top-three medals, weekly clan scores,
and an escrowed defense fund. Do not independently award the same capture bonus
or duplicate these prizes in territory finalization. Use its receipt's
`players[account]` entries (`side`, `place`) for the achievement hooks below.
Weekly badge values 5/4/3/2 are **additional** rank points per eligible kill,
matching manual printed p27; they are not a replacement for base kill points.

## Owner actions and projections

`set_crest(db, account, bmp_bytes, identity)` validates an uncompressed 24-bit
16×16 BMP, charges 1,000 credits once, and returns `crest_id`/`charged`.
Identical current content is free. `crest_id(db, clan_id)` reads the projected
native ID; `crest_content(db, crest_id)` returns validated bytes. Content upload/
download is not assigned an invented historical opcode.

`set_base_tax(db, leader, base, percent, expected_revision=revision)` enforces
ownership, revision, 0–10% and no unfinished assault. `schedule_options(start)`
returns the explicit configured UTC choices; `set_next_assault(db, leader,
base, default_start, chosen_start, now=stamp)` validates the fixed weekly day
and rejects already-created events. `fund_defense(db, leader, event_id, credits,
identity)` escrows clan safe funds during registration only.

Read `config/clan_benefits.json` for explicit emulator choices where the manual
does not recover numeric medal multipliers, prize counts, defense distribution,
decay rounding or schedule times. These choices are not historical server claims.

## Earned achievements and profile bonuses

`tio/achievement_benefits.py` reads immutable earned `achievement_awards.body`
prizes. `rating_bonus(db, account)` sums kind3 bonuses once per earned award;
`influence_multiplier(db, account)` returns the highest kind1 `Fraction`, default
1. Delivery/notification flags do not gate earned bonuses. These APIs do not
include premium or medals. `total_rating(db, account, base_rating)` combines the
base and earned rating, preserves negative legacy ratings, and bounds the native
field. `server/public_profile.py` already uses this profile bonus. Top100 must
use the same total and must not add the bonus twice.

The released `clan_benefits.influence_multiplier` still contains its initial
award-reading loop. Root integration must replace that loop with the validated
`achievement_benefits.influence_multiplier` call while preserving the surrounding
premium and medal factors; the released module is root-owned.

All event hooks in `tio/achievements.py` join the same authoritative transaction:

* `influence_received(db, account, event_id, receipt['amount'])` after a successful
  XP/Gold contribution, before `snapshots` or reward flushing. Zero is valid.
* `assault_result(db, account, event_id, captured=bool, defended=bool, place=place)`
  using finalized clan ownership, actual participation and the per-side ranking.
  Capture and defense flags are mutually exclusive. `place <= 20` increments
  the existing top-20 counter. Never infer participation from current city presence.
* `ranked_result(db, account, match_id, result=result, league_before=before,
  league_after=after, streak=accepted_streak)` immediately after accepted ranked
  settlement. Original league indices: platinum0, gold1, silver2, bronze3;
  result1 means win. Loss/draw requires streak0. Bronze-win uses the **before**
  league, so promotion victories count correctly.

Hooks prefix their own receipt identity (`influence:`, `assault:`, `ranked:`),
ignore identical replay and reject changed replay. Event IDs must identify the
specific XP/shop/assault/match event consistently and remain at most160 characters
including this prefix. Do not call an additive influence hook after a snapshot
already incorporated that same new contribution; run the hook first. Existing
`snapshots` captures real saved contribution/league and separates human mercenary,
dog and miner levels. Reward flushing marks validated kind1/3 bonuses delivered
without mutating base rating or multiplying influence again.
