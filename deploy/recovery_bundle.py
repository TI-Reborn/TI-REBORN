"""Capture a private, verified platform recovery archive to binary stdout.

This command captures hosted state; it never installs files or restores a live
database. Layout is configurable so tests need no production paths or services.
"""
from __future__ import annotations

import ast
from contextlib import closing, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile


MAX_BYTES = 2 * 1024 ** 3
MAX_FILES = 100_000
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Layout:
    game: Path = Path('/opt/tio-emulator')
    sqlite: Path = Path('/var/lib/tio-server/reservation.sqlite3')
    portal: Path = Path('/opt/tio-portal/current')
    client: Path = Path('/var/www/tio-client')
    config: tuple[Path, ...] = (Path('/etc/tio-server'), Path('/etc/tio-portal'))
    nginx: tuple[Path, ...] = (
        Path('/etc/nginx/nginx.conf'), Path('/etc/nginx/mime.types'),
        Path('/etc/nginx/sites-available/tio-launcher'),
        Path('/etc/nginx/sites-available/tireborn'),
        Path('/etc/nginx/snippets/tio-updates.conf'),
    )
    letsencrypt: Path = Path('/etc/letsencrypt')
    systemd: Path = Path('/etc/systemd/system')
    portal_backup_module: Path = Path('/opt/tio-portal/portal_backup.py')
    runtime: tuple[Path, ...] = (Path('/opt/tio-node'),)
    database: str = 'tionline_web'


def safe_member(name):
    """Reject extraction paths that can escape an archive or Windows directory."""
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or '\x00' in name or PurePosixPath(name).is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe recovery archive member')
    return name


def digest(stream):
    value = hashlib.sha256()
    size = 0
    while chunk := stream.read(CHUNK):
        size += len(chunk)
        value.update(chunk)
    return value.hexdigest(), size


def _required(path):
    path = Path(path)
    if not path.exists():
        raise RuntimeError('Required recovery source is missing')
    return path.resolve(strict=True)


def _within(path, scope):
    resolved = _required(path)
    if not resolved.is_relative_to(scope):
        raise ValueError('Recovery source escapes its approved root')
    return resolved


class Collector:
    def __init__(self, directory, *, max_bytes, max_files):
        self.directory = directory
        self.max_bytes, self.max_files = max_bytes, max_files
        self.records = {}
        self.bytes = 0

    def file(self, source, name, *, scope=None, expected=None):
        name = safe_member(name)
        if name == 'manifest.json' or name in self.records:
            raise ValueError('Duplicate recovery archive member')
        if len(self.records) >= self.max_files:
            raise RuntimeError('Recovery archive file limit exceeded')
        source = _within(source, scope) if scope is not None else _required(source)
        before = source.stat()
        if not source.is_file():
            raise ValueError('Recovery source is not a regular file')
        if before.st_size > self.max_bytes - self.bytes:
            raise RuntimeError('Recovery archive size limit exceeded')
        target = self.directory.joinpath(*name.split('/'))
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        value = hashlib.sha256()
        size = 0
        with source.open('rb') as reader, target.open('xb') as writer:
            while chunk := reader.read(CHUNK):
                size += len(chunk)
                if size > self.max_bytes - self.bytes:
                    raise RuntimeError('Recovery archive size limit exceeded')
                writer.write(chunk)
                value.update(chunk)
        target.chmod(0o600)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino) or size != before.st_size:
            raise RuntimeError('Recovery source changed during capture')
        record = {'path': name, 'sha256': value.hexdigest(), 'size': size,
                  'mode': before.st_mode & 0o777}
        if expected is not None and (record['size'], record['sha256']) != expected:
            raise RuntimeError('Published client blob verification failed')
        self.records[name] = record
        self.bytes += size
        return record

    def tree(self, source, prefix, *, scope=None, portal=False):
        source = Path(source)
        scope = _required(scope or source)

        def visit(path, name, ancestors):
            relative_parts = PurePosixPath(name).parts
            if '__pycache__' in relative_parts or name.endswith(('.pyc', '.pyo')):
                return
            if portal and any(relative_parts[index:index + 2] == ('.next', 'cache')
                              for index in range(len(relative_parts) - 1)):
                return
            resolved = _within(path, scope)
            if resolved.is_dir():
                if resolved in ancestors:
                    raise ValueError('Recovery source contains a directory link cycle')
                for child in sorted(resolved.iterdir(), key=lambda item: item.name):
                    visit(child, name + '/' + child.name, ancestors | {resolved})
            else:
                self.file(resolved, name, scope=scope)

        visit(source, safe_member(prefix), set())


