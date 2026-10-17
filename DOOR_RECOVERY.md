# Closed-door path and reopen correction

## Recovered causes

* `ti.exe6dc9be` calls the real ownership predicate `723fa4`, which compares
  actor+64 with the local owner. The first movement reply point is skipped for
  an owned actor because the native client already predicted that step.
  The previous single-point rejection reply updated model coordinates but
  queued no correction for the rendered actor. The previous native probe
  incorrectly stubbed ownership to false and missed this case.
* Live trace `data/door-session.jsonl` showed dog4 at scene(12,20) while the
  response had restored model(19,14). This is a scene/model divergence, even
  when further movement clicks are still accepted locally.
* Native `.s` hangar door cells initially had collision1 despite closed visual
  state1. `72d79c` instead assigns closed collision3 and open collision0.
* After closing, native visibility refresh `6e40a4` excludes the opaque door
  endpoint itself. `6e45a0` returns true for an **unseen**, not visible, cell.
  `72e370` refuses reopening that door. Live inspection found closed door
  (19,15), collision3, visibility0 next to owned human(19,16).

## Changes

`tio/battle_rejection.py` returns the authoritative current position twice.
The second point reaches the original scene action queue and corrects the
predicted position; no server movement or AP charge is performed.

The launcher's `tools/battle_door_grid.js` adapter runs around the original
visibility refresh. Stable closed/open door states synchronize collision3/0
before path/visibility recalculation. After recalculation, only the surface
cell of a closed door next to a living owned actor is made visible. Diagonal
access through blocked corners remains forbidden. Cells beyond the door and
enemy positions are not exposed. Native door permissions, AP and server-side
validation remain unchanged. Deferred door states are now completed through the native stable-state path (see the hangar follow-up below).

No original client files or saved account/database contents are patched.
Restart `python tools/run_reservation.py` for both changes to apply.

## Verification

* Server suite: 402 tests, including encrypted rejected move/door replies and
  repeated open/close checks with AP accounting.
* `node tools/verify_battle_door_grid.js`: actual adapter against bounded memory;
  initial collision, three open/close cycles, no reveal behind the door,
  owner/death/distance/corner limits and pending animation states.
* `python tools/verify_dog_abilities_native.py`: original ownership predicate,
  zero/one/two-point replies for own and remote actors, original scene position
  correction from a mismatching prediction, and isolated queue completion.
  Rendering and UI callbacks remain isolated; this is not full visual QA.
* `tools/trace_door_session.py` records native door/movement states in an
  already running client; optional `--apply-grid-fix` is a temporary live
  diagnostic, not a replacement for restarting the launcher.

## Follow-up after restart

User confirmed normal dog movement and the out-of-range attack message in the current session. `data/dog-movement-session.jsonl` captures full dog4 movement request/reply paths. No further gameplay changes were made for that report. Improved the launcher movement diagnostic: it now looks up the packet actor ID rather than always printing the first squad member, and includes AP and rendered coordinates. Closed-door regression still needs the user’s visual confirmation.

## Upper hangar door stuck opening

Live inspection in process4220 found upper hangar door(23,14) in state4,
frame0, collision3, visibility0; the lower door(32,14) was state2,
frame1, collision0. State4 is a deferred open response, not an unhandled
server request. The original render path72fa32 cannot finish it while its
surface remains unseen. Click handling accepts stable states1/2 only.

The adapter now normalizes received door states3/4 to stable1/2 at the entry
of72dc90. The rest of the original handler updates sprite, sound and grid.
The crate branch (flag0) is unchanged. When attaching to an existing scene,
already pending door states and frames are recovered before grid refresh.
No timer and no AP/permission/server state changes were introduced.

Verification: adapter checks cover independent upper/lower doors, preserved
visibility boundaries and door-only receiver normalization. Four additional
native cases run3F to stable frame/collision without jumping into the render
finalizer: `python tools/verify_battle_doors_native.py` passes14 cases.
The client exited before the live patch could be attached; restart is needed
for the user to confirm the repaired upper door visually.
