# SVD and HK G3SG/1 scope

Deployed hosting/client release2026.10.19.5. Sources: original manual printed
p40/60 (visually checked in reports/sniper-rifles-20261019/manual-page60.png),
and the original target_riflescope selector described in AWP_SCOPE.md.

| Rifle | Scope center range | Scope AP | Shot AP | Bullets | Minimum level |
|---|---|---|---|---|---|
| AWP312 | 7..18 | 3 | 9 | 1 | 1 |
| SVD5013 | 7..15 | 3 | 9 | 1 | 5 |
| HK G3SG/1 313 | 7..16 | 3 | 10 | 3 | 1 |

Scope uses the existing radius1 cross, allied recon and current-turn lifetime.
Each use spends3 wear before premium reduction, without ammo. Only the primary
weapon grants skill9. HK's previous weapon parameters were not changed.

SVD was absent from all inspected runtime/legacy catalogs. Its model, icon and
sound already ship.5013 is an explicitly allocated emulator ID, checked unused
in server/client catalogs and owned inventories; no historical ID is claimed.
The ordinary shop sells SVD for1650 credits where the city permits level5 gear.
The native XML and generic equip rules enforce level5.

## Reconstruction limit

SVD range15, reference7, shot9AP/one7.62x51 round, accuracy90, level5 and weight200
come from manual p60. Its illustrated damage46..63/66..76 cannot be reproduced
by a single native fade factor, and the raw SVD damage record was not found.
Base55 plus random20 and AWP fade120 are an explicit compatible reconstruction;
durability300, critical5 and animation timing inherit compatible AWP defaults.
Exact historical SVD damage is not asserted. See tio/sniper_rifles.py.

## Evidence

All evidence is in reports/sniper-rifles-20261019:

- remote-checks.json:68 tests on an isolated fresh hosted runtime copy,
  including purchase, level requirement, primary/secondary eligibility,
  per-rifle boundaries, scope followed by burst, rollback and visibility.
  The same unrelated legacy catalog-extension count assertion excluded in
  AWP's checks remains excluded; it was not changed to satisfy this release.
- native-scope-regression.json:8 original x86 selector/serializer AP/range
  cases. Metadata, distance math, UI and transport are explicitly isolated.
- hosted-two-account.json: two excluded accounts in a shared PvP battle, no
  bots. SVD revealed at15 and shot for66 damage; HK revealed at16 and shot
  for73. Each next distance and the wrong owner were rejected atomically.
  Scope3AP/3wear/zero ammo; SVD shot9AP/1round, HK shot10AP/3rounds.
  Side privacy and checkpoint decode verified.
- hosted-hk-before-svd.json: HK separately verified on the previous live build.
- native-delivered-metadata.json: real client's received tables confirm
  AWP7..18/9AP/level1, HK7..16/10AP/level1, SVD7..15/9AP/level5.
- gui-svd.json, gui-svd-guards.jsonl, svd-scope-used.png: actual native SVD
  cast; AP15->12, wear288->285, ammo56 unchanged, five recon cells.
- gui-hk.json, gui-hk-state.json, hk-scope-button.png, hk-scope-used.png:
  actual HK cast; AP8->5, wear287->284, ammo54 unchanged, five cells.
  Movement preceded the scope. Enemy shots were tested by protocol clients;
  graphical evidence is button/use/cost validation.
- scope-of-changes.json: previous weapon rules, item records and ordinary
  offers are semantically identical; only the SVD record/offer was added.

## Installation and cleanup

User approved restarting immediately after the ongoing battle finished.
Installation proceeded with no retained battles and the authorized maintenance
flag for a connected city client. Backup:
/root/tio-before-game-operations-sniper-rifles-20261019 (DB and old code/config).
All171 DB tables were preserved during replacement; no local saves uploaded
and no DB restored. Publication/HTTPS receipts verify the XML-only client update.

Both owned QA accounts and their five matches were removed. Existing players
and pre-existing QA accounts were preserved. final-health.json confirms active
service, integrity, exact deployed hashes,21 accounts,4 clans, zero accounts or
checkpoint memberships belonging to this task. Ordinary gameplay continued
during QA, so the entire window's player fingerprint is not asserted identical;
cleanup itself preserved every unrelated row.
