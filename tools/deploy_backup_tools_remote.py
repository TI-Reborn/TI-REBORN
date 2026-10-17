"""Guarded operational-file installation for Stage3 backups, without game restart.

Inspection reads public operational files/tool versions only. Apply backs up those
files, writes exclusively/atomically and reloads systemd. Database verification is
an explicit separate --validate-dump operation, never a live database restore.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid

FILES = {
    'deploy/backup.py': ('/opt/tio-emulator/deploy/backup.py', 0o644),
    'deploy/recovery_bundle.py': ('/opt/tio-emulator/deploy/recovery_bundle.py', 0o644),
    'web/deploy/portal_backup.py': ('/opt/tio-portal/portal_backup.py', 0o644),
    'web/deploy/backup_portal.sh': ('/opt/tio-portal/backup_portal.sh', 0o755),
    'web/deploy/tio-portal-backup.service': ('/etc/systemd/system/tio-portal-backup.service', 0o644),
}
MAX_BYTES = 2 * 1024 ** 2
PG = '/usr/lib/postgresql/16/bin/'
ENV = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'LANG': 'C.UTF-8'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_package(path, expected):
    path = Path(path)
    if not re.fullmatch('[0-9a-f]{64}', expected) or not path.is_file() or path.is_symlink():
        raise ValueError('Invalid backup-tools package')
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Backup-tools package size limit exceeded')
    raw = path.read_bytes()
    if not 0 < len(raw) <= MAX_BYTES or digest(raw) != expected:
        raise ValueError('Backup-tools package checksum differs')
    contents, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive:
            if member.name not in FILES.keys() | {'manifest.json'} or member.name in contents or not member.isfile():
                raise ValueError('Unexpected backup-tools member')
            total += member.size
            if member.size < 0 or total > MAX_BYTES:
                raise ValueError('Backup-tools package size limit exceeded')
            contents[member.name] = archive.extractfile(member).read()
    manifest = json.loads(contents.pop('manifest.json', b'null'))
    if (set(contents) != set(FILES) or not isinstance(manifest, dict)
            or manifest.get('schema') != 1 or manifest.get('kind') != 'backup-tools-stage3'
            or not isinstance(manifest.get('files'), list)):
        raise ValueError('Incomplete backup-tools package')
    records = {}
    for entry in manifest['files']:
        if not isinstance(entry, dict) or entry.get('source') not in FILES or entry['source'] in records:
            raise ValueError('Invalid backup-tools manifest')
        name = entry['source']
        target, mode = FILES[name]
        if (entry.get('target') != target or entry.get('mode') != mode
                or entry.get('size') != len(contents[name]) or entry.get('sha256') != digest(contents[name])):
            raise ValueError('Backup-tools manifest differs')
        if b'\r' in contents[name]:
            raise ValueError('Backup-tools scripts must use LF line endings')
        if name.endswith('.py'):
            ast.parse(contents[name].decode('utf-8'), filename=name)
        records[name] = entry
    if set(records) != set(FILES):
        raise ValueError('Incomplete backup-tools manifest')
    return contents, manifest


def state(path):
    path = Path(path)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise ValueError('Operational path must not contain symlinks')
    if not path.exists():
        return {'exists': False, 'sha256': None}
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Invalid existing operational file')
    info = path.stat()
    return {'exists': True, 'sha256': digest(path.read_bytes()), 'mode': info.st_mode & 0o777,
            'uid': info.st_uid, 'gid': info.st_gid}


def command(args, *, runner=subprocess.run, timeout=30):
    try:
        return runner(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                      text=True, env=ENV, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Backup-tools preflight or service query failed') from None


def service(name, *, runner=subprocess.run):
    result = command(['/usr/bin/systemctl', 'show', name, '-p', 'MainPID', '-p', 'NRestarts',
                      '-p', 'ActiveState'], runner=runner)
    return dict(line.split('=', 1) for line in result.splitlines() if '=' in line)


def inspect(contents, manifest, *, runner=subprocess.run):
    if os.geteuid() != 0 or sys.version_info < (3, 10):
        raise RuntimeError('Root and Python3.10 or later are required')
    required = ['/usr/bin/python3', '/usr/bin/env', '/usr/sbin/runuser', '/bin/bash',
                '/usr/bin/systemctl', '/usr/bin/systemd-analyze'] + [PG + name for name in
                ('pg_dump', 'pg_dumpall', 'pg_restore', 'createdb', 'dropdb', 'psql')]
    for path in required:
        if not Path(path).is_file() or not os.access(path, os.X_OK):
            raise RuntimeError('Required backup runtime is unavailable')
    versions = {name: command([PG + name, '--version'], runner=runner)
                for name in ('pg_dump', 'pg_restore', 'psql')}
    if any(not re.search(r'\b16\.', version) for version in versions.values()):
        raise RuntimeError('PostgreSQL16 tools are required')
    connection = command(['/usr/sbin/runuser', '-u', 'postgres', '--', '/usr/bin/env', '-i',
                          'PATH=' + PG.rstrip('/') + ':/usr/bin:/bin', 'LANG=C.UTF-8', PG + 'psql',
                          '--host=/var/run/postgresql', '--port=5432', '--username=postgres',
                          '--dbname=postgres', '--no-psqlrc', '--no-align', '--tuples-only',
                          '--set=ON_ERROR_STOP=1',
                          "--command=SELECT current_setting('server_version_num'),current_setting('port');"],
                         runner=runner)
    pieces = connection.split('|')
    if len(pieces) != 2 or not pieces[0].isdigit() or not 160000 <= int(pieces[0]) < 170000 or pieces[1] != '5432':
        raise RuntimeError('The verified local PostgreSQL16 socket is unavailable')
    for directory in ('/opt/tio-emulator/deploy', '/opt/tio-portal', '/etc/systemd/system',
                      '/var/backups/tio-server', '/var/backups/tio-portal'):
        if not Path(directory).is_dir() or Path(directory).is_symlink():
            raise RuntimeError('Required existing backup directory is unavailable')
    for path in ('/opt/tio-emulator/deploy/scheduled_backup.py', '/opt/tio-portal/cleanup.sql'):
        if not Path(path).is_file():
            raise RuntimeError('An existing backup dependency is unavailable')
    game, portal = service('tio-server', runner=runner), service('tio-portal', runner=runner)
    if any(item.get('ActiveState') != 'active' for item in (game, portal)):
        raise RuntimeError('Hosted services are not healthy')
    jobs = {name: service(name, runner=runner).get('ActiveState') for name in
            ('tio-backup', 'tio-portal-backup', 'tio-portal-cleanup')}
    # Bash/unit syntax checks operate on a private staged public script only.
    with tempfile.TemporaryDirectory(prefix='tio-backup-tools-check-') as directory:
        directory = Path(directory)
        wrapper = directory / 'backup_portal.sh'
        wrapper.write_bytes(contents['web/deploy/backup_portal.sh'])
        command(['/bin/bash', '-n', str(wrapper)], runner=runner)
        unit = directory / 'tio-portal-backup.service'
        unit.write_bytes(contents['web/deploy/tio-portal-backup.service'])
        command(['/usr/bin/systemd-analyze', 'verify', str(unit)], runner=runner)
    return {'schema': 1, 'kind': 'backup-tools-inspection',
            'created_utc': datetime.now(timezone.utc).isoformat(), 'python': sys.version.split()[0],
            'python_executable': sys.executable, 'postgres_tools': versions,
            'postgres_local_socket': '/var/run/postgresql:5432',
            'package_files': manifest['files'],
            'before': {name: state(target) for name, (target, _) in FILES.items()},
            'game': game, 'portal': portal, 'jobs': jobs}


def atomic_write(path, raw, *, mode, uid=None, gid=None):
    path = Path(path)
    pending = path.with_name('.' + path.name + '.backup-tools-' + uuid.uuid4().hex)
    try:
        descriptor = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        pending.chmod(mode)
        if uid is not None:
            os.chown(pending, uid, gid)
        os.replace(pending, path)
        if hasattr(os, 'O_DIRECTORY'):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        pending.unlink(missing_ok=True)


@contextmanager
def deploy_lock():
    import fcntl
    descriptor = os.open('/run/lock/tio-backup-tools-deploy.lock', os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def apply(contents, manifest, baseline, *, runner=subprocess.run, backup_parent=Path('/root')):
    actual = inspect(contents, manifest, runner=runner)
    if (not isinstance(baseline, dict) or baseline.get('kind') != 'backup-tools-inspection'
            or actual['before'] != baseline.get('before')
            or actual['package_files'] != baseline.get('package_files')
            or actual['game'] != baseline.get('game') or actual['portal'] != baseline.get('portal')):
        raise RuntimeError('Operational baseline changed; inspect again')
    if any(value in ('active', 'activating', 'deactivating') for value in actual['jobs'].values()):
        raise RuntimeError('An operational backup/cleanup job is running')
    backup = Path(tempfile.mkdtemp(prefix='tio-before-backup-tools-', dir=backup_parent))
    backup.chmod(0o700)
    before_bytes = {}
    for name, previous in actual['before'].items():
        if previous['exists']:
            raw = Path(FILES[name][0]).read_bytes()
            if digest(raw) != previous['sha256']:
                raise RuntimeError('Operational file changed during backup')
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(saved, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            before_bytes[name] = raw
    descriptor = os.open(backup / 'rollback.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(actual, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    installed = []
    try:
        for name, raw in contents.items():
            target, mode = FILES[name]
            previous = actual['before'][name]
            if state(target) != previous:
                raise RuntimeError('Operational file changed before publication')
            atomic_write(target, raw, mode=mode, uid=previous.get('uid', 0), gid=previous.get('gid', 0))
            installed.append(name)
        command(['/usr/bin/systemctl', 'daemon-reload'], runner=runner)
        game, portal = service('tio-server', runner=runner), service('tio-portal', runner=runner)
        if game != actual['game'] or portal != actual['portal']:
            raise RuntimeError('A hosted service changed during operational installation')
        for name, raw in contents.items():
            if state(FILES[name][0])['sha256'] != digest(raw):
                raise RuntimeError('Installed operational hash differs')
    except BaseException:
        for name in reversed(installed):
            target, _ = FILES[name]
            previous = actual['before'][name]
            if previous['exists']:
                atomic_write(target, before_bytes[name], mode=previous['mode'],
                             uid=previous['uid'], gid=previous['gid'])
            else:
                Path(target).unlink(missing_ok=True)
        command(['/usr/bin/systemctl', 'daemon-reload'], runner=runner)
        raise
    return {'status': 'installed', 'backup': str(backup),
            'files': {name: state(target) for name, (target, _) in FILES.items()},
            'game': game, 'portal': portal, 'database_access': 'local PostgreSQL version SELECT only',
            'service_restart': False, 'backup_capture': False, 'timers_changed': False}


def validate_existing_dump(path, contents, manifest, *, runner=subprocess.run):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not (path.resolve().is_relative_to('/root')
            or path.resolve().is_relative_to('/var/backups/tio-portal')):
        raise ValueError('Select an existing private portal backup')
    module_path = Path(FILES['web/deploy/portal_backup.py'][0])
    if digest(module_path.read_bytes()) != digest(contents['web/deploy/portal_backup.py']):
        raise RuntimeError('Install the reviewed portal validator before the drill')
    before = digest(path.read_bytes())
    spec = importlib.util.spec_from_file_location('_stage3_portal_validator', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tables = module.validate_dump(path, runner=runner)
    if digest(path.read_bytes()) != before:
        raise RuntimeError('Portal dump changed during restore verification')
    return {'status': 'verified', 'verified_restore': 'isolated PostgreSQL16',
            'dump_sha256': before, 'tables': tables, 'table_count': len(tables),
            'rows': sum(row['rows'] for row in tables), 'live_database_restore': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--validate-dump', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.report.exists() or args.report.is_symlink():
        parser.error('Refusing to replace an operational report')
    if args.apply and not args.baseline:
        parser.error('--apply requires the reviewed --baseline report')
    try:
        contents, manifest = load_package(args.archive, args.sha256)
        if args.inspect:
            result = inspect(contents, manifest)
        elif args.apply:
            with deploy_lock():
                result = apply(contents, manifest, json.loads(args.baseline.read_text()))
        else:
            result = validate_existing_dump(args.validate_dump, contents, manifest)
        descriptor = os.open(args.report, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        print(json.dumps(result))
    except Exception:
        parser.exit(1, 'Backup-tools operation failed; inspect the private rollback directory and service state.\n')


if __name__ == '__main__':
    main()
