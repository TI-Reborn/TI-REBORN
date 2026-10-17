# Verified backups and recovery

## Daily VPS database snapshots

The game timer runs at 03:00 UTC (up to five minutes randomized delay). SQLite's
backup API captures committed WAL data while gameplay continues. Publication is
exclusive and atomic: integrity_check must return exactly `ok` before a daily
name appears. Files are 0600 in `/var/backups/tio-server` (tio:tio, 0700).
Only strict `auto-<UTC timestamp>.sqlite3` files older than 14 days are removed,
after a new verified snapshot. Manual and `pre-update-*` copies are preserved.

The portal timer runs at 03:30 UTC (up to fifteen minutes randomized delay).
`web/deploy/portal_backup.py` creates a custom dump, reads its complete contents,
restores into a fresh `tiobackupcheck_<random UUID>` database and counts every
restored user table. It drops only the scratch database whose creation succeeded.
Only then does it publish `website-<UTC timestamp>.dump` in
`/var/backups/tio-portal` (root:root, 0700; files 0600). Strict new daily filenames
older than 14 days are rotated after success. Legacy filenames, manual dumps and
`before-release-*` dumps are preserved. A failed dump, restore, row check,
cleanup or publication cannot delete older backups. A service timeout or machine
power loss can leave a private `.pending-*` file or scratch database: investigate
its owning job before manually removing it. These are not verified snapshots.

Both systemd timers use `Persistent=true`; a missed run is performed when its
timer is active again. A oneshot service normally becomes inactive after success.
Check `Result=success`, its journal and the active timer. Journals contain phase
status and aggregate counts, never SQL rows, configuration or command stderr.
No email/Discord notification is configured.

## Install or update the backup tools

Inspect the remote baseline and preserve code/config and both current databases
before updates. Upload only the scripts and units listed here; never upload a
local player database over hosted data. These changes need no gameplay restart.
Convert uploaded shell scripts to LF and make them executable.

The reviewable package builder is local-only:

```powershell
python tools/prepare_backup_tools_deploy.py --output '<new local package directory>' --validate-dump '<existing private remote website.dump path>'
```

Its `package.json` names exactly five targets: game `deploy/backup.py` and
`deploy/recovery_bundle.py`, portal `portal_backup.py` and `backup_portal.sh`, and
`tio-portal-backup.service`. It records LF-normalized file hashes and a package
checksum. Upload the archive to its suggested private `/root` path, then pass
`inspect-remote.stdin.py` to a static SSH `/usr/bin/python3 -` command via stdin.
Review the returned baseline before separately sending `apply-remote.stdin.py`.
The helper pins PostgreSQL16 binaries and `/var/run/postgresql:5432`, checks root
Python3.10+, refuses active backup jobs or a changed baseline, saves previous
operational files in a private rollback directory and installs atomically. It
runs `daemon-reload` and checks unchanged game/portal service identities; it
does not restart services, change timers or capture a database. Partial failures
restore the previous operational files.

`validate-remote.stdin.py` is a separate explicitly invoked operation. It verifies
the installed validator hash, restores the selected existing dump into its own
isolated temporary database, counts rows, removes that database and verifies the
source dump hash is unchanged. A fresh offsite capture is still a separate command
and performs its own PostgreSQL restore check before streaming the archive.

```bash
install -d -o tio -g tio -m 0700 /var/backups/tio-server
install -d -o root -g root -m 0700 /var/backups/tio-portal
install -m 0644 /root/backup.py /opt/tio-emulator/deploy/backup.py
install -m 0644 /root/scheduled_backup.py /opt/tio-emulator/deploy/scheduled_backup.py
install -m 0644 /root/recovery_bundle.py /opt/tio-emulator/deploy/recovery_bundle.py
install -m 0644 /root/portal_backup.py /opt/tio-portal/portal_backup.py
install -m 0755 /root/backup_portal.sh /opt/tio-portal/backup_portal.sh
install -m 0644 /root/tio-backup.service /etc/systemd/system/tio-backup.service
install -m 0644 /root/tio-backup.timer /etc/systemd/system/tio-backup.timer
install -m 0644 /root/tio-portal-backup.service /etc/systemd/system/tio-portal-backup.service
install -m 0644 /root/tio-portal-backup.timer /etc/systemd/system/tio-portal-backup.timer
systemd-analyze verify /etc/systemd/system/tio-backup.service /etc/systemd/system/tio-backup.timer /etc/systemd/system/tio-portal-backup.service /etc/systemd/system/tio-portal-backup.timer
systemctl daemon-reload
systemctl start tio-backup.service tio-portal-backup.service
systemctl enable --now tio-backup.timer tio-portal-backup.timer
systemctl show tio-backup.service tio-portal-backup.service --property=Result
systemctl list-timers tio-backup.timer tio-portal-backup.timer --no-pager
```

Before a gameplay update:

```bash
runuser -u tio -- /opt/tio-emulator/.venv/bin/python /opt/tio-emulator/deploy/scheduled_backup.py --source /var/lib/tio-server/reservation.sqlite3 --directory /var/backups/tio-server --tag pre-update
```

Before a portal update (also used by `web/deploy/install_portal.sh`):

```bash
/opt/tio-portal/backup_portal.sh --tag before-release
```

## Encrypted copies on the selected Windows computer

`tools/offsite_backup_windows.py` captures a complete application recovery bundle
over the existing authenticated SSH connection. The remote module stages and
checks the bundle privately before binary output. Capture/verification keeps
plaintext in local process memory; the only local archive is encrypted using
Windows CurrentUser DPAPI. The destination
`%LOCALAPPDATA%\TIO-emulator\backups` has a protected ACL for the current user.
A kernel lock prevents overlapping scheduled/manual captures.

The schema2 bundle includes:

