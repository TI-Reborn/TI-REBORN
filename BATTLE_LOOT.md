> Обновление 2026-09-28: наземные рюкзаки, выбрасывание во всех боевых сценах,
> выпадение временных вещей и бура с кристаллами при смерти: [GROUND_LOOT.md](GROUND_LOOT.md).

> Update 2026-09-19: Ordinary Survival now uses generated Reservation scenes; crate positions/counts come from each scene, not the four-box diagnostic layout below. Loot is rolled once during scene preparation and remains battle-local. See BATTLE_MAPS.md.

# Battle crates — 2026-09-19

Implemented for the current Survival arena. Restart the emulator/client with
`python tools/run_reservation.py`, start a new battle, approach a steel crate,
and click it during the selected mercenary's turn. The original two-panel
inventory opens; drag items and close the window to commit the transfer.

## Open-crate appearance — follow-up

The user confirmed looting works in the live game. On the first successful
opening the server now sends **44 x y 01 00** before47. No additional AP cost,
resource replacement or client hook is involved. The original scene changes
the existing crate to its open frame and retains that state for the battle,
including when the inventory becomes empty. A new battle starts closed.

Original resources: `base/setting/military/item_steel_box_01.t`, `01u.t`,
`01b.t`, `01bu.t`; texture families `steel_box_01.png` / `steel_box_01b.png`.
Their metadata includes `cnt_chest_open`. These are the installed game's
resources; no generated graphics are used.

Important protocol distinction: silver.dll961F60 consumes only x/y from44,
but ti.exe6DD34C queues the scene event, whose consumer6F5D7A reads **four**
bytes. The third byte selects open state4 (visible transition) or2 (offscreen
immediate state) through72DC90. The fourth byte is sent as0, giving grid cell
flag1. Original72D64C selects `base_frame + 1` for state2, preserving the
crate's orientation. The scene update72FF35 settles state4 to2 and selects
the same frame when it becomes visible. Sending only44/x/y would under-read
the native scene payload. Sending45 would clear the container cell flag; it
is not the open-lid command and is not used here.

Verification: `tools/verify_crate_visual_native.py` runs the original44
consumer, state setter and frame setter, plus the visible-state settlement
fragment: **4 PASS** (visible/offscreen, two base-frame values). Scene-object
lookup, visibility queries and sound are isolated. Results are in
`evidence/crate_visual_native.json`; this is native execution, not a live
graphics test. All **385 unit/integration tests PASS**, including15 loot
tests and encrypted transport ordering. Log: `data/crate-visual-tests.log`.
Restart the emulator/client and start a new battle for visual verification.

## Original evidence

