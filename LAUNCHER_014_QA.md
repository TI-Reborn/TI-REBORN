# Launcher 0.1.4 publication and login-route proof

Published on **2026-10-07 at 19:39 UTC**, with trusted public HTTPS checks at
**19:41 UTC**. Download the versioned
[TIO Launcher 0.1.4](https://ti-reborn.com/downloads/TIO-Launcher-0.1.4.exe).
Close the game and launcher before replacing the old EXE. Game-resource updates
do not update the launcher executable.

The published EXE is **118,679,712 bytes**, SHA256
`61a0d5bc78cc5a74a0f29d42d7f9c2bf49ca33b378993221a45ff9ba2084aa5f`.
The current download alias contains the same binary. The client-resource manifest
remains `2026.10.07.4`, SHA256
`2966cadc3eff333f46d944145d7a398ab5e55a4894a2ded59fd31bf86dea25d2`.

## Reason and validation scope

The original native connection adapter supplies a byte mode with unrelated upper
bits in the stack argument. Launcher 0.1.3 compared the full DWORD and could send
an ordinary mode-0 login to the session listener. The fix compares `AL` while
preserving the complete original argument passed to the original networking code.
[Original adapter proof](reports/login-incident/normal-ti-connect-offline.json)
reproduces the wrong route and validates the corrected route in isolated x86.

[Candidate checks](reports/login-incident/launcher-0.1.4-local-validation.json)
passed 60 emitted route cases, 15 bootstrap checks, 7 Windows TLS groups,
4 original-adapter cases, 5 observer-lifecycle cases and 6 updater groups.
[Two hosted native clients](reports/login-incident/launcher-0.1.4-hosted-native.json)
used the original TI adapter: both received one server, succeeded through all
five authentication stages and completed game authentication.
The clients used owned QA credentials through their dedicated heap adapter and
were closed afterward. This proves the ordinary native connection route and
game authentication. Character-list loading, character selection and native
world entry were not verified in this run.
After replacing their launchers, both users independently confirmed that the
server list appeared: «Список серверов появился у обоих». This is the manual
login acceptance for the reported hang, separate from the instrumented QA route.

## Publication safeguards and evidence

[Fresh server inspection](reports/login-incident/launcher-014-baseline.json)
confirmed the exact 0.1.3 baseline, active service PIDs and current portal release.
[Pre-update backup](reports/login-incident/launcher-014-preupdate-backup.json)
saved consistent SQLite, a full PostgreSQL dump, previous game/portal code,
configuration and TLS assets, the launcher and client manifest under private
`/root/tio-before-launcher-opefu9a1`. SQLite integrity passed. PostgreSQL was fully
restored and row-counted in an owned scratch database, which was removed; no live
database was restored.

The [reviewed package](reports/login-incident/launcher-014-publication-package/package.json)
uses a private recovery journal, an exclusive publication lock, an immutable
version path and atomic current-alias replacement. Exact whole-row SQL guards
update only `launcherVersion`, `launcherUrl`, `fileSizeBytes` and `updatedAt` in
`DownloadVersion/main`. Timeout recovery re-reads metadata because COMMIT may have
succeeded before an error. Guarded rollback checks both the binary and metadata
before changing them. Local safety checks passed **13**, with **1** skipped because
Windows symlink privileges were unavailable.

[Publication receipt](reports/login-incident/launcher-014-publication-receipt.json)
confirms the alias and immutable version share an inode. Game PID **395798**, API
PID **330389** and portal PID **394710** stayed active with zero restarts. Config,
portal release and complete client-manifest hash were preserved. No account row
was changed, no database restored and no game service restarted.

[Trusted HTTPS verification](reports/login-incident/launcher-014-public-https.json)
streamed the entire immutable binary and current alias with a cache-busting query,
matching both hashes and byte counts. No executable was saved by this verifier.
The API and both localized download pages show 0.1.4 and the immutable link. The
versioned URL avoids earlier cached responses on the current alias.

[Portal release8](reports/login-incident/launcher-014-portal-deployment.json)
publishes the EN/RU manual replacement note for existing 0.1.2 and 0.1.3 users.
Type checking, production build and 11 localization/render checks passed.
[Fresh public portal checks](reports/login-incident/launcher-014-portal-hosted.json)
passed **32/32**, with zero created fixtures. The
[final HTTPS checks](reports/login-incident/launcher-014-guide-public-https.json)
confirm both exact EXE hashes, public version/link metadata and localized notes.
[Remote read-back](reports/login-incident/launcher-014-remote-after.json)
confirms game/API PIDs and configuration/manifest hashes remain unchanged;
only the portal restarted, with new PID **399953**.

The [fresh encrypted recovery copy](reports/site-backups/offsite-capture-launcher014.json)
and [independent verification](reports/site-backups/offsite-verified-launcher014.json)
passed with **638,039,874 encrypted bytes / 15,432 files**. They retain both reviewed
0.1.4 download files, the unchanged resource manifest and the exact portal release8
build identity. SQLite restored in memory; PostgreSQL restored only in an isolated
scratch database during capture. No local plaintext was written. The
[final server status](reports/site-backups/launcher014-final-status.json) confirms
active services, persistent backup timers and zero remaining scratch databases.

Historic 0.1.3 gameplay acceptance remains in
[game TLS acceptance](reports/game-tls/acceptance.json); it does not validate the
dirty-upper-byte ordinary adapter case corrected here.
