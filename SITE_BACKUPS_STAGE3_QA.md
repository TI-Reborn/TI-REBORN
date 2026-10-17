# Stage3 website and backup acceptance

**2026-10-07 update, 19:52 UTC:** The current portal is
`tireborn-20261007-8-launcher014`, with launcher **0.1.4** and EN/RU replacement
instructions. [Fresh public checks](reports/login-incident/launcher-014-portal-hosted.json)
passed **32/32**; [both full HTTPS downloads and page metadata](reports/login-incident/launcher-014-guide-public-https.json)
match the reviewed launcher. The separate login incident is resolved: both users
confirmed receiving the server list after replacing their launchers. See
[launcher acceptance](LAUNCHER_014_QA.md) for the distinction between that manual
confirmation and automated native authentication.

The new [encrypted capture](reports/site-backups/offsite-capture-launcher014.json)
and [independent verification](reports/site-backups/offsite-verified-launcher014.json)
passed: **638,039,874 encrypted bytes**, **15,432 files**, **179 game accounts**,
SQLite integrity `ok`, and **8 PostgreSQL tables / 32 rows**. The capture performed
its own full isolated PostgreSQL restore; independent local verification checked
every member, both 0.1.4 download hashes, the unchanged client manifest and the
exact release8 build ID. No local plaintext was written. Bundle SHA256:
`da3c2d59a85f923bc714fc167828a431f64441548dca7d295948e083cdab377f`.
[Final read-only status](reports/site-backups/launcher014-final-status.json)
confirms game PID **395798** and API PID **330389** were preserved; only the portal
restarted, now PID **399953**. Both backup timers remain active/Persistent,
both backup services retain success/status0, and scratch database count is **0**.
The earlier v2 copy and scheduled-task skip proof below are preserved as history.
This fresh copy was an explicit manual capture; no extra scheduled task or VPS
backup job was run. SMTP/provider/Windows-profile limitations remain as documented.

Initial acceptance was on **2026-10-07**, with read-only audit at **19:06–19:09 UTC**.
Machine-readable acceptance: [stage3-acceptance.json](reports/site-backups/stage3-acceptance.json).
The original Stage3 website and backup evidence follows; its separate native
login investigation is superseded by the later launcher acceptance linked above.

## Website evidence

The deployed portal is `/opt/tio-portal/releases/tireborn-20261007-7-stage3`.
[Trusted public HTTPS checks](reports/site-backups/hosted-after.json) passed
**32/32**, covering EN/RU routes, localized errors/news, locale routing,
CSRF/origin enforcement and public status/download metadata. They created no
hosted fixtures. [Website tests](reports/site-backups/website-tests.json) passed
**46/46** against a temporary isolated PostgreSQL database: the live database
and production game API were not selected, and the temporary database was removed.
These are automated checks; this Stage3 acceptance does not add native gameplay
or current login validation.

## Database recovery and full external copy

The installed backup tools publish only after validation and preserve manual
rollback snapshots. The optional `pyproject.toml` packaging metadata is captured
when present; the hosted runtime's `requirements.txt` remains required.
[Installation](reports/site-backups/backup-tools-deployment.json) and the
[targeted metadata correction](reports/site-backups/offsite-metadata-deployment.json)
preserved the running game PID **395798** and portal PID **394710**.

[Actual PostgreSQL16 restore](reports/site-backups/actual-postgres-restore.json)
restored a private existing dump into an owned random scratch database, counted
**8 tables / 32 rows**, removed the scratch and retained the source dump hash.
The live database was never a restore target. The full offsite capture also
performed its own isolated PostgreSQL restore before streaming its archive.

[Full platform capture](reports/site-backups/offsite-capture-v2.json) and
[independent verification](reports/site-backups/offsite-verified.json) agree:
**589,897,394 encrypted bytes**, **15,431 files**, **179 game accounts**,
SQLite integrity `ok`, and the same PostgreSQL aggregate counts. Verification
restored SQLite in memory and checked every archived member's checksum plus
the protected remote PostgreSQL restore receipt. Bundle SHA256:
`03619a0d9d66b0d135f61d972a56f33210d6c9bed6aa936eab225b686536f02c`.

The private Windows CurrentUser DPAPI copy includes game and website recovery
images, current code/runtime dependencies, operational config and TLS assets,
service units, and the current launcher/client manifest with only referenced
update blobs. It is an application recovery bundle; database images are separate
consistent snapshots rather than one cross-database transaction. Recovery
instructions and retention rules are in [deploy/BACKUPS.md](deploy/BACKUPS.md).

## Observed backup operation

[Final VPS read-back](reports/site-backups/backup-final-status.json) confirmed:

- Both backup services have `Result=success` / status 0. Their inactive state is
  the expected state after successful oneshot completion.
- Both daily timers are active with `Persistent=yes`. Next SQLite run is
  2026-10-08 03:02:34 UTC; next PostgreSQL run is 03:31:52 UTC.
- Latest verified daily files are 1,449,984 bytes for SQLite and 33,483 bytes for
  PostgreSQL, both mode 0600. Daily retention is 14 days; manual/pre-release names
  are preserved.
- No `tiobackupcheck_<UUID>` database remains. Game/portal PIDs are unchanged;
  the game service restart count is 0.

[Windows task read-back](reports/site-backups/windows-final-status.json) confirmed
`TIO-Offsite-Backup` is Ready, last result 0 at 2026-10-07 21:58:21+03:00,
with daily and current-user logon triggers, `StartWhenAvailable`, `IgnoreNew`,
and an Interactive/Limited principal matching the current user's canonical SID.
Its observed operation verified the same existing platform copy and returned
`skipped`; no second copy was created. The status record's `last_success_utc`
is null because this task invocation did not perform a fresh capture.

The next daily trigger is 2026-10-08 06:45+03:00. The accepted 24-hour eligibility
gate can skip that trigger when a verified copy is younger than 24 hours; normal
spacing while this computer is available is 24–48 hours. External retention is 31
days and the backup folder has a protected ACL. This audit did not run a backup,
restore, task, gameplay restart or remote configuration change.

## Practical limits

- SMTP delivery, email verification and self-service email password reset remain
  unimplemented; the website explicitly reports unavailability.
- Optional Turnstile remains disabled until real provider keys are configured.
  Provider fixture tests do not establish live provider integration.
- The encrypted archive requires this Windows profile and its DPAPI keys.
  Scheduled operation requires the selected computer and interactive user to be
  available. Preserve that profile for recovery.

The earlier [website deployment report](web/docs/DEPLOYMENT_RESULT.md) and
[security review](web/docs/SECURITY_REVIEW.md) retain their historical content.
Their offsite-unconfigured statements are superseded by this acceptance. The
security review's pre-TLS gameplay statement is superseded by the earlier
[game TLS acceptance](reports/game-tls/acceptance.json); this Stage3 audit did not
repeat that gameplay acceptance. The later launcher acceptance above records the
native login correction and manual confirmation separately.