- [Administration: Quick start, 2012-02-21](https://ggeek.ru/forum/blog-administratsii/72014-bystryj-start/):
  opening costs 4 AP; the left panel contains the mercenary's inventory and
  the right panel the crate. Found items disappear after the battle while the
  player's own equipment remains.
- [Original manual](https://ti.ggeek.ru/files/TIO_manual.pdf), inventory section
  p23: 18 inventory places, including equipped items. The PDF endpoint is
  intermittently unavailable; its indexed passage was used during research.
- `base/quest/tut_1000.xml`: tutorial instructions take a weapon, ammunition,
  grenade and sniper weapon from crates. These instructions are not a general
  random drop table.
- Original `silver.dll` constructor `9DC861..9DC881` initializes unseal=4,
  reopen=1 and equip=2. The field names are in the settings RTTI.
- Original native `CanOpenContainers A86C18` checks the humanoid resource
  group. Server access uses the existing human/dog profile distinction.
- Map fragment `.s` model records identify actual `item_steel_box_01.t` and
  `item_steel_box_01b.t` objects. Coordinates are imported, not assigned to
  every decorative wooden/paper box.

Current world positions: `(4,8)`, `(7,4)`, `(18,11)`, `(18,24)`. The user's
request `46 03000000 12 0B` refers to actor3 opening `(18,11)`.

## Server behavior

- First opening of each crate costs 4 AP; later openings cost 1 AP. Each46
  request represents an opening. An unchanged dialog closes without a40,
  so suppressing same-turn requests would make legitimate reopening free.
- The crate is generated once per match and shared by actors in that match.
  Reopening never rerolls. An empty crate remains empty.
- Checks living actor ownership, selected actor/current unexpired turn,
  real crate coordinates, adjacent position, AP and quantities. Server
  adjacency currently allows one cell including diagonals; this distance
  policy has not been fully matched to every original cursor/path branch.
- Transfer40 is committed on closing the native dialog. It carries deposits
  followed by withdrawals. The response refreshes the bag with30; sending47
  again would reopen the window.
- Inventories retain the existing stacking rules, slot limit, item weights,
  overload calculation and persistent consumption of the player's supplies.
  Temporary and permanent supplies never merge into one saved stack.
- Loot weapons and supplies work through existing combat actions. Added
  armor equip/unequip with 2 AP cost and original class/sex/level/slot rules,
  updating defense and the visibility template.
- Every generated item and its split descendants are tracked by battle-local
  instance IDs. `Combat._persist_inventory` excludes these IDs from **every**
  database write, not just settlement. Winning, losing, disconnecting or
  restarting therefore cannot export crate loot to the warehouse/city.
- Dropping one's own loose supplies into a crate removes them from the saved
  bag; retrieving them restores permanent ownership. Deliberately abandoned
  supplies remain abandoned. Equipped, marked/rented and SE items cannot be
  deposited through this subset of the container protocol.
- Duplicate/stale transfers are rejected; no partial mutation on validation
  or snapshot conflicts. Rejection sends the authoritative owned inventory
  to restore the client's optimistic drag state and release its wait flag.

## Explicit local balance, not recovered drop probabilities

`config/battle_loot.json` records the assumptions. One supported ordinary,
non-SE weapon, one ordinary armor item, and 1–3 Bandages or Candies are chosen.
The weapon receives 1–2 original ammunition packs, if applicable; a Frag
Grenade has an additional 25% chance. Equipment uses the highest participating
player mercenary level as its level ceiling. Templates, restrictions, weights
and ammunition pack sizes come from the imported client metadata.

The precise historical server drop tables were **not found**. These pool and
probability choices are provisional emulator balance. Unsupported weapon
attack types and special/miner-only equipment are excluded from this pool.
Items use source durability; destruction after
battle is enforced by the server's temporary-ID tracking, independently of
client durability display.

## Recovered packet paths

| Action | Native code | Wire |
| --- | --- | --- |
| Open | `95E114` | `46 u32 actor, u8 x, u8 y` |
| Contents serializer | `640718`, entry `63FC90` | `47 u32 actor, u16 x, u16 y, u32 count, entries` |
| Contents consumer | `991508` → `9B1440` | populates cell item array and opens two-panel inventory |
| Transfer | `98F5CC`; queue `9DCE5C` | `40 u32 actor, u8 x, u8 y, u32 depositCount, pairs, u32 withdrawalCount, pairs` |

Each pair is instance/count as two u32 values. Ordinary47 entries are 25
bytes: instance/template/count, three durability words, effective/real
upgrade, SE/marked/rented flags, optional-name/time presence flags. Generated
loot has no optional fields. `tio/protocol/battle_loot.py` implements this
subset; inventory30 remains the canonical bag format.

## Verification

- `python -m unittest discover -s tests -v`: **384 PASS**, including 14 loot
  tests. Coverage includes actual map records, single generation, AP, native
  wire shape, split/merge conservation, capacity, ownership/turn checks,
  atomic failures, own-item deposit/retrieval, equip/consumption, encrypted
  transport rejection refresh, settlement and fresh database reload.
- `python tools/verify_battle_loot_native.py`: **8 PASS** against SHA256
  `a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.
  The authoritative complete SHA is recorded in
  `evidence/battle_loot_native.json` and checked by the probe at startup.
  Original47 serializer,46/40 writers,47 consumer field writes and the call
  to the native inventory window execute in Unicorn. Allocation, managed
  copies, actor/cell lookup and UI are explicitly isolated. AP defaults also
  execute from the original constructor.
- Results: `data/loot-tests.log`, `evidence/battle_loot_native.json`.

No game DLL modifications or new Frida hooks. No player database mutations
during these checks. Actual rendering and drag/drop in the running game still
need the user's next test after restart; native execution is not a live UI test.
