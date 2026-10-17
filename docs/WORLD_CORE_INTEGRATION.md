# Phase8 world core integration

These shared location/map/scene rules were installed as phase8 on
2026-10-08 at 15:06:49.209408 UTC; the exact27-file deployment and saved-table
preservation are recorded in
`reports/gameplay-completion/stage8-world/deployment.json`, backup
`/root/tio-before-gameplay-completion-gqmepid1`. Client assets are not published
by that deployment. Ordinary hosted world QA is running; live GUI acceptance
is not claimed.
`config/world_completion.json` remains the source of the explicit emulator ID,
coordinate and map composition policy. Original Outpost4/Prison10 bounds and
Detroit whole-map resources are distinguished from new geometry in that file.

## Released source scope

* `tio/cities.py`: adds Outpost4 and Detroit18 using `extra_cities()`. Their
  ordinary combat admission requires a nonempty selected roster and levels4–20.
  Existing city calls with empty legacy test rosters remain accepted.
* `tio/locations.py`: extends `TOWNS` with `location_bounds()`, adds relocated
  capturable Base7 to `BASE_LOCATIONS`, and projects training/prison level bands
  through the existing native TownInfo packet. Training19–22 are not capturable
  bases. `LocationStore.travel()` calls `require_travel(db,account,destination)`
  inside its writer transaction before modifying any journey/location.
* `tio/map_generation.py`: preserves the local custom profile/max8-deployment
  contracts API. Detroit dispatch uses its original small38×38 map for modes0/7
  and large50×50 map for modes1/4. It accepts strict wager sizes1–4 through the
  composition policy below, preserves `None` ordinary maps, and rejects custom
  variants or unsupported world-profile size requests.
* `tio/team_scene.py`: appends optional `town_id=None` to `prepare()`, validates
  all admitted real/bot seat levels, selects the world map and records primitive
  `scene_metadata['world_policy']`. Outpost crates are filled at scene birth from
  the existing explicit loot policy with a seeded RNG and unique temporary item
  IDs. No source inventory is deleted or rewritten by this preparation.

There is no `tio/travel.py` in this repository; individual native1B travel is
implemented by `tio/locations.py`.

## Exact root calls

In the shared `TeamArena.start_match` scene factory, append **`town_id=town`** to
the existing `prepare(seats,mode,...,profile=city.profile,...)` call. The city is
the already authenticated initiating location, not a client-supplied map name.
Outpost and Military Zone currently share `military_zone`, so the town ID must
be supplied to distinguish their admission/inventory/rank policy. A legacy
`profile='detroit'` call infers18, but new runtime calls should pass the town.

Return shape stays `(field,views,encoded_ground,skills)` with one shared field,
views keyed by real owner IDs, and native Ground packet. `world_policy` is:

```python
dict(version=1,town_id=town_id,levels=(low,high),carry_items=bool,
     max_upgrade=int,rank_gain=town_id != 4,
     map_geometry='original_whole_map_v1' if town_id == 18
                  else 'procedural_military_v1',
     bonus_crates=town_id == 4)
```

The reviewed Detroit wager candidate now supplies that distinct composition
policy, reusing `config/wagers.json` scales1,5/4,3/2,7/4. The intact original
resource is centered on an expanded brush6 canvas: mode0/7 dimensions are
38/47/57/66, mode1/4 dimensions50/62/75/87, with integer-floor rounding.
Ordinary maps remain exactly38/50. The read-only admission preflight rejects
invalid scales/sizes/bounds before escrow; doors, boxes and collision translate
with the art, and expanded deployment is checked for connectivity. See
`reports/gameplay-completion/stage8-world/detroit-wager-candidate/README.md` and
the eight production-import regression cases in `test_detroit_wager_maps.py`.
These are explicit server dimensions, not recovered historical wager dimensions.
The root applied the reviewed patch to frozen27, passed final public validation
and installed it. Ordinary hosted QA and the world client publication remain
pending; the positive LV4 wager cases remain isolated proofs.

Root owns admission `freeze_city(db,global_match_uuid,town,now=...)`, its receipt
storage and reward coefficient application. These scene metadata values do not
replace the frozen XP/influence/profit receipt. Outpost requires suppression of
the **entire** rank report, including confirmed kills, deaths, city kill bonuses
and weekly medal bonuses; setting only `city_kill_bonus=0` is insufficient.

## Outpost temporary inventory and persistence contract

The frozen phase8 runtime now implements the empty battle copy and personal
inventory CAS projection described in `OUTPOST_EQUIPMENT_INTEGRATION.md`.
`world_policy['carry_items'] == False` records that admitted policy. The
implemented integration retains the following invariants:

1. Retain every actor's original personal `ItemRecord` tuple separately in
   serialized primitive/dataclass state keyed by battle actor ID. Do not DELETE
   or overwrite `owned_pets.inventory_packet` at entry, and do not classify saved
   personal IDs as loot-temporary IDs.
2. Remove personal equipment/items from the **battle copy** and recompute the
   battle actor's armor, HP/AP/sight/weight/equipment effects and native soldier
   templates from that empty copy. Copying a fully equipped actor and merely
   sending an empty ItemList would retain invisible equipment benefits.