- A consistent hosted SQLite snapshot, custom PostgreSQL dump, full isolated
  PostgreSQL restore with aggregate table counts, and private PostgreSQL role/global
  definitions. Database files are separate consistent snapshots; they do not form
  a single cross-database transaction.
- Game code, registration/API code, dependency specifications and required runtime
  evidence; the exact current portal release with its runtime dependencies and
  maintenance scripts; the installed `/opt/tio-node` runtime.
- `/etc/tio-server` and `/etc/tio-portal`, including private environment files and
  gameplay TLS material; relevant Nginx configurations and all custom tio service
  units/timers/drop-ins.
- Active Let's Encrypt certificates, current archive targets, ACME account data,
  renewal configuration, hooks and optional Nginx TLS options/DH parameters. Safe
  link metadata preserves the Certbot live/archive relationship; tar members are
  regular files.
- The published client manifest, every hash-referenced current blob and current
  downloads. Unreferenced historical update blobs and portal `.next/cache` are
  excluded. Every file has a checksum, size and source permission mode in the
  manifest. Capture fails if the active portal release or client manifest changes.

Verification checks all member hashes, required components, referenced client
blobs and safe paths, then restores the SQLite image in memory. PostgreSQL restore
is performed on the server during capture; Windows verification checks its
protected receipt and dump hash. It does not run a second local PostgreSQL restore.
This is an application recovery bundle, not a complete OS image: recreate Linux
users, PostgreSQL16, Python environments, Nginx and the Certbot runtime before
starting recovered units. Existing schema1 game-only DPAPI copies remain readable
but are not accepted as successful new platform captures.

```powershell
python tools/offsite_backup_windows.py --retention-days 31
python tools/offsite_backup_windows.py --if-due --retention-days 31
python tools/offsite_backup_windows.py --verify '<absolute encrypted copy path>'
```

A verified new copy is published exclusively under
`platform-<UTC timestamp>.dpapi`, then strict owned daily names older than 31 days
are removed. A failed capture/encryption/verification does not prune anything.
Legacy `tio-*`, manually named files and unknown filenames are preserved.
`--if-due` skips only after decrypting and verifying a platform copy from the last
24 hours; malformed/future names and corrupt copies cannot count as success.
This is a 24-hour eligibility gate rather than one copy per calendar day. A late
initial capture can make the next daily trigger skip; observed intervals with
daily/logon triggers are normally 24–48 hours while this computer is available.

The local installer `tools/install_offsite_backup_task.ps1` configures the native
Windows task (daily + current-user logon, `StartWhenAvailable`, no stored Windows
password). Its action uses `--if-due`; a missed run is attempted when the user
logs in with network access. DPAPI and SSH authentication run under that same
user. A logged-out/offline/switched-off computer cannot receive a copy; failed
runs are visible in Task Scheduler and the wrapper's aggregate status report.
Installing/running the task and the first remote capture are separate operational
steps; local tests alone do not establish that they happened.

Preserve this Windows profile and its DPAPI keys. An encrypted archive alone
cannot be decrypted after losing the profile or under an unrelated account.

## Repeatable restore drill and actual recovery

To test an existing private portal dump, run on the VPS:

```bash
python3 /opt/tio-portal/portal_backup.py --validate /var/backups/tio-portal/<verified-dump>.dump
```

This creates/restores/queries/drops only its own random scratch database; it never
uses `--create`, the live database name as a restore target, or live credentials.
Retain sanitized evidence of PostgreSQL version, command success, restored table
count and total rows. The SQLite check uses the backup API and integrity check;
the Windows verifier additionally restores the exported database image in memory.

Actual recovery requires an explicitly selected verified copy and a maintenance
window. `--verify <copy> --export-new <new private directory>` is an explicit
plaintext export for recovery; it refuses an existing directory and sets its ACL
before writing contents. It does not install anything or alter a hosted database.

For recovery on a replacement host, recreate required packages/users first.
Review `manifest.json` without displaying private file contents. Restore code,
current portal release, config, current client assets and units using the recorded
permission modes and appropriate tio/tio-web ownership. Preserve root-only secrets
and root:service-group 0640 environment files. Recreate `current` and known Nginx
`sites-enabled` links. Rebuild Certbot `live` symlinks from `tls.live_links` only
after validating each archived path and target, whose hashes must agree. Do not
execute a recovered service before checking its paths and configuration.

For either replacement-host or in-place database recovery:

1. Stop all writers: `tio-server`, `tio-game-api`, `tio-portal`, and the legacy
   `tio-registration` service if present. Stop backup/portal-cleanup timers **and
   any currently running backup/cleanup jobs**. Confirm no process retains the
   database before replacing it.
2. Preserve the current SQLite DB together with its `-wal`/`-shm` sidecars and a
   fresh PostgreSQL dump in a separate private rollback directory. Never delete
   live WAL data first. Prepare the selected SQLite image outside the live path,
   verify it, install atomically with tio:tio ownership and 0600 permissions, and
   ensure old sidecars cannot be paired with the new image.
3. Restore PostgreSQL into a new database first; check schema and all table counts.
   Apply role/global definitions only on a fresh reviewed host: they contain
   sensitive authentication material and may conflict with existing roles. An
   in-place replacement of `tionline_web` is a separate explicit maintenance
   operation after rollback copies and writer shutdown, never part of a drill.
4. Check configs/TLS/Nginx, start services, verify website health and two-account
   authoritative gameplay, then resume timers. If checks fail, keep writers
   stopped while restoring the preserved rollback state.

Historical stage3 gameplay backup evidence is in
[BATTLE_RECOVERY_STAGE3.md](../BATTLE_RECOVERY_STAGE3.md). It proves that earlier
scope only; the expanded platform restore/capture needs its own operational
verification record.
