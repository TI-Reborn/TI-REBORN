# Scope 3x3 and marker removal — 2026-10-19

The user's revised scope footprint is a square of nine map cells, including
the four diagonals. Released on hosting with launcher **0.1.17**; restart the
game through the updated launcher to remove legacy beige cell markers.

`tio/recon_geometry.py` shares footprint membership between authoritative enemy
visibility and terrain presentation. Only scope effects carry `shape='square'`;
legacy binocular footprints stay circular. Scope terrain includes obstacle
surfaces, preventing missing terrain cells. Map boundaries clip the footprint.
Actor visibility still respects the existing wall/smoke checks. AP, rifle wear,
range checks, ally sharing, kneeling and turn expiry are retained.

F7 now allows one independent RECON row alongside a smoke, light or fire row
at the same coordinates. Previously the effect's row replaced RECON, which
could leave a hole in native fog. Exact duplicate rows and conflicting terrain
effects are rejected. The native reader already supports the independent rows;
its version and bounds remain unchanged.

Launcher0.1.17 skips the exact pinned Silver RECON rectangle-draw branch with a
guarded in-memory jump. Native fog updates remain active; other effect sprites,
sounds and animation continue through their original paths. Installed game
executables and client manifest2026.10.19.6 are unchanged.

Evidence: [reports/scope-square-20261019](reports/scope-square-20261019).

- `remote-checks.json`:74 tests against an isolated copy of freshly inspected
  hosted sources, including all nine enemy positions, obstacle surfaces,
  overlapping effects, map-edge clipping, walls/smoke, expiry and checkpoints.
- `native-recon-and-kneeling.json`, `launcher-native-doors.json`: exact compiled
  launcher adapter reveals the nine cells, including a blocked surface; stock
  resets preserve active recon and clear expired recon; doors are unchanged.
- `native-marker-removal.json`: exact compiled marker jump in the original
  native renderer, tested at preferred and relocated Silver bases. Zero RECON
  rectangle draws; smoke/fire/flare/light sprites and sounds retained, including
  smoke and recon at identical coordinates.
- `hosted-two-account.json`: two ranking-excluded accounts, no bots, public TLS.
  Both reveal a previously hidden enemy in the diagonal cell and fire at it.
  Nine cells,3AP/3wear/zero scope ammunition, foreign owner and range rejection,
  checkpoint restoration and opponent recon privacy are verified. One shot
  missed under the normal combat roll; the other dealt76 damage.
- `gui-native-request.json`: graphical-client verification uses the original
  native skill9 serializer8c0730 inside the owned QA client, hosted authentication
  and authoritative action handling. This is not a mouse-click acceptance test.
  `graphical-verification.json` confirms nine native vision bytes equal1, the
  diagonal enemy at2/17, own kneeling stance1 and zero marker draws. After turn
  expiry the snapshot is empty and the enemy returns to hidden255/255.
- `publication/https-verification.json`: trusted HTTPS verifies complete launcher
  downloads, aliases, self-update manifests and public metadata. Version0.1.17,
  SHA25614be6642b477d16ca1def25b0ffae8b5c406f4fae31a9c46f2a9d60d8939ada6.

Server baseline differs from the local workspace. For battle_item_effects.py,
only the footprint condition was changed in the freshly downloaded hosted file;
unrelated local changes were not uploaded. The guarded deployer waited until the
ordinary hosted battle had ended, then backed up DB/code/config and preserved
all171 database tables. Backup:
`/root/tio-before-game-operations-scope-square-20261019`.
Launcher backup: `/root/tio-before-launcher-trm1bdwe`.

`fixture-cleanup.json` removes both excluded QA accounts and their matches;
unrelated rows are identical immediately before/after cleanup. The broad
pre-existing-player fingerprint changed during the QA window, which included
ordinary hosted gameplay; it is not claimed identical across that interval.
`final-health.json`:22 accounts,4 clans, no retained battles, no remaining owned
fixtures, DB integrity ok, active service PID205234. All five deployed hashes
match the validated candidate.
