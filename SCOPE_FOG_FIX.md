# Sniper scope fog and kneeling — 2026-10-19

The subsequent [3x3 scope release](SCOPE_SQUARE.md) adds diagonals, resolves
missing terrain cells and removes the legacy markers in launcher0.1.17.

Released server fix and launcher **0.1.16**. Restart the game through the updated
launcher to install the client adapter. The public client manifest stays at
2026.10.19.6; Silver/ti.exe files and player saves are unchanged.

The previous scope implementation sent the authoritative five-cell recon and
enemy3B correctly, but F7 drew markers without updating native fog. It also
omitted skill-use status0. The original 7F/01 consumer8c0790 routes status0 for
target_riflescope to ChangeState(Sit), a86a34. The original animation.xml provides
human_snip_sit, human_snip_sit_idle and human_snip_sit_fire_.

The server now acknowledges successful scope use with status0, after resource
validation/commit. Visible recipients share the use animation; cooldowns remain
private, and hidden actors never leak through this event. Existing scope AP,
wear, range, LOS, ally sharing, checkpoint and expiry rules are preserved.

The launcher extends its guarded native fog adapter to apply only server-issued
F7 kind3 cells after stock fog reset. It binds the exact SHA-pinned Silver reader
after the module actually loads. Every F7 snapshot, including empty/invalid
snapshots, triggers stock fog recalculation. This clears expired recon and keeps
active recon across ordinary visibility recalculations. Coordinates/counts and
native grid bounds are checked. Existing door handling is retained.

Verification in [reports/scope-fog-20261019](reports/scope-fog-20261019):

- `remote-checks.json`: 70 tests on an isolated copy of freshly inspected hosted
  code, including scope, statuses, visibility, item effects and event projection.
- `native-recon-and-kneeling.json`, `launcher-native-doors.json`: exact compiled
  x86 adapter, five-cell cross, hidden diagonals, snapshot expiry, unchanged door
  behavior, stack/flags and original skill-use kneeling branch. Rendering is
  isolated in these automated probes.
- `hosted-two-account.json`: two excluded accounts, authoritative PvP, no bots;
  both reveal and shoot the previously hidden enemy at range18. Scope costs3AP,
  3wear, zero bullets; invalid range/foreign owner rejected; opponent gets no
  recon. These shots use protocol clients.
- `graphical-verification.json`: original graphical client through candidate
  launcher, same hosted two-account PvP. Five native vision bytes become1,
  hidden enemy255/255 becomes14/35 and appears, own stance becomes1. Actual
  callbacks run human_snip_sit and human_snip_sit_idle. On turn expiry the enemy
  returns to255/255, recon disappears and human_snip_stand runs. No graphical
  shot is claimed.
- Screenshots: [before](reports/scope-fog-20261019/gui-before.png),
  [revealed enemy and kneeling](reports/scope-fog-20261019/gui-after.png),
  [expired](reports/scope-fog-20261019/gui-expired.png).
- `publication/https-verification.json`: full EXE verified through trusted HTTPS
  by both versioned/alias downloads, self-update manifests and public metadata.
  SHA256: ce3ec8b2422d1ca18c1802c50ca2c4bbf54bc34e039f7d5fd53a08eb8a938068.

Server backup: `/root/tio-before-game-operations-scope-fog-20261019`.
Launcher/code/config/DB backup: `/root/tio-before-launcher-oi11w247`.
Server restart occurred with no active battles; all171 tables were preserved.
Publication needed no further restart. Disposable fixtures and their matches
were removed with unrelated rows preserved. Final audit:22 accounts,4 clans,
no retained battles, DB integrity ok, active service PID197898.