def _portal_module(path):
    path = _required(path)
    spec = importlib.util.spec_from_file_location('_tio_recovery_portal_backup', path)
    if spec is None or spec.loader is None:
        raise RuntimeError('Portal backup validator is unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _runtime_assets(game):
    tree = ast.parse((game / 'server' / 'runtime.py').read_text(encoding='utf-8'))
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'RUNTIME_ASSETS'
                for target in statement.targets):
            value = ast.literal_eval(statement.value)
            if not isinstance(value, (tuple, list)) or not value:
                break
            return tuple(safe_member(name) for name in value)
    raise RuntimeError('Required game runtime assets are unavailable')


def _sqlite_image(source, destination):
    source = _required(source)
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                    raise RuntimeError('SQLite backup integrity check failed')
                accounts = dst.execute('SELECT count(*) FROM accounts').fetchone()[0]
    except sqlite3.Error:
        raise RuntimeError('SQLite recovery snapshot failed') from None
    destination.chmod(0o600)
    return accounts


def _nginx_name(source):
    try:
        relative = Path(source).relative_to('/etc/nginx').as_posix()
    except ValueError:
        relative = Path(source).name
    return 'nginx/' + relative


def _capture_tls(collector, source):
    root = _required(source)
    # live files are materialized from their archive targets inside this root.
    for name in ('live', 'renewal', 'accounts'):
        collector.tree(_required(root / name), 'letsencrypt/' + name, scope=root)
    live_links = []
    for path in sorted((root / 'live').rglob('*')):
        if path.is_symlink() and path.is_file():
            target = _within(path, root)
            link_name = 'letsencrypt/' + path.relative_to(root).as_posix()
            target_name = 'letsencrypt/' + target.relative_to(root).as_posix()
            safe_member(link_name)
            safe_member(target_name)
            if target_name not in collector.records:
                collector.file(target, target_name, scope=root)
            live_links.append({'path': link_name, 'target': target_name})
    for name in ('cli.ini', 'options-ssl-nginx.conf', 'ssl-dhparams.pem', 'renewal-hooks'):
        path = root / name
        if path.exists():
            collector.tree(path, 'letsencrypt/' + name, scope=root)
    return live_links


def _capture_units(collector, source):
    root = _required(source)
    units = sorted(path for path in root.iterdir() if re.fullmatch(
        r'tio[^/]*\.(?:service|timer)(?:\.d)?', path.name))
    if not any(path.name == 'tio-server.service' for path in units):
        raise RuntimeError('Required game service unit is missing')
    if not any(path.name == 'tio-portal.service' for path in units):
        raise RuntimeError('Required portal service unit is missing')
    for path in units:
        collector.tree(path, 'systemd/' + path.name, scope=root)


