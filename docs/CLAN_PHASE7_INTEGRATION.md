# Phase 7 integration handoff

This change wires existing clan/achievement policy into authoritative territory
finalization, public profiles and optional battle rank reports. It adds no
runtime maintenance, transport opcode, database backfill or hosted update.
Shared server admission/action/journal and `battle_rewards`/shop hooks remain
root-owned. The policy and original manual evidence are described in
[CLAN_BENEFITS_INTEGRATION.md](CLAN_BENEFITS_INTEGRATION.md), [RANKS.md](../RANKS.md)
and `config/clan_benefits.json`.

## Battle XP transaction

The backward-compatible signature is:

```python
clans.settle_influence(db, account, experience, *, identity=None,
                      city_coefficient=1, now=None)
```

`experience` is `{owned_pet_id: actual_awarded_xp}` after existing accepted XP
policy. Inside the existing battle reward transaction replace the old influence
call (and old `cities.CITIES` influence gate) with:

```python
from fractions import Fraction
from tio.clans import settle_influence
from tio.world_completion import frozen_city

city = frozen_city(db, global_match_id)  # previously frozen at admission
influence_receipt = settle_influence(
    db, account, actual_experience_report,
    identity=global_match_id,
    city_coefficient=Fraction(city['influence']),
    now=reward_timestamp,
)
```

The real shared match UUID is the stable operation key. It is not a turn ID,
timestamp, username or generated ID at settlement. A reservation coefficient0
creates a durable zero receipt; subsequent clan membership does not backfill it.
The result is a dict with `clan_id`, `amount`, `multiplier`, as returned by
`clan_benefits.settle_experience`. The adapter also calls
`achievements.influence_received(db, account, 'xp:'+global_match_id, amount)`
before any achievement snapshots/flush. The resulting event identity is
`influence:xp:<UUID>`. Do not call the benefit or achievement hook a second time.
The whole enclosing battle reward transaction, including the existing
`battle_rewards(match_id,account)` receipt, must commit once. Wagers must keep
bypassing every progression hook.

An unchanged retry returns the original multiplier/amount even after premium
expiry; changed XP/coefficient rejects and rolls back. Benefit helper overflow
also rejects the whole transaction. The old three-positional-argument form
retains its original calculation and `None` return; its existing outer battle
receipt supplies replay protection. Supplying `now` or a nondefault coefficient
without `identity` rejects instead of inventing an operation key. The complete
achievement event ID must fit 160 characters (XP identity at most 147).

Root must also replace the legacy earned-prize loop in the root-owned
`clan_benefits.influence_multiplier` with
`achievement_benefits.influence_multiplier(db, account)`, preserving the premium
and permanent medal multipliers. The adapter does not reimplement these factors.

## Territories: already integrated

`TerritoriesStore._sync` and `_current` now resolve
`clan_benefits.scheduled_start(db, town, default_start)` for actual base locations.
The default weekly day is retained, but event birth/ID uses the chosen start.
Both 12 UTC before the former 18 UTC start and 21 UTC after it are tested.
Checkpoints retain their existing start policy.

Continue calling `TerritoriesStore.finalize(event_id)` exactly as before. New
final receipts contain `benefits_version:1`; in the same existing transaction it:

1. Computes accepted shared scores and ownership/ordinary assault influence.
2. Stores the final receipt and marks the actual event finalized.
3. Calls `clan_benefits.settle_assault(db, event_id)` for capture 10,000 influence,
   top 20 prizes, medals, defense fund and weekly scores.
4. Calls `achievements.assault_result` only for frozen contested score accounts,
   with their per-side prize place, base capture/defense outcome and frozen clan.

Root must not add another capture 10,000 award, another `settle_assault` hook or
another assault achievement call around this finalizer. Empty/uncontested events
create no synthetic participant achievements. Base defense excludes neutral
checkpoints. An error in prize/achievement writing rolls back claim changes,
ordinary influence, all prizes and finalization together. Marked retries replay
the same benefit/achievement receipts without adding rewards again. Old unmarked
final receipts are returned unchanged and are not backfilled by this adapter.

