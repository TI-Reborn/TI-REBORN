# Turn timer handoff — 2026-09-29

## Cause and runtime change

`encode_turn_now` sent bare `1B owner:u32 seconds:u32`. `1B` is an internal
message type, not this message's wire opcode. The original silver.dll classifier
at 65D034 ignores bare1B; C8/17 selects the type stored at ACD15C (initialized
to1B by AB75A0). The classifier leaves the cursor after both header bytes;
65D83C forwards that body to registered readers. Reader630BD8 consumes owner
and seconds. Callback95E170 updates the current owner at *AC5CD4.

The name renderer9576A8 compares each member ID against *AC5CD4 at9579AC;
only that row can render the timer. TurnFinished95E270 disables input but
retains this owner, so the ignored old packet left the countdown at the previous
player's name. Runtime change: emit C8/17 + the same two little-endian u32 values.
All shared modes, bot notifications and reconnect paths reuse this encoder.
No client DLL/update manifest changes are required.

## Verification

- `tools/verify_turn_now_native.py`: original SHA-guarded x86 classifier rejects
  old packet, accepts the new packet and advances exactly two bytes. Original
  reader consumes the body, original finish/TurnNow callbacks retain disabled
  input and change owner. Original renderer comparison admits the next owner's
  row and rejects the old row. Human, bot and ignored own-owner cases checked.
  UI allocation/audio/timer-setup calls isolated; no graphical client test.
- `evidence/turn_now_native.json`: native results and DLL SHA.
- `reports/turn-timer/tests.log`: 46 passing tests covering packet encoding,
  shared battles, timeout, foreign-turn restoration and persistence/recovery.
- `reports/turn-timer/battle-core-tests.log`: 10 passing battle-core tests,
  including encrypted TCP reconnect and saved state/deadline preservation.
- `tools/verify_turn_finish_native.py`: original finish/AP handling passes.
- `tools/verify_hosted_turn_timer.py`: two fresh independent hosted accounts;
  checks actual C8/17 packets against member IDs in Team and Wall, skips both
  human turns, observes each bot and starts the next round. This is encrypted
  TCP protocol verification, not validation with two graphical game clients.

## Deployment

Installed only `tio/protocol/battle_turn.py` after checking the remote hash and
absence of connected players. Backup of hosted DB, previous code/config/unit:
`/root/tio-before-turn-timer-2eh7m53s`.
`reports/turn-timer/deployment.json`: service active, all42 existing tables
unchanged during installation. No local database was uploaded.
After SHA:371042a12fecc7326523790c1e7797deeccd2ffa9b3b077e4f776f402482b522.

An initial hosted check reached both human handoffs, but its bot assertion
collapsed identical AI bot display names into one dictionary entry. The probe
now keeps distinct IDs. A subsequent SSH attempt timed out before account
creation; connectivity returned, without any configuration change.

Hosted verification completed successfully with accounts qzb06b8ddca/b:
`evidence/hosted-turn-timer-qzb06b8ddc.json`. Both Team and Wall delivered
correct human timer IDs, all bot timer IDs and the next human round.
`reports/turn-timer/hosted-integrity.json`: all1686 pre-existing gameplay rows
preserved across41 tables (plus monotonic SQLite sequence checked separately),
SQLite integrity ok, deployed SHA matches, both services active, zero restarts.
Four fresh QA accounts were added across the two gameplay test attempts.
Visual confirmation by the user with two game clients remains outstanding.