def _client(collector, source):
    root = _required(source)
    manifest_path = root / 'updates' / 'manifest.json'
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if manifest.get('schema') != 1 or not isinstance(manifest.get('files'), list) or not manifest['files']:
        raise ValueError('Published client manifest is invalid')
    collector.file(manifest_path, 'client/updates/manifest.json', scope=root,
                   expected=(len(raw), hashlib.sha256(raw).hexdigest()))
    blobs = {}
    logical_paths = set()
    for record in manifest['files']:
        if not isinstance(record, dict):
            raise ValueError('Published client manifest is invalid')
        logical = safe_member(record.get('path'))
        size, sha = record.get('size'), record.get('sha256')
        if (logical in logical_paths or type(size) is not int or size < 0
                or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)):
            raise ValueError('Published client manifest is invalid')
        logical_paths.add(logical)
        if sha in blobs and blobs[sha] != size:
            raise ValueError('Published client manifest contains conflicting blob sizes')
        blobs[sha] = size
    for sha, size in sorted(blobs.items()):
        collector.file(root / 'updates' / 'blobs' / sha, 'client/updates/blobs/' + sha,
                       scope=root, expected=(size, sha))
    collector.tree(_required(root / 'downloads'), 'client/downloads', scope=root)
    return manifest_path, raw


def _verify_archive(path, manifest, *, max_bytes, max_files):
    expected = {record['path']: record for record in manifest['files']}
    seen, size = set(), 0
    if path.stat().st_size > max_bytes:
        raise RuntimeError('Recovery archive size limit exceeded')
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            safe_member(member.name)
            if not member.isfile() or member.name in seen:
                raise ValueError('Invalid recovery archive member')
            seen.add(member.name)
            if len(seen) > max_files + 1:
                raise RuntimeError('Recovery archive file limit exceeded')
            size += member.size
            if size > max_bytes:
                raise RuntimeError('Recovery archive size limit exceeded')
            with archive.extractfile(member) as stream:
                if member.name == 'manifest.json':
                    if json.load(stream) != manifest:
                        raise RuntimeError('Recovery archive manifest verification failed')
                else:
                    record = expected.get(member.name)
                    if record is None or digest(stream) != (record['sha256'], record['size']):
                        raise RuntimeError('Recovery archive checksum verification failed')
    if seen != set(expected) | {'manifest.json'}:
        raise RuntimeError('Recovery archive is incomplete')


