# World completion package: integration contract

This bounded package contains only new backend/config/overlay/probe files. It
does not modify existing routing, live accounts, territory ownership or client
catalogs. Root integrates and deploys the multiplayer service and performs the
actual-client checks. Local checks are not hosted multiplayer completion.

## Source and explicit policy

The local manual `reports/chat-presence/manual.txt`, printed pages11–13/85,
provides Detroit/Outpost/Prison/training and the4–6/7–10/11–15/16–20 upgrade
bands. Outpost has XP0.75, influence0, profit1 and no rank points. Detroit uses
the usual floating1/1/4 factors, equipment admission and+10 kill rank bonus.
Prison time is online-only. Training bases cannot be captured.

Original `towns.cfg` contains Outpost4, Prison10 and Outpost Base7. Exact town4
and10 geometry/art are retained. Base7's original bounds overlap active Mine14;
its new bounds315,-410..335,-390 are explicit emulator relocation. Detroit18
and training bases19–22 are contiguous new IDs at collision-free coordinates.
No historical claim is made about new IDs or coordinates. Existing IDs1–17,
including Mine14, remain unchanged except activated/amended4/7/10 records.

The four dynamic cities use a balanced deterministic UTC hourly rotation
0.8/1/1.2/1 around1/1/4. The historical fluctuation algorithm is unavailable.
Detroit item upgrade cap25 follows current emulator support; the manual has no
city cap. The original Assault4 three-flag scene generator remains the battle
scene source for training/base modes. The `assaultMap` XML names are original
town-menu map resources, not a promise that battle RNG chooses the same map.

## Backend hooks (`tio.world_completion`)

* `location_bounds() -> {int: (x1,y1,x2,y2)}`: merge into `locations.TOWNS`;
  `extra_cities() -> {4: City,18: City}`: merge into `cities.CITIES`. Rebuild
  `BASE_LOCATIONS` as appropriate. `location(town) -> dict|None` returns a
  detached rule record with `levels`, `profile`, `carry_items`, `max_upgrade`,
  `arena`, `capture` and `prison_only`.
* `require_location(town, levels, *, training=False) -> rule dict`: validate
  admission; training accepts19–22 only. Outpost ordinary battles must remove
  all carried items on authoritative battle copies and generate crate loot.
  Outpost disables all battle rank awards, not merely the+10 kill bonus.
* `generate_world_map(town, *, seed=None, deployment_size=3, mode=0)`:
  Detroit returns existing `GeneratedMap`; Outpost delegates Military Zone;
  bases/training return existing `AssaultLayout`. Detroit modes0/7 use original
  38×38 small map; modes1/4 use original50×50 large map. Deployment1–6 per side
  uses connected source cells; original boxes, doors and collision grids are
  retained. Native ground brush6 and basename resource lookup are used.
  Custom wager `map_size` is not an argument; admission must use supported
  original sizes or route a separate supported generator.
* `city_coefficients(town, *, now=None) -> primitive dict` contains
  `version,town_id,epoch,experience,influence,profit,kill_bonus`. Factors are
  exact rational strings (`"4/5"`, `"16/5"`, etc.), suitable for journal/JSON.
* `freeze_city(db, match_id, town, *, now=None) -> coefficient dict` requires
  the caller's transaction. Call at creation/admission of each real global
  match UUID in all ordinary/team/survival/territory/training modes. A retry
  returns the first receipt; a changed town fails. The schema and receipt
  participate in rollback. `frozen_city(db, match_id)` reads that receipt after
  restart. Settlement uses `Fraction(value)` before rounding each final reward;
  never re-read wall-clock coefficients during settlement. This hook changes
  neither wager progression bans nor premium/booster/achievement rules.
* `players(db, *, sort='rating', limit=100) -> tuple[dict]` and
  `player_top100(path, *, sort='rating') -> tuple[dict]`: use all authenticated
  saved character owners, including valid account character aliases, from one
  read-only snapshot. Sorts: `rank,rating,wins,damage,experience`. Deterministic
  descending score, casefolded public name, owner key tie; maximum100. Row keys:
  `owner,name(bytes),level,soldiers,rank,rating,wins,damage,experience,place`.
  `owner` is internal routing identity; omit it from public wire data. Rank uses
  current PublicProfile calculation; rating/XP exclude dismissed soldiers;
  wager victories are excluded. Earned rating bonus comes from root helper
  `achievement_benefits.rating_bonus(db,owner)`, with optional0 fallback only
  when that module is absent. No `level rating` or new wire format is invented.

## Prison hooks and authority

All mutations require the caller's transaction; reads create no schema.
`sentence(db,account,seconds,operation) -> state` is trusted moderation only,
never an ordinary client request. It adds bounded online seconds once per
unique operation, cancels world travel, moves the saved character to town10
and retains a previous valid location for release. Before calling, the service
must authorize the moderator and leave/cancel the current battle and queues.
`prison_state(db,account) -> None|{remaining:int,town_id:int}` is a public view.

`prison_online(db,account,token, *, now=None,active=True) -> state` is called by
the authenticated session heartbeat (≤60s) and disconnect (`active=False`).
The caller must fence tokens against the active authenticated session. Only
same-session intervals≤60s are charged; reconnect, long gaps and backward
clock changes never charge offline time. Stale disconnect cannot clear the new
session. Release restores the saved location. Persistent state survives
reconnect/restart; a reconnect starts a fresh uncharged heartbeat baseline.
`require_travel(db,account,destination=None)` blocks travel while sentenced and
unpunished entry into10. Apply the same positive-sentence guard to all battle,
queue and location-service admission paths.

## Overlay and territory integration

`config/world_completion_zones.xml` is an amendment/addition overlay, not a
standalone22-row replacement. Merge by ID into the exact published zones XML,
order records by ID and verify IDs1..22. Native F0/98 accesses ID-minus-one.
`tools/build_world_completion_overlay.py` verifies new/moved rectangles against
every source location. It writes hash/provenance evidence plus original asset
inventory `evidence/world_completion_assets.json`; no shared catalog is changed.
The inventory pins186 models, both Detroit maps, backgrounds and source files;
their textures remain in the original setting asset tree.

Enable relocated territory7 in root-owned territory configuration and replace
its disabled reason. Its levels must use the existing weekly rotating-band
policy with max upgrade3. Training19–22 uses authoritative shared real-account
assault admission and level/upgrade checks but never calls ownership/capture,
scheduled clan registration or owner prize settlement. Native menu data must
not advertise capturable training ownership. Existing territories and saved
ownership must be preserved.

## Verification and remaining release work

`python -m unittest discover -s tests -p test_world_completion.py -q` checks
130 saved accounts/top100 cap/read-only state, all five rankings, aliases/ties,
dismissal/wager exclusions, earned-rating adapter, frozen coefficients,
rollback/restart, admission, Prison session fencing/clock/gap/re-sentence and
connected Detroit maps.

`python tools/verify_world_completion_native.py` passes2 Detroit ground cases
and16 town enabled/ID gates in exact phase3 candidate DLL SHA
`2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f`.
Every visited original instruction, including helper entrypoints, is compared
byte-for-byte with original DLL SHA
`a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`.
Ground/C82D packet consumption and town gate/lookup are actual x86 execution.
Allocation, resources, strings and UI are isolated. The town XML filesystem
loader, GUI pixels, top100 request/response adapter and hosted two-client flow
are root integration/release checks; these probes do not claim them complete.