3. Keep persistent CAS old/new projections equal to the retained original
   personal records. Current `Combat._persist_inventory()` compares the old
   packet against saved `owned_pets`; simply filtering battle inventories would
   cause a CAS mismatch. Both old/new projections must merge the retained
   originals before converting battle actor IDs to `storage_ids`.
4. Keep crate/collected/battle-issued IDs in `Combat.temporary_items`. Current
   BattleLoot allocates IDs above selected/reserve/warehouse/retired IDs and
   filters temporary IDs from persistence. Temporary supply consumption must
   never consume an original record or persist a crate pickup to a warehouse.
5. Restore the personal view at return/reconnect outside combat. Persist the
   retained-original map and all policy flags in the existing allowlisted Combat
   graph, preserve them in journal rollback, and clear them only after durable
   settlement/return. Do not introduce an unregistered Combat subclass.

`field.loot.boxes` contains prefilled Outpost supply tuples at birth;
`field.loot.opened` starts empty, so existing open-container AP charges and
achievements apply to observed native actions. Its RNG is seeded with
`map_seed ^ 0x4C4F4F545F54494F`. Allocation and RNG survive the existing snapshot
codec. Existing explicit arena-map callers retain their caller-owned loot policy.

## Restricted locations and native travel

New clicks on Prison10 are rejected with no sentence/schema/route mutation.
Trusted `world_completion.sentence()` cancels an existing individual journey and
moves the actual account to10. `LocationStore.current()` now recognizes10, so
root's online authenticated heartbeat can project that location normally.
Only root's `prison_online()` authenticated heartbeat/disconnect path charges
online seconds. The travel layer never invents a jail penalty.

A pre-extension journey whose saved endpoint falls inside Prison's newly enabled
rectangle finishes on the world map (`town_id=-1`) with a native stop packet. It
does not open Prison. Other established journeys retain interpolation, endpoint,
arrival transaction and reconnect semantics. Routes attempting to move an
actively sentenced account are rejected; trusted sentencing normally cancels
such routes first.

Training19–22 can be reached and project their level bands. They intentionally
reject ordinary combat admission. The frozen runtime's `TrainingArena` now uses
`require_location(town,levels,training=True)` and an original `AssaultLayout`,
enforces configured upgrades/no capture, and journals the shared lifecycle.
MultiServer initializes it before checkpoint recovery; authenticated arrival
uses `world_runtime.project_town` to attach its native ZoneInfo. Base7 is enabled
in the installed public territory configuration. Ordinary hosted QA remains
separate from these completed integration and deployment checks.

## Actual-host map generator override

Read-only SSH used the configured `tio_server` identity to fetch the current
hosted `/opt/tio-emulator/tio/map_generation.py`. Exact bytes are saved in:

* `reports/gameplay-completion/stage8-world/source/map_generation.py`
  SHA256 `48ab66cd092e18d9908d9a70f19af19009173fd50d7396ecc3374d99e49f5f52`.
* `reports/gameplay-completion/stage8-world/runtime/tio/map_generation.py`
  SHA256 `0ef8d0c4b1236a1f19257a28f7d5ff1759b93611101835e2c2cca48a7ba48b18`.

The runtime override adds only the Detroit dispatch branch to that source.
Removing that exact branch reproduces the complete original byte stream. Its
signature contains no `profiles_path`, `profiles_data`, or local contracts
deployment extension. Use it as the phase8 **fileoverride**, never copy the local
`tio/map_generation.py` over the hosted generator. Recheck the actual remote
base SHA at integration/publication if another deployment changed this file.

## Verification and completed local compatibility

`tests/test_world_core_integration.py` checks new location bands, strict arena
admission, two-account native travel/arrival/reopen isolation, restricted Prison
admission/real moderation release, old-route migration, original Detroit Ground,
actual-host override parity, two real saved owners in one scene, Outpost unique
temporary crate supplies, unchanged saved rosters, and snapshot/RNG replay.

Root completed the local namespace/geometry adapter in `tio/pve_contracts.py`:
the separate local contract catalogue may reuse public IDs only for disjoint
bounds, with its validated fifteen-cell margin. Public Training20 now uses
[-240,-420,-220,-400] and Training22 [110,-320,130,-300]. The focused
contract/world-namespace/party checks pass66 tests. The local-only explicit
contract map scene regression is now `tests/test_contract_world_scene_compat.py`
and passes its separate one-test run. These are local compatibility results,
not a hosted contract deployment or account migration.

The frozen27 public runtime contains no local contracts source/config/XML.
Its `evidence/zones_diagnostic.xml` is the separately prepared public overlay in
`reports/gameplay-completion/stage8-world/runtime/evidence/zones_diagnostic.xml`;
the native/catalogue checks and revised cities consistency check use that
candidate explicitly. The original local contract-bearing diagnostic XML is
preserved and is not a source for the hosted release. Final
`reports/gameplay-completion/stage8-world/validation.json` passed242 local and
242 remote-isolated tests in10 batches. Original native checks passed22 towns,
44 visibility cases and9 Top100 requests/13 cases; its `world_client_release`
matches the actual deployment. All135 old table contents,199 accounts and198
wallets were preserved. Ordinary hosted world QA and client2026.10.08.5
publication remain pending until their own canonical reports establish success.
