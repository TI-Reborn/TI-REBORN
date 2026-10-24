# AWP sniper scope

Current scope area: [3x3 including diagonals, without beige markers](SCOPE_SQUARE.md),
as requested by the user after the initial five-cell implementation.

Fog rendering and the missing native kneeling acknowledgement are fixed in
[launcher0.1.16 and the hosted scope update](SCOPE_FOG_FIX.md), with actual
graphical PvP verification of the revealed enemy and turn-end refog.

Released on hosting on 2026-10-19. Gameplay/server catalog release
`2026.10.19.3`; missing tooltip labels published in `2026.10.19.4`.

## Sources and behavior

- [Manual, printed p40 and p59](https://ti.ggeek.ru/files/TIO_manual.pdf):
  AWP range18, sniper scope costs3AP, primary slot required, select an area
  and shoot an enemy found there. The manual also names HK G3SG/1 and SVD.
- Original silver.dll SHA256
  `a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11`:
  selector8b6335 reads the equipped weapon's minRange/maxRange, not actor
  sight. AWP therefore selects centers at rounded distances7..18; HK313
  uses7..16. Native target_riflescope is enum5 and sends skill9 in opcode81.
- [Illustrated eyewitness guide, 24 March2011](https://totalinfluence.webnode.cz/news/pouziti-optickeho-zamerovace/):
  center plus four orthogonal neighbors, three weapon wear units, clear sight
  to the selected center. Radius is1; diagonals stay hidden. This area size
  and wear detail are not specified in the manual excerpt.

The authoritative server validates the turn, selected actor, living owner,
primary rifle, working weapon, map, LOS/smoke, range and AP. Scope consumes3AP
and3 wear before premium wear reduction, with no ammunition use. Each selected
area shares temporary recon with allies and expires at the owner's turn end,
using the existing binocular lifetime policy. Repeated uses can add separate
areas. The center must be in range; an adjacent revealed cell can lie one cell
beyond maximum shooting range, without extending the rifle's shot range.

`tio/sniper_scope.py` owns the action. `weapon_effects.battle_skills` supplies
skill9 from primary equipment, rather than recording a learned perk. SVD had
no weapon definition in this release. The subsequent [SVD/HK release](SNIPER_RIFLES.md)
adds an explicit SVD catalog extension and checks both rifles separately.
Steyr AUG is not substituted for SVD.

## Verification

Evidence is in [reports/awp-scope-20261019](reports/awp-scope-20261019).

- `remote-checks.json`:65 tests against an isolated copy of the freshly
  inspected hosting runtime, including new scope tests, item effects,
  visibility, event projection and XML generation. A pre-existing unrelated
  catalog-extension fixture expected12 nodes against the hosted11; that one
  fixture assertion is excluded from the65 passing tests and was not changed.
- `native-regression.json`: original x86 XML loader, scope selector and packet
  serializer, seven AP/range cases. DOM, actor selection, distance math and
  rendering are explicit stubs; this is separate from graphical validation.
- `hosted-two-account.json`: two excluded accounts, shared PvP, no bots. Both
  revealed a previously hidden enemy at18, received native3B, then shot AWP
  for102/62 damage. Scope cost3AP/3wear/zero bullets; shot9AP/one bullet.
  Range19 and the other owner's action were rejected without resource changes.
  Recon was private to the proper side and survived checkpoint decode.
- `gui-state-after-scope.json`, `gui-guards.jsonl`, `scope-used.png`: original
  graphical client selected scope9 and sent the request for(22,17) from(18,2).
  Hosted AP12->9, wear285->282, bullets599 unchanged; five recon cells added.
  Earlier invalid clicks were outside the playable grid. No GUI enemy shot is
  claimed; that sequence is covered by the two protocol clients above.
- `scope-button.png`: actual lower-right button tooltip now reads
  `Снайперский прицел (3 ap)`, `Цель: местность`.
- `labels-https-verification.json`: trusted HTTPS verifies the final manifest
  and all three language blobs. Only missing p09n labels were appended.

## Deployment and cleanup

`deployment.json`: scoped server update with DB and previous code/config
backups at `/root/tio-before-game-operations-awp-scope-20261019`, clean restart,
all171 database tables identical during replacement, service active. No local
player data was uploaded or any DB restored. Separate catalog and label
publication receipts contain their backups and unchanged service identity.

`fixture-cleanup.json`: both reserved QA accounts and their five match records
removed; unrelated rows unchanged by cleanup. `final-health-and-data-audit.json`
confirms21 accounts,4 clans, no retained battles, active service and DB integrity.
The full QA window crossed a pause with ordinary hosted gameplay; existing
player inventories/wallets/clan state changed during that interval and were
preserved, so the entire window's player fingerprint is not asserted identical.
