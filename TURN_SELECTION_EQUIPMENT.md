# First squad member on turn start and battle equipment audit

Launcher0.1.15 extends the pinned original ti.exe YourTurn event38. Once the
native handler has enabled the turn, its exit trampoline scans the31 actor
slots in roster order, matches the local owner, decodes HP using the native key,
and invokes the original selection routine706564 for the first living member.
That routine clears earlier selection, selects the member, updates the camera
and recalculates native highlights. Further manual selection stays available.
Enemy-turn and turn-finished branches are unchanged. The adapter sends no
movement/action packets, charges no AP and changes no authoritative game state.

Sources: `launcher/NativeBattleTurn.cs`, `tools/build_native_battle_turn.py`,
embedded `launcher/Assets/native-battle-turn.json`; installed alongside the
existing door adapter before the game's main thread runs. Original client
files are preserved; unsupported ti.exe images fail the existing SHA pin.

## Equipment behavior

The inspected hosting equipment modules, including the actual hosted combat
and shared-battle runtime, were copied into an isolated validation directory.
All47 equipment/integration checks pass there and locally. New regressions
cover replacement of primary weapon, helmet, chest and legs while retaining
all other equipped items and opaque item metadata; explicit placement of
already equipped items; Tank Armor conflicts; atomic rejection and restoration.
No arbitrary removal was reproduced in these checks.

Replacing an occupied slot returns the old item to the backpack. Tank Armor
covers head/chest/legs and therefore replaces those three pieces, retaining
both weapons. Equipping a separate armor piece that overlaps that whole suit
removes the suit; it does not independently restore the three old pieces.
Untargeted double-click/use is an explicit toggle: invoking it on an equipped
item removes that item. Dragging to an explicit valid slot is idempotent.
These rules were not changed during this audit.

2026-11-13: an untargeted click on a bag weapon fills a free hand, primary
first, then secondary; it replaces the primary weapon only when both hands are
occupied. One rule (`tio.equipment.weapon_slot`) serves city equipment and
both battle routes (staged F6 and direct action33). Dragging an equipped
weapon onto the other occupied hand exchanges the two weapons
(`tio.equipment.vacated_hand`); only a weapon brought from the bag sends the
displaced one back to the bag.

In battle, selections are private previews until confirmation. A changed actor
costs2AP per confirmed batch; no-op explicit rewear and duplicate confirmation
do not charge again. Cancel, invalid actions, turn end and reconnect restore
the authoritative outfit. No production server code or player data is replaced
for this launcher feature and audit.

## Evidence and limits

`reports/turn-selection-equipment-20261019/`:

- `native-turn-selection.json`: exact compiled C# payload at a relocated
  allocation, original native YourTurn branch, clear/select routine and later
  selected-actor getter.21 cases cover first/second/last slot, dead first actor,
  foreign actors, previous manual selection, empty roster and three HP keys.
  Stack and saved registers, HP, coordinates and ownership are preserved.
- `native-startup.json`: a separate owned original client loads both selection
  and door adapters and verifies the TLS route. No account login in this probe.
- `launcher-native-doors.json`: prior door collision/surface behavior remains
  valid; original sight and click-distance checks pass.
- `local-equipment-tests.log`, `remote-equipment-checks.json`:47 tests;
  validation uses temporary databases, not hosted player records.
- `launcher-self-test.json`, `launcher-tls-test.json`: install/repair/recovery
  and TLS regression groups pass.
- `hosted-equipment-two-account.json`: two excluded random QA accounts, no
  bots, public TLS and a shared authoritative battle. Each replaced primary
  weapon, helmet/chest/legs, confirmed a no-op explicit rewear, equipped Tank
  Armor, then replaced it with a helmet. Only overlapping gear was removed;
  both hands, item metadata and the other account's bag remained correct.
  Three real changes cost6AP; repeated confirmation/no-op rewear cost0.
- The first two protocol attempts retained one completed account case but
  could not assess the second reliably: the helper treated9E as a request
  fence, while the live server also sends9E as an unsolicited heartbeat.
  The final helper drains old notifications and awaits actual inventory30
  for the requested actor. Both final account cases pass; no production
  equipment code was changed to accommodate the test.
- `fixture-cleanup.json`: final exact QA account/match cleanup preserves all
  unrelated rows and schema, all22 pre-existing accounts and4 clans. Earlier
  disposable pairs were likewise cleaned by exact ownership. Ordinary gameplay
  changed protected fingerprints during the first QA window; cleanup retained
  that current player data and did not restore a database snapshot.

Launcher0.1.15 was published with the existing guarded publisher, backed by
`/root/tio-before-launcher-dgwdsa7q` (verified SQLite, full PostgreSQL restore
check, prior code/config and public launcher). Candidate SHA256:
`98ffb5555eaf867bf681d80cfef269fd9b691d2bf23a71147b90599533854fdf`.
Publication receipts are in `publication/`. No game service restart, resource
manifest replacement, account edit or player-data upload is part of publication.

Rendering/highlight internals are isolated in the native emulator. The hidden
loader is not a graphical battle acceptance test; interactive end-to-end
selection with a logged-in graphical client is not claimed by these checks.
