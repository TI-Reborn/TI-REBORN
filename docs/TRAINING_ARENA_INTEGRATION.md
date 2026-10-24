# Noncapturable Assault4 training

**2026-10-18:** production now uses permanent registration and starts when two
ready four-owner groups queue. The native client fixes, hosted eight-account
acceptance and deployment evidence are documented in
[TRAINING_BASE_20261018.md](TRAINING_BASE_20261018.md). Historical schedule-mode
details below remain available through `init_training(schedule='scheduled')`.

The original scoped package added `server/training_arena.py` and focused tests;
root has since installed its integration in the shared27-file phase8 runtime.
This does not claim original-client graphical acceptance.
The candidate consumes world training towns19–22 and the existing Assault4 rules,
not a bot demonstration. Two native groups of four distinct authenticated saved
owners are required; each owner selects1–3 fully healthy fighters in the town's
level range, with equipped enhancement no greater than its configured cap.

Current integration status: the installed phase8 runtime places TrainingArena
before the ordinary hub, initializes it before journal recovery, projects
authenticated native TownInfo at arrival, and applies common frozen-coefficient
SQL settlement/reconnect. The final242 local and242 remote-isolated phase8
checks and actual deployment passed on2026-10-08; see
`reports/gameplay-completion/stage8-world/validation.json` and `deployment.json`.
On 2026-10-18 the positive hosted eight-owner protocol scenario passed. A native
graphical client also created a group, readied and started a shared battle,
rendered the Assault4 field and the eight-owner result screen. Its seven peers
were TLS protocol clients, not seven additional graphical clients.

## Root wiring

1. Put `TrainingArena` before the current `TeamArena` bases in the MRO, equivalent
   to the test harness `class TrainingHub(TrainingArena,TeamArena): pass`. Call
   `hub.init_training(shared_path,wall=authoritative_wall_clock)` before journal
   recovery; it does not create/alter player or territory tables.
2. Existing `TeamArena.handle()` already invokes `self.handle_assault()`. The
   mixin intercepts original C8/1D–23 only while the authenticated account is at
   a training town. Other towns delegate to the existing assault service.
   Existing native create/join/select/ready/start/disband/list packet formats are
   reused. Group capacity is4, existing room list carries that capacity, and a
   real second ready group is required; no bot fallback exists.
3. Use `hub.training_town_packet(town)` instead of the generic TownInfo for
   authenticated arrival/current-town projection in19–22. This attaches native
   Assault4ZoneInfo (seventh optional branch), exact level/enhancement bands,
   current registration/tour/pause schedule and no clan owner. `REQUEST_ROOMS`
   also emits this packet. Training ticks push it to online idle accounts only
   when the event/phase/cutoff changes. Root owns the world XML/background publication and
   actual menu/admission delivery hook.
4. Root's common journal birth hook calls
   **`server.world_runtime.admit(db,battle,now=authoritative_utc)`** immediately
   after the factory returns and before the durable snapshot/queued replies are
   published. It uses `battle['match_id']` (native global UUID),
   `battle['city_id']`, freezes `battle['city_coefficients']` and sets the common
   Combat kill bonus. This module does not duplicate that receipt or manufacture
   a second policy snapshot. Pass all admitted roster levels through the same
   canonical rank/context rules. The scene factory passes trusted
   `prepare(...profile='assault',arena_map=layout.arena,selected_ids=True,town_id=town)`;
   the released team_scene branch validates `require_location(...,training=True)`
   while ordinary arena admission still rejects training/base towns.
5. Root settlement must recognize **`kind='training'`** as ordinary observed PvP:
   actual `reward_roster`, opponent identities, damage/kill/support activity,
   health, XP/rank, anti-repeat factors and premium effects. Apply root's frozen
   city factors through its common reward path. The candidate delegates existing
   `prepare_settlements()`/`settle()` without synthetic XP or fixed credit grants.
   Current unextended policy fallback is XP1/influence1/profit1/kill0; do not
   silently assert4/10 unless the root policy explicitly defines them.
6. `tick`, `tick_battle`, `perform_action`, `finish`, `assault_packets`, `busy`,
   and `disconnect` are mixin overrides. Nontraining branches call `super()`.
   Training capture/ticks/final settlement explicitly use `journal.unit()`;
   inherited wrappers alone would not cover overridden post-action capture.
   `assault_packets` is already called by the common native reconnect scene.
   No snapshot registry extension is needed: only existing Combat/BattleField/
   AssaultPoints objects and primitive training metadata are added.

## Tour and battlefield distinction

`AssaultMapLoader.rules` uses validated `config/territories.json`: registration
1800seconds, three tours of1800seconds separated by300second pauses for ordinary
territories and optional legacy scheduled training. Default training now uses
`schedule='on_demand'`: registration remains open, `ends=phase_ends=0`, and two
queued ready groups immediately create a match with its own900second deadline.
The first group waits for real opponents. Groups must form and confirm readiness
again after a completed battle. The exact original historical training timetable
is unknown; this permanent availability is the user's approved emulator policy.
Old2008–2011
five-flag/reserve rules are not mixed with the installed Assault4 client.

`battle['training_event']` freezes the event ID, town, UTC window, rules,
phase/tour and cutoff. `assault_round_seen` and `AssaultPoints.advance` use the
existing rule: score4/10/18 once per complete cycle of living owners, not per
action, player, keepalive or tour. Original C8/38 counts the current paired
**battle** (`total=1,completed=0`); it does not reinterpret three event tours as
three remaining battles. Native ZoneInfo phases2/4/6 carry the tour progression.

## Original resources and persistence

`AssaultMapLoader.overview(town)` returns
`dict(asset='assault\\mo.xml'|'assault\\denver.xml',background='mo'|'denver',
kind='strategic_overview')` from the world record. Original XML has sixteen Base
rows, a16×16 strategic board, background texture and attack/defence arrows.
Those files are not native combat Ground maps. `load(town,seed=...)` returns
`(AssaultLayout,overview)` using existing `assault_map.generate` and its five
verified original `assault_map_01..05` scenes, each55×33 with three authored
flags. Sharing that five-map pool across backgrounds is explicit server choice;
no historical background-to-battle-map distribution is claimed.

Uncharged waiting groups are process-local, like ordinary TeamLobbies. Disconnect
releases them and readiness; restart clears them with no economic refund needed.
Active fields, original gear consumption, wounds, RNG, flags, score cycle,
native owner IDs, actual tour/deadline and settlement outbox use existing durable
checkpoints. `recover_training_events()` reconstructs still-active schedule
windows from recovered training battles; `tick_training_events()` calls it.

There are no `TerritoriesStore` instances, claim writes, warfare match binding,
OV, `warfare_scores`, weekly medal/top20 receipts, capture/defence achievement
hooks, or capture influence awards. Final native C8/32 reports real kills/deaths
and flag scores but clan/assault award points are0. Ordinary PvP reward policy
remains the root settlement's responsibility. Empty/incomplete loading returns
every participant without settling a battle or inventing progression.

## Verification

Focused tests run a candidate mixin against the real TeamArena, shared journal,
eight saved SQLite characters and native room/loading/move/attack/end-turn
requests. They verify authoritative sharing, three actual UTC tours/pauses,
whole-map selection, score clock, no bot fallback, actual band/health/upgrade
rejection, loading cancellation, exactly-once ordinary settlement, native
confirmed-kill XP/rank audits, no territory/weekly writes, crash/reconnect flags,
birth failure rollback, post-action rollback, native phase notifications and
idle-write suppression with journaled tour/tactical-mark cutoffs. These are automated protocol/core checks, not eight human
game clients or GUI validation.