def capture(layout=None, *, output, runner=subprocess.run, now=None,
            max_bytes=MAX_BYTES, max_files=MAX_FILES):
    """Write a fully verified tar.gz; return its non-secret structural manifest."""
    layout = layout or Layout()
    if (type(max_bytes) is not int or max_bytes < 1 or type(max_files) is not int or max_files < 1):
        raise ValueError('Invalid recovery archive limits')
    if not isinstance(layout.database, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,62}', layout.database):
        raise ValueError('Invalid website database name')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('Timezone-aware capture time required')
    now = now.astimezone(timezone.utc)
    game, portal = _required(layout.game), _required(layout.portal)
    runtime_assets = _runtime_assets(game)
    validator = _portal_module(layout.portal_backup_module)
    with tempfile.TemporaryDirectory(prefix='tio-recovery-') as folder:
        private = Path(folder)
        private.chmod(0o700)
        stage = private / 'files'
        stage.mkdir(mode=0o700)
        work = private / 'databases'
        work.mkdir(mode=0o700)
        collector = Collector(stage, max_bytes=max_bytes, max_files=max_files)
        sqlite_image = work / 'reservation.sqlite3'
        accounts = _sqlite_image(layout.sqlite, sqlite_image)
        collector.file(sqlite_image, 'data/reservation.sqlite3')
        portal_image = work / 'portal.dump'
        with portal_image.open('xb') as stream:
            validator._command(['pg_dump', '--format=custom', '--dbname=' + layout.database],
                               'portal-dump', runner=runner, stdout=stream)
        if not portal_image.stat().st_size:
            raise RuntimeError('Website recovery dump is empty')
        portal_image.chmod(0o600)
        with redirect_stdout(io.StringIO()):
            tables = validator.validate_dump(portal_image, runner=runner)
        if (not isinstance(tables, list) or any(not isinstance(record, dict)
                or not isinstance(record.get('table'), str) or type(record.get('rows')) is not int
                or record['rows'] < 0 for record in tables)):
            raise RuntimeError('Website restored row counts are invalid')
        collector.file(portal_image, 'data/portal.dump')
        globals_image = work / 'postgres-globals.sql'
        with globals_image.open('xb') as stream:
            validator._command(['pg_dumpall', '--globals-only'], 'postgres-globals',
                               runner=runner, stdout=stream)
        if not globals_image.stat().st_size:
            raise RuntimeError('PostgreSQL globals recovery dump is empty')
        globals_image.chmod(0o600)
        collector.file(globals_image, 'data/postgres-globals.sql')
        for name in ('server', 'tio', 'tools', 'config', 'deploy'):
            collector.tree(_required(game / name), 'game/' + name, scope=game)
        collector.file(game / 'requirements.txt', 'game/requirements.txt', scope=game)
        # Existing hosted installations deploy modules and requirements directly;
        # packaging metadata is optional and is not needed to rebuild the venv.
        if (game / 'pyproject.toml').exists():
            collector.file(game / 'pyproject.toml', 'game/pyproject.toml', scope=game)
        if (game / 'registration').exists():
            collector.tree(game / 'registration', 'game/registration', scope=game)
        for name in runtime_assets:
            collector.file(game / 'evidence' / name, 'game/evidence/' + name, scope=game)
        collector.tree(portal, 'portal', scope=portal, portal=True)
        maintenance = _required(layout.portal_backup_module).parent
        for name in (Path(layout.portal_backup_module).name, 'backup_portal.sh', 'cleanup.sql'):
            collector.file(maintenance / name, 'portal-maintenance/' + name, scope=maintenance)
        for source in layout.config:
            collector.tree(_required(source), 'config/' + Path(source).name)
        for source in layout.nginx:
            collector.tree(_required(source), _nginx_name(source))
        tls_live_links = _capture_tls(collector, layout.letsencrypt)
        _capture_units(collector, layout.systemd)
        for source in layout.runtime:
            collector.tree(_required(source), 'runtime/' + Path(source).name)
        client_manifest_path, client_manifest_raw = _client(collector, layout.client)
        manifest = {
            'schema': 2, 'scope': 'platform', 'created': now.isoformat(),
            'files': [collector.records[name] for name in sorted(collector.records)],
            'sqlite': {'path': 'data/reservation.sqlite3', 'accounts': accounts},
            'postgres': {'path': 'data/portal.dump', 'restored_tables': tables},
            'globals': {'path': 'data/postgres-globals.sql'},
            'tls': {'live_links': tls_live_links},
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode('utf-8')
        if collector.bytes + len(manifest_bytes) > max_bytes:
            raise RuntimeError('Recovery archive size limit exceeded')
        archive_path = private / 'recovery.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as archive:
            for record in manifest['files']:
                info = tarfile.TarInfo(record['path'])
                info.size, info.mode, info.mtime = record['size'], record['mode'], int(now.timestamp())
                with stage.joinpath(*record['path'].split('/')).open('rb') as stream:
                    archive.addfile(info, stream)
            info = tarfile.TarInfo('manifest.json')
            info.size, info.mode, info.mtime = len(manifest_bytes), 0o600, int(now.timestamp())
            archive.addfile(info, io.BytesIO(manifest_bytes))
        archive_path.chmod(0o600)
        _verify_archive(archive_path, manifest, max_bytes=max_bytes, max_files=max_files)
        if _required(layout.portal) != portal:
            raise RuntimeError('Active portal release changed during capture')
        if client_manifest_path.read_bytes() != client_manifest_raw:
            raise RuntimeError('Active client manifest changed during capture')
        with archive_path.open('rb') as stream:
            shutil.copyfileobj(stream, output, CHUNK)
        return manifest


def main():
    try:
        capture(output=sys.stdout.buffer)
        return 0
    except Exception:
        print('Platform recovery capture failed; no verified archive was produced.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
