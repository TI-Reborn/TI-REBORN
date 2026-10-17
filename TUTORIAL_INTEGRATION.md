# Introductory mission integration (phase5)

`server/tutorial_arena.py` is a mixin for the real shared `TeamArena`. Each
account owns a private introductory scene under the common authoritative hub
and `BattleJournal`; it is not a local single-player demonstration. The class
must precede `TeamArena`'s other mixins so its tutorial-only overrides apply.
Existing battles fall through to the ordinary implementations.

## Exact root hooks

1. Import `TutorialArena`; the ordinary implementation is `_SharedTeamArena`,
   and the exported wrapper is `TeamArena(TutorialArena,_SharedTeamArena)`.
   A base of a class cannot override that class’s own methods. No new
   constructor/state/snapshot allowlist entry is required: tutorial metadata
   uses only existing battle classes and primitive dicts/sets.
2. The hub requires `journal = BattleJournal(hub,server_database)` and its
   normal startup recovery. At the trusted NEW character creation boundary,
   apply `deploy/tutorial_character_creation.patch`: `create()` uses the
   enclosing `transaction(self.path)` and calls
   `onboarding.initialize_created(self.path,owner)` immediately after inserting
   the new `characters` row for native male/female types1/2. Diagnostic type0
   retains its earlier behavior. The helper initializes main actor/wallet and calls
   the existing `grant_starters(...,created=True)` exactly once, issuing IDs2/3,
   two random humans, empty inventories and durable tutorial state. All writes
   roll back with the character insert. It also creates the pending appearance
   row so initializing the roster early cannot accidentally skip that editor.
   Constructor/login/`prepare()`/resume/migration never invoke this helper.
3. After selecting the character and finishing appearance, use the existing
   reconnect check first. If `hub.resume(session)` returned false, call
   `hub.tutorial_auto(session) -> bool` before entering the ordinary city loop.
   It returns false for existing saves without tutorial state, completed
   missions and pending appearance. It starts a fresh incomplete mission via
   `journal.birth`, queues native scene packets, and returns true. Transport
   must drain the hub queue through its usual encrypted reply writer.
4. At the normal authenticated slash-command entry, route
   `hub.tutorial_command(session,text) -> bool` before rejecting slash text.
   `/tutorial` is an explicit emulator command. It continues an unfinished
   fresh mission with verified facts retained; completed/legacy saves get a
   temporary replay without resetting earned progress or receiving starters.
   It returns false for other commands and raises a normal readable `ValueError`
   if the account is busy, has an existing durable scene or cannot be admitted.

`start_tutorial(session,*,replay=False) -> battle dict` is the direct trusted
service hook. No invented original intro request opcode is registered. A valid
main human actor must exist and pass existing full-health scene admission.
No other player's save or login key can supply the private scene.

## Real actions, durable progress and exit

The scene emits existing settings6C, members25, arranged order, ground35,
soldiers3B, private inventory30, skills/status, fog, load marker41 and battle
chat22. The player acknowledges with36, uses movement3C, shooting49 and
end-turn3A, and leaves with2A01. Common authoritative validation, AP, weapon
accuracy/RNG, damage, native event projection and account visibility apply.
Rejected/foreign actions do not count. A kill is observed only on the target's
actual positive-HP-to-zero transition, not from a client claim.

The existing `tutorial_begin/progress/leave` hooks store four verified events
`move,attack,end_turn,enemy_killed` inside the same journal transaction as each
accepted scene mutation. A critical early kill retains the unfinished movement
and explicit end-turn lessons; expiring a turn does not pretend the player
pressed End Turn. A closed incomplete attempt preserves facts. If its target
was actually killed, continuation reconstructs that completed lesson as a dead
target rather than granting another fabricated kill. The original in-progress
scene, RNG, inventory, deadline and position survive reconnect/process restart.

Completion emits native4C with zero credits/rental tax/XP records, then the
normal Finish/2A01 returns to the current town. Temporary practice equipment,
wounds, skill deltas, XP, ranks and statistics never write to owned profiles.
Tutorial scenes clear `combat.persistence` and bypass ordinary settlement,
including shutdown/expiry/quarantine fallbacks; no battle reward row is minted.
Early leave, loading timeout and expired disconnect release only the tutorial
binding. Other accounts continue independently.

## Source, policy and checks

The manual printed7/9/42 requires two random starters and a short first
training mission. Original `base/maps/tutorial.s` is48×48 with27 model entries,
one box and three native doors. `tools/build_tutorial_map.py` imports the exact
source hash into `config/tutorial_map.json` and records provenance. Original
`base/quest/tut_1000.xml` contains the historic instruction text for movement,
boxes, shooting, vision, grenade, scope and end turn. Its ACK dialogue network
trigger is not reconstructed. This bounded short four-event introduction,
temporary Beretta301/ammo3, stationary10HP target, connected placement and60s
turns are explicit `config/tutorial.json` policy. Hints use the known native
battle-chat reader; there is no claim of the complete historical quest script.

`tests/test_shared_tutorial.py` passes14 focused tests: fresh atomic creation
and rollback, exactly two starters/retry, no existing-save backfill, two actual
account rows with separate scenes, native actions/completion, early kill/leave,
foreign request rejection, same-match restart/reconnect, shutdown/expiry,
explicit legacy replay, appearance gate, checkpoint-birth/action/DB rollback
and continuation of an already verified early kill. Tests execute
the real common hub, field and journal; they do not claim GUI or hosted QA.

`tools/verify_tutorial_native.py` executes9 bounded cases in the exact phase3
candidate DLL (`2c472913b2f1e9f5171b89518cba692b624d1d194c70024999baf3024da9794f`):
original tutorial ground reader, five UTF16 hints, native attack/endturn request
writers and zero-reward4C result. Every visited original instruction is checked
against the pinned original DLL. Allocation, UI and transport are isolated.
The ordinary movement ABI is already established by the existing native3C/3D
probes. No GUI acceptance is claimed. Root integrates and tests real hosting
clients after phase4; this package does not alter VPS or live player data.

Adding tutorial JSON changes the existing all-config snapshot rules digest;
root should use its controlled release/checkpoint plan and immutable test tree.
The CharacterStore diff remains unapplied until root's phase4 release gate.