The existing root-owned `close_week` currently calls `settle_assault` directly for
all finalized events in a week. Before enabling historic-week maintenance, root
must enforce the same `benefits_version==1` eligibility there; otherwise it could
backfill legacy final receipts despite this finalizer's protection.

## Accepted-death rank bonus and journal hooks

The backward-compatible signature is:

```python
ranks.battle_report(combat, owner, *, weekly_rank_per_kill=0,
                   weekly_rank_by_victim=None)
```

At every accepted unique opponent death (including authoritative hazard kills),
capture the actual killer account's badge at the server timestamp:

```python
from tio.clan_benefits import rank_per_kill

accepted_death_bonus[victim_global_actor_id] = rank_per_kill(
    db, killer_save_owner, now=accepted_death_timestamp)
```

Use the existing transaction/action rollback boundary, then include this map in
the authoritative journal/snapshot and preserve it through reconnect/recovery.
The map can be shared for the match because each accepted victim has one credited
killer; it must never be client-authored. It needs an explicit zero entry when no
badge is active. At settlement:

```python
report = ranks.battle_report(
    combat, battle_owner_id,
    weekly_rank_by_victim={int(k): value
                           for k, value in accepted_death_bonus.items()},
)
```

JSON restoration must convert object keys back to integer global actor IDs.
Unknown deaths, string keys, negative/out-of-range values and booleans reject.
Only the first eligible opponent death earns the added 0..5 points: no mutant,
ally or level-ineligible bonus. With a supplied map, missing entries give 0 and
never fall back to the constant argument. Thus a badge expiring during a match
does not continue granting a birth-time bonus, and replay does not read a later
wall clock. Wagers always suppress the weekly addition. Existing rank caps,
repeat reduction, result/premium factors and outer reward receipt are retained.
The optional constant integer is retained for older fixed-bonus callers; use the
per-death map for exact badge TTL. Journal/snapshot wiring is still root-owned.

## Public profile, rating and crest transport

`server.public_profile.read_profile` now projects the actual stored
`clan_benefits.crest_id` into `PublicProfile.clan_crest_id`. It remains a read-only
snapshot; absent clan/crest returns 0. Alliance crest remains 0 because there is no
corresponding stored content policy. No upload/download opcode is invented.
Root still needs the authorized account HTTP/content route for `set_crest` and
`crest_content`, and the actual client's image loading route must be verified.

The shared `achievement_benefits.total_rating(db, account, base_rating)` now
clamps the combined value to signed 32 `[-2147483648,2147483647]`, matching native
Top100's i32 and the public profile. `rating_bonus` remains bounded u32; delivery
flags do not alter earned bonuses or base stored rating. Profile and Top100
must use this helper once and must not add earned bonuses again.

## Remaining root runtime calls

See the released backend contract for the exact signatures. Within each actual
gameplay transaction root still needs:

- Premium item Gold debit → `premium_gold_spent`; then the actual returned amount
  → `influence_received` with a distinct stable `gold:<shop-operation>` identity.
- Ordinary sale → `sales_tax`, credit returned seller `net` once.
- Hourly maintenance → `decay`; completed UTC weeks → `close_week` with the legacy
  eligibility guard described above.
- Safe city warehouse refresh → `deliver_prizes`, send its private returned
  warehouse packets only after commit.
- Authenticated base/crest actions → existing owner methods from the backend
  contract. Runtime routing and HTTP auth remain outside this patch.

## Verification

18 new integration tests exercise real temporary SQLite stores and accepted
territory match results: multiplier/achievement replay, no clan backfill,
transaction faults, frozen participant outcomes, early/later event creation,
rank TTL/reconnect map, rank cap/repeat/reward replay, read-only crest projection
and equal signed profile/Top100 values. Combined regression run:

```powershell
$env:PYTHONPATH='C:\TIO-emulator\tests;C:\TIO-emulator'
python -m unittest tests.test_clan_benefits_integration tests.test_clan_benefits tests.test_achievement_benefits tests.test_public_profile tests.test_player_top100 tests.test_world_completion tests.test_clans tests.test_territories tests.test_ranks
```

Result: 128 tests passed. These are automated local checks, not hosted deployment
or validation with real clients. No hosting service/accounts/saves were changed.
