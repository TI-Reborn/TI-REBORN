# Corpse visibility and mine owner status — 2026-09-28

## Follow-up: preserve the completed death pose

The user confirmed that the HP1/HP0 recreation replays the fall on fog return.
VisibilityView now retains already displayed corpses as stationary scene objects,
independently of the current LOS set. It no longer sends43, an off-map3B, a new3B,
or another death transition for those corpses when sight is lost and regained.
This preserves the original client's actual completed pose and chosen death
variant rather than attempting to reconstruct it. Template refreshes also skip
resident corpses. Movement projection copies the per-view corpse set.

Retention is per observer, does not grant sight, and does not disclose unseen
corpses or hidden living enemies. These are remembered scene objects, not actors
currently in LOS. The change does not add a protocol command to seek an animation:
a corpse discovered for the first time still uses the one-time HP transition.

Validation: 626 automated tests pass, including three fog cycles without corpse
reset packets, independent viewer discovery, movement projection, living-enemy
visibility and the last-enemy owner status. Actual graphical fog rendering still
requires validation in the original client.

Deployed follow-up to hosting: backup `/root/tio-before-corpse-pose-jaeqh4_2`;
all35 existing database tables unchanged during deployment, service active.
Three battle-event regression tests also pass against the deployed modules.
Public encrypted TCP verification with two fresh accounts passed mine entry,
masked enemy registration and first turns:
`evidence/hosted-corpse-visibility-qv29d17a81.json`. This checks networking and
server behavior, not the graphical client's final image.

The following sections describe the initial fix and its deployment history.

## Report and root causes

User reported dead Sick Miners standing again after leaving/re-entering fog, and Enemy 1 crossed out while other miners remained alive underground.

Original pinned silver.dll SHA256 a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11:

- BattleSoldierAdd3B reader 8C5044 writes HP at 8C57C3, but its scene tail unconditionally requests idle via A84704 at 8C5F4A. An HP-zero snapshot alone does not restore the death animation.
- Status4E/attribute4 updates HP at 8C75B2, compares the signed HP delta, invokes DeathAnimation A86CD8 at 8C7639 for a decrease to zero, and clears actor+40 at 8C769C.
- Owner-eliminated predicate 9C04BC scans the 31 actor slots: matching owner, positive HP and removed flag+20==0. It does not consult battle-member squad sizes. The kill handler calls this predicate at 960FAC and emits nn13 at 960FDA. Thus enemies never sent to the client, or hidden using43, do not prevent premature elimination.
- Remove43 sets removed=1 and position255/255. Add3B clears removed at8C50DD and accepts byte coordinates255/255; the scene setup has explicit absent-position guards.

## Change

VisibilityView.snapshot_packets emits a transient model-only HP1 snapshot followed immediately by native4E HP0 for a dead actor. This routes model recreation through the original death handler. Authoritative HP remains zero; no attack, extra damage, kill, XP or reward is generated. This can replay the native fall animation on rediscovery; it does not claim to seek directly to its final frame.

Mine mode7 registers hidden enemies at native absent-position255/255 with HP represented only by an alive bit. Hidden movement and damage do not produce snapshots while that bit is unchanged. Revealing sends the current real model; hiding first removes its scene representation then registers its off-map state. All ten NPCs fit the original 31-slot limit along with the player's squad. This is scoped to underground mode, leaving PvP information rules unchanged.

Shared battle snapshot emission uses the same death transition. Movement projection copies per-view hidden registration state alongside visibility/doors.

## Validation and deployment

- `python -m unittest discover -s tests`: 624 tests pass, including three fog return cycles for a dead miner, no hidden route/HP disclosure, and elimination only after the last of ten hidden miners dies.
- `python tools/verify_corpse_visibility_native.py`: six original-binary cases pass: zero-to-zero versus one-to-zero HP callbacks, absent-position snapshot decoding, and three real owner-elimination predicate executions. Rendering/audio callbacks are isolated, so this is not a graphical-client check.
- `python tools/verify_hosted_corpse_visibility.py 185.184.42.88`: two newly created QA accounts authenticate and independently enter hosted mines, both receive ten masked NPC records and begin their turns. `evidence/hosted-corpse-visibility-qva8accb6f.json` reports passed=true. Only these fresh QA squads were prepared for level4/checkpoint13.
- Deployed four runtime files after the user disconnected; backup `/root/tio-before-corpse-visibility-4x4re5md` contains DB/code/config. Deployment verifies before/after hashes and all35 existing table contents unchanged.
- Post-check: service active, SQLite integrity_check=ok, all pre-existing accounts/owned_pets/wallets retained. `evidence/corpse-hosted-integrity.json`.

Graphical revalidation in the original game remains unperformed: check killing a miner, leaving and re-entering its fog region, and retaining Enemy 1 until the final enemy dies.
