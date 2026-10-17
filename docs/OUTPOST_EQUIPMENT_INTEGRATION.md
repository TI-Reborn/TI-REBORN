# Outpost equipment copy: integration handoff

This scoped change modifies only `tio/combat.py`, `tio/team_scene.py` and adds
`tests/test_outpost_equipment_copy.py`. No hosted code/config/save deployment or
ordinary account action is performed. It completes the empty-equipment/CAS
portion of `WORLD_CORE_INTEGRATION.md`.

Current integration status: the installed27-file phase8 runtime includes this copy/CAS
logic, complete town4 rank suppression and admission-frozen coefficients in the
shared SQL journal/reward path. The scoped local/native checks passed; no
positive ordinary hosted Outpost battle or GUI acceptance is asserted. Actual
deployment on2026-10-08 at15:06:49 UTC and242 local/242 remote-isolated checks
passed (`reports/gameplay-completion/stage8-world/deployment.json` and
`validation.json`). The first ordinary hosted arrival and LV1 admission rejection
passed; final travel-return/world QA and client.5 publication remain pending. The
responsibilities below describe implemented invariants, not missing wiring.

## Actual hosted baseline

Read-only SSH with the configured `~/.ssh/tio_server` identity fetched exact
`/opt/tio-emulator/tio/combat.py` into
`reports/gameplay-completion/stage8-world/source/combat.py`.
The remote and pre-change local SHA256 were both
`d14ce3e7f05aa6e92f73683cf78ae845c707addc1416508da0cbd5089ad902da`.
No Combat deployment override is needed: this candidate preserves that actual
hosted baseline and adds only the reviewed Outpost copy logic. Recheck this
baseline before publication if another release changes hosted Combat.

## Root scene calls

Ordinary town4: pass the authenticated town through the existing API:

```python
field, views, ground, skills = prepare(seats, mode, town_id=4, **existing_kwargs)
```

Its existing4..20 admission is retained. Every admitted real/transient actor
starts with an empty authoritative battle inventory; saved personal packets are
not deleted or replaced. The return signature is unchanged.

Outpost Base7: after root's existing authoritative shared territory admission,
use the explicit supplied assault layout:

```python
field, views, ground, skills = prepare(
    seats, 0, arena_map=layout.arena, selected_ids=True,
    profile='assault', town_id=7,
)
```

Only that trusted explicit-layout path accepts7; an ordinary town7 matchmaking
call still rejects. It validates4..20 and applies the same retained personal
inventory and empty-copy projection. Root continues setting actual assault
mode, event, enhancement cap, result/reward/return rules afterward.

The same explicit-layout path accepts training19..22 using
`require_location(town,levels,training=True)` and preserves their carried gear.
Ordinary training-location admission still rejects. This is compatible with
the released `server/training_arena.py` contract. Native ground bytes come from
the supplied original layout. Its metadata describes `original_assault_v1`.

## Combat state and persistence

`Combat.personal_inventories` is a primitive dict:

```python
{global_battle_actor_id: exact_original_ItemList30_bytes}
```

The packet owner is the global battle actor ID. Its records/unknown flag are
the original saved personal inventory. Existing `storage_ids` maps that actor
to the account-local saved pet ID only at the final persistence boundary.
Shared accounts may have equal personal item/pet IDs; their persistence routes
remain separate `(path,account)` entries.

`persistent_inventory(packet, temporary_ids=None)` retains its existing API.
For an excluded actor it returns this exact retained packet for **both** the
old and new optimistic-CAS projections. All battle supplies must be in the
existing temporary-ID set; hidden originals must never enter that set. Invalid
classification rejects. The existing `_persist_inventory`/`_persist_batch`
transaction and profile CAS remain in force: stale city edits reject instead
of being overwritten, including rollback of an earlier account's update.
Temporary pickups/equip/wear/ammo/medicine/death drops never write a supply ID
or consume/wear an original personal record.

The birth-time `exclude_personal_equipment(actor_id,catalog,template,*,pet_packet=None)`
method returns `(native_template, learned_abilities_packet)`. Persistent actors
are read again from their actual saved base PetInfo and checked against their
retained original inventory. Transient actors require that raw base profile
from the scene factory. Reprojection starts from normalized saved skills, then
applies learned passives using an empty local inventory: HP/current HP, armor,
carrying capacity, weight, sight, AP budget, weapons and all native equipment
fields are recomputed. Tank melee, Exo carry, helmet sight, shield/armor,
Groza-granted ability27, rental tax and overload effects disappear. Learned
health/carry/defense/accuracy and miner/dog abilities, native LV/XP/rank remain.
No subclass or new snapshot registry entry is introduced. Serialization is
staged before live field/maps are replaced.

Loot allocation reserves **all** retained personal IDs, including transient
actors without persistence routes, before rolling any Outpost crates. Crate
supplies remain seeded and temporary through the existing BattleLoot mechanism.

## Root snapshot, journal and return responsibilities

The existing snapshot codec already supports this bytes/dict attribute on the
allowlisted Combat graph; the test resumes actual supply consumption after a
round trip. Older snapshots without the attribute use `getattr(...,{})` and
retain normal inventory behavior.

Include `personal_inventories` in root's Combat journal capture/rollback state
and retain it until durable settlement/return. It is immutable after scene
birth; do not clear it on death, disconnection, temporary owner removal or
reconnect. Do not classify its records as loot. Returning city ItemList and
PetInfo continue reading the actual saved inventory, so personal gear naturally
reappears. No saved-health/XP/rank reward policy is changed by this package.
Root still owns complete town4 rank suppression, admission-frozen city reward
coefficients and its settlement receipts.

## Verification and limits

Focused tests use two actual SQLite save owners and native ItemList30,
BattleSoldier3B and abilities80 codecs. They cover human/miner/dog projection,
original flags/IDs and gear preservation, learned passives, Groza removal,
actual crate pickup/medicine/ammo/weapon training CAS, stale city rejection,
multiowner SQL rollback, temporary death/return, snapshot consumption, transient
ID reservation, Base7/training explicit-layout calls and ordinary rejection.
Validation counts/SHA256 are in
`reports/gameplay-completion/stage8-world/outpost-validation.json`.

An initial combined run took longer than the bound. A verbose isolated rerun
confirmed the existing encrypted native crate transport test passed and traced
the delay to the following
`tests.test_battle_loot.BattleLootTests.test_positions_match_real_fragment_records`,
which repeatedly traverses original external assets via `read_fragment/rglob`.
The bounded20second diagnostic exited in that asset census. The final scoped
run includes native crate transport and excludes only this external asset
census, recording its exact ID. This is not a full asset-catalogue regression
or hosted GUI acceptance. No graphical or hosted Outpost battle was performed
by this package.
