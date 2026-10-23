"""Apply the audited static-backup deduplication plan without touching live files.

Run on the VPS with one plan path. All paths must be old regular single-link
payloads inside /root/tio-before-*; no player database is ever deduplicated.
"""
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

from inspect_backup_duplicates_20261023 import digest, fingerprint


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    os.nice(10)
    plan = json.loads(Path(sys.argv[1]).read_text())
    assert 0 <= time.time() - plan['created'] < 1800, 'Stale plan'
    paths = []
    for group in plan['groups']:
        assert len(group['files']) > 1
        for row in group['files']:
            p = Path(row['path'])
            assert (p.parent != Path('/root') and p.is_relative_to('/root')
                    and p.parts[2].startswith('tio-before-') and p.resolve() == p
                    and p.suffix.lower() in ('.exe', '.dll', '.zip', '.gz'))
            assert fingerprint(p) == row['stat'], 'Backup baseline changed: ' + str(p)
            assert stat.S_ISREG(row['stat'][3]) and row['stat'][8] == 1
            assert row['stat'][2] >= 5 * 1024**2
            assert row['stat'][6] / 1e9 < time.time() - 86400
            assert not os.listxattr(p)
            paths.append(p)
        assert all(row['stat'][2:6] == group['files'][0]['stat'][2:6] for row in group['files'])
    assert len(paths) == len(set(paths))
    inodes = {(p.stat().st_dev, p.stat().st_ino) for p in paths}
    for proc in Path('/proc').glob('[0-9]*/fd'):
        try:
            for fd in proc.iterdir():
                try:
                    s = fd.stat()
                except (FileNotFoundError, PermissionError):
                    continue
                assert (s.st_dev, s.st_ino) not in inodes, 'Backup is open in a process'
        except (FileNotFoundError, PermissionError):
            continue

    maintenance = Path(tempfile.mkdtemp(prefix='tio-disk-maintenance-20261023-', dir='/root'))
    (maintenance/'duplicates-plan.json').write_text(json.dumps(plan, indent=2))
    before = os.statvfs('/')
    source = sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro', uri=True)
    target = sqlite3.connect(maintenance/'reservation.sqlite3')
    try:
        source.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    finally:
        target.close()
        source.close()
    subprocess.run(['tar', '--exclude=.venv', '--exclude=.venv-web', '--exclude=__pycache__',
                    '-czf', str(maintenance/'game-code-config.tar.gz'), '-C', '/',
                    'opt/tio-emulator', 'etc/tio-server', 'etc/systemd/system/tio-server.service'],
                   check=True, capture_output=True)
    service_before = subprocess.check_output(['systemctl', 'show', 'tio-server',
                            '-p', 'MainPID', '-p', 'NRestarts'], text=True)
    completed = []
    for group in plan['groups']:
        anchor = Path(group['files'][0]['path'])
        assert fingerprint(anchor) == group['files'][0]['stat']
        assert digest(anchor) == group['sha256']
        for row in group['files'][1:]:
            p = Path(row['path'])
            assert fingerprint(p) == row['stat'], 'Backup changed before replacement'
            temporary = p.with_name(p.name+'.disk-dedup-20261023')
            assert not temporary.exists()
            os.link(anchor, temporary)
            try:
                assert fingerprint(p) == row['stat']
                os.replace(temporary, p)
            finally:
                if temporary.exists():
                    temporary.unlink()
            assert p.samefile(anchor)
            completed.append({'path': str(p), 'anchor': str(anchor), 'sha256': group['sha256']})
            (maintenance/'completed.json').write_text(json.dumps(completed, indent=2))
        assert digest(anchor) == group['sha256']
        for row in group['files']:
            p = Path(row['path'])
            s = fingerprint(p)
            assert p.samefile(anchor) and s[2:6] == row['stat'][2:6]

    after = os.statvfs('/')
    service_after = subprocess.check_output(['systemctl', 'show', 'tio-server',
                            '-p', 'MainPID', '-p', 'NRestarts'], text=True)
    assert service_after == service_before, 'Unexpected service restart'
    report = dict(maintenance=str(maintenance), groups=len(plan['groups']),
                  duplicate_files_replaced=len(completed),
                  payload_bytes_reclaimed=plan['reclaimable_bytes'],
                  available_before=before.f_bavail*before.f_frsize,
                  available_after=after.f_bavail*after.f_frsize,
                  all_paths_and_contents_verified=True,
                  original_timestamps_in_plan=True, live_data_changed=False,
                  sqlite_backup_integrity='ok', service_before=service_before,
                  service_after=service_after)
    (maintenance/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
