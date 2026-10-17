"""Private platform recovery capture encrypted with Windows CurrentUser DPAPI.

Capture/verification writes no local plaintext. The server prepares consistent
SQLite/PostgreSQL images and restores PostgreSQL into an isolated temporary DB.
This command never installs a release or restores a live hosted database.
"""
from contextlib import closing, contextmanager
import argparse
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import subprocess
import tarfile
import uuid

MAGIC = b'TIO-DPAPI-1\n'  # Keep existing CurrentUser recovery copies readable.
HOST = 'root@185.184.42.88'
REMOTE = '/usr/bin/python3 /opt/tio-emulator/deploy/recovery_bundle.py'
MAX_BYTES = 2 * 1024 ** 3
MAX_FILES = 100_000
MAX_METADATA = 32 * 1024 ** 2
CHUNK = 1024 * 1024
AUTOMATIC = re.compile(r'platform-(\d{8}T\d{12}Z)\.dpapi')
LEGACY_REQUIRED = {
    'server.toml', 'tio-server.service', 'server/runtime.py', 'tio/battle_state.py',
    'requirements.txt', 'evidence/items_diagnostic.xml',
    'evidence/skills_diagnostic.xml', 'evidence/zones_diagnostic.xml',
    'evidence/customization_diagnostic.xml', 'evidence/owned_pet_trial.json',
}
PLATFORM_REQUIRED = {
    'data/reservation.sqlite3', 'data/portal.dump', 'data/postgres-globals.sql',
    'game/server/runtime.py', 'game/tio/battle_state.py', 'game/requirements.txt',
    'portal/server.js',
    'config/tio-server/server.toml', 'config/tio-portal/portal.env',
    'systemd/tio-server.service', 'systemd/tio-portal.service',
    'client/updates/manifest.json',
}


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, *, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Windows CurrentUser DPAPI is required')
    if not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Encrypted recovery copy size limit exceeded')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    api = ctypes.WinDLL('crypt32', use_last_error=True)
    function = api.CryptUnprotectData if decrypt else api.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN, current user scope; never suppress TLS/SSH checks.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Windows CurrentUser recovery encryption failed')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(target.data)


def safe_member(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or '\x00' in name or PurePosixPath(name).is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe recovery archive member')
    for part in name.split('/'):
        stem = part.split('.')[0].upper()
        if (part.endswith((' ', '.')) or stem in {'CON', 'PRN', 'AUX', 'NUL'}
                or re.fullmatch(r'(?:COM|LPT)[1-9]', stem)):
            raise ValueError('Unsafe Windows recovery archive member')
    return name


def _archive(payload):
    if not 0 < len(payload) <= MAX_BYTES:
        raise ValueError('Recovery archive size limit exceeded')
    files, selected, seen, total = {}, {}, set(), 0
    retain = {'manifest.json', 'metadata.json', 'reservation.sqlite3',
              'data/reservation.sqlite3', 'client/updates/manifest.json'}
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive:
            name = safe_member(member.name.rstrip('/') if member.isdir() else member.name)
            if name in seen or len(seen) >= MAX_FILES + 1:
                raise ValueError('Duplicate or excessive recovery archive members')
            seen.add(name)
            if member.isdir():
                continue  # Old game-only copies contained directory headers.
            if not member.isfile() or member.size < 0:
                raise ValueError('Recovery archive contains a non-regular file')
            total += member.size
            if total > MAX_BYTES:
                raise ValueError('Recovery archive size limit exceeded')
            if name in {'manifest.json', 'metadata.json', 'client/updates/manifest.json'} and member.size > MAX_METADATA:
                raise ValueError('Recovery metadata size limit exceeded')
            digest, size = hashlib.sha256(), 0
            keep = io.BytesIO() if name in retain else None
            with archive.extractfile(member) as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    if keep is not None:
                        keep.write(chunk)
            if size != member.size:
                raise ValueError('Recovery archive is truncated')
            files[name] = {'sha256': digest.hexdigest(), 'size': size}
            if keep is not None:
                selected[name] = keep.getvalue()
    return files, selected


def _sqlite(image, expected_accounts):
    if type(expected_accounts) is not int or expected_accounts < 0:
        raise ValueError('Invalid recovery account count')
    try:
        with closing(sqlite3.connect(':memory:')) as database:
            database.deserialize(image)
            if database.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite recovery integrity check failed')
            accounts = database.execute('SELECT count(*) FROM accounts').fetchone()[0]
            if accounts != expected_accounts:
                raise ValueError('SQLite recovery account count differs')
    except sqlite3.Error:
        raise ValueError('SQLite recovery image cannot be restored') from None
    return accounts


def verify_payload(payload):
    """Check every member; return aggregate evidence, never private file contents."""
    files, selected = _archive(payload)
    if 'manifest.json' not in selected:
        metadata = json.loads(selected.get('metadata.json', b'null'))
        if not isinstance(metadata, dict) or not LEGACY_REQUIRED.issubset(files):
            raise ValueError('Legacy game recovery copy is incomplete')
        image = selected.get('reservation.sqlite3')
        if image is None or hashlib.sha256(image).hexdigest() != metadata.get('database_sha256'):
            raise ValueError('Legacy SQLite recovery checksum differs')
        accounts = _sqlite(image, metadata.get('accounts'))
        return {'scope': 'game', 'accounts': accounts, 'integrity': 'ok',
                'verified_restore': ['in-memory SQLite'],
                'bundle_sha256': hashlib.sha256(payload).hexdigest()}
    manifest = json.loads(selected['manifest.json'])
    if (not isinstance(manifest, dict) or manifest.get('schema') != 2
            or manifest.get('scope') != 'platform' or not isinstance(manifest.get('files'), list)):
        raise ValueError('Unknown platform recovery manifest')
    expected = {}
    for record in manifest['files']:
        if not isinstance(record, dict):
            raise ValueError('Invalid platform recovery manifest')
        name = safe_member(record.get('path'))
        if (name in expected or name == 'manifest.json' or type(record.get('size')) is not int
                or record['size'] < 0 or not isinstance(record.get('sha256'), str)
                or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
            raise ValueError('Invalid platform recovery manifest')
        expected[name] = {'sha256': record['sha256'], 'size': record['size']}
    if (set(files) != set(expected) | {'manifest.json'}
            or not PLATFORM_REQUIRED.issubset(expected)
            or any(files[name] != record for name, record in expected.items())):
        raise ValueError('Platform recovery copy is incomplete or has changed')
    tls = manifest.get('tls', {})
    if not isinstance(tls, dict) or not isinstance(tls.get('live_links', []), list):
        raise ValueError('Invalid TLS recovery link metadata')
    live_names = set()
    for link in tls.get('live_links', []):
        if not isinstance(link, dict) or set(link) != {'path', 'target'}:
            raise ValueError('Invalid TLS recovery link metadata')
        live, target = safe_member(link['path']), safe_member(link['target'])
        if (live in live_names or not live.startswith('letsencrypt/live/')
                or not target.startswith('letsencrypt/archive/')
                or live not in expected or target not in expected
                or expected[live] != expected[target]):
            raise ValueError('TLS recovery link target differs')
        live_names.add(live)
    sqlite = manifest.get('sqlite', {})
    postgres = manifest.get('postgres', {})
    globals_record = manifest.get('globals', {})
    if (not all(isinstance(value, dict) for value in (sqlite, postgres, globals_record))
            or sqlite.get('path') != 'data/reservation.sqlite3'
            or postgres.get('path') != 'data/portal.dump'
            or globals_record.get('path') != 'data/postgres-globals.sql'
            or not expected['data/portal.dump']['size']
            or not expected['data/postgres-globals.sql']['size']):
        raise ValueError('Platform database recovery images are missing')
    counts = postgres.get('restored_tables')
    if not isinstance(counts, list) or not counts:
        raise ValueError('Isolated PostgreSQL restore evidence is missing')
    names = set()
    for row in counts:
        if (not isinstance(row, dict) or set(row) != {'table', 'rows'}
                or not isinstance(row['table'], str) or not row['table']
                or row['table'] in names or type(row['rows']) is not int or row['rows'] < 0):
            raise ValueError('Invalid isolated PostgreSQL restore evidence')
        names.add(row['table'])
    client = json.loads(selected['client/updates/manifest.json'])
    if not isinstance(client, dict) or client.get('schema') != 1 or not isinstance(client.get('files'), list) or not client['files']:
        raise ValueError('Published client recovery manifest is invalid')
    logical_names, blobs = set(), set()
    for record in client['files']:
        if not isinstance(record, dict):
            raise ValueError('Published client recovery manifest is invalid')
        name = safe_member(record.get('path'))
        sha, size = record.get('sha256'), record.get('size')
        if (name in logical_names or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha)
                or type(size) is not int or size < 0):
            raise ValueError('Published client recovery manifest is invalid')
        logical_names.add(name)
        blob = 'client/updates/blobs/' + sha
        if expected.get(blob) != {'size': size, 'sha256': sha}:
            raise ValueError('Published client recovery blob is missing')
        blobs.add(blob)
    if {name for name in expected if name.startswith('client/updates/blobs/')} != blobs:
        raise ValueError('Recovery copy contains unreferenced client blobs')
    accounts = _sqlite(selected['data/reservation.sqlite3'], sqlite.get('accounts'))
    return {'scope': 'platform', 'accounts': accounts, 'portal_tables': len(counts),
            'portal_rows': sum(row['rows'] for row in counts), 'integrity': 'ok',
            'verified_restore': ['in-memory SQLite', 'remote isolated PostgreSQL'],
            'files': len(expected), 'bundle_sha256': hashlib.sha256(payload).hexdigest()}


def _read_encrypted(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Invalid encrypted recovery copy')
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError('Unknown encrypted recovery copy format')
    return raw


def verify(path):
    path = Path(path)
    raw = _read_encrypted(path)
    result = verify_payload(crypt(raw[len(MAGIC):], decrypt=True))
    return dict(result, path=str(path.resolve()), encrypted_bytes=len(raw))


def _stamp(path):
    match = AUTOMATIC.fullmatch(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match[1], '%Y%m%dT%H%M%S%fZ').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune(directory, *, now, days):
    """Remove only owned daily names after a new verified snapshot succeeded."""
    cutoff, removed = now - timedelta(days=days), 0
    for path in Path(directory).iterdir():
        stamp = _stamp(path)
        if stamp is not None and stamp < cutoff and path.is_file() and not path.is_symlink():
            path.unlink()
            removed += 1
    return removed


def publish(payload, directory, *, now=None, days=31):
    if type(days) is not int or not 1 <= days <= 3650:
        raise ValueError('Retention days must be between 1 and 3650')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware capture time required')
    now = now.astimezone(timezone.utc)
    evidence = verify_payload(payload)
    if evidence['scope'] != 'platform':
        raise ValueError('New automatic copies must cover the full platform')
    directory = Path(directory)
    final = directory / ('platform-' + now.strftime('%Y%m%dT%H%M%S%fZ') + '.dpapi')
    if final.exists() or final.is_symlink():
        raise FileExistsError(final)
    encrypted = MAGIC + crypt(payload)
    pending = directory / ('.pending-' + uuid.uuid4().hex + '.dpapi')
    try:
        descriptor = os.open(pending, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        result = verify(pending)
        if result['bundle_sha256'] != evidence['bundle_sha256']:
            raise ValueError('Encrypted recovery verification differs')
        os.link(pending, final)
    finally:
        pending.unlink(missing_ok=True)
    result.update(path=str(final.resolve()), status='captured', pruned=prune(directory, now=now, days=days))
    return result


def _protect_directory(path):
    if os.name != 'nt':
        raise RuntimeError('Windows CurrentUser backup destination is required')
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Backup destination must not be a symbolic link')
    path.mkdir(parents=True, exist_ok=True)
    # Install an exact protected DACL, instead of retaining old explicit grants.
    script = """$ErrorActionPreference='Stop'
$p=$env:TIO_BACKUP_ACL_PATH
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl=[Security.AccessControl.DirectorySecurity]::new()
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true,$false)
$rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
$acl.AddAccessRule($rule)
[IO.Directory]::SetAccessControl($p,$acl)
"""
    environment = dict(os.environ, TIO_BACKUP_ACL_PATH=str(path.resolve()))
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                        encoded], env=environment, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Private backup destination permissions could not be set') from None


@contextmanager
def capture_lock(directory):
    """A kernel-released lock serializes scheduler and manual captures."""
    if os.name != 'nt':
        raise RuntimeError('Windows capture lock is required')
    import msvcrt
    path = Path(directory) / '.capture.lock'
    if path.is_symlink():
        raise ValueError('Invalid backup lock')
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError('Another recovery capture is already running') from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def recently_verified(directory, *, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    candidates = sorted((path for path in Path(directory).iterdir()
                         if not path.is_symlink() and path.is_file() and _stamp(path) is not None),
                        key=lambda path: _stamp(path), reverse=True)
    for path in candidates:
        stamp = _stamp(path)
        if not cutoff <= stamp <= now:
            continue
        try:
            result = verify(path)
        except (OSError, ValueError, RuntimeError, tarfile.TarError):
            continue
        if result['scope'] == 'platform':
            return dict(result, status='skipped', reason='verified backup within 24 hours', pruned=0)
    return None


def _remote_capture():
    try:
        result = subprocess.run([
            'ssh', '-i', str(Path.home() / '.ssh' / 'tio_server'),
            '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
            '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
            HOST, REMOTE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            check=True, timeout=25 * 60, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Remote recovery capture failed') from None
    if not 0 < len(result.stdout) <= MAX_BYTES:
        raise ValueError('Remote recovery archive size limit exceeded')
    return result.stdout


def export_new(path, destination):
    result = verify(path)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    # Explicit plaintext export. ACL is set before any private contents exist.
    destination.mkdir(parents=False, mode=0o700)
    _protect_directory(destination)
    raw = _read_encrypted(path)
    payload = crypt(raw[len(MAGIC):], decrypt=True)
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive:
            name = safe_member(member.name.rstrip('/') if member.isdir() else member.name)
            target = destination.joinpath(*name.split('/'))
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            if not member.isfile():
                raise ValueError('Recovery export contains a non-regular file')
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'wb') as writer, archive.extractfile(member) as reader:
                while chunk := reader.read(CHUNK):
                    writer.write(chunk)
    result['exported_plaintext'] = str(destination.resolve())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--export-new', type=Path,
                        help='Explicit plaintext export into a new private directory for manual recovery')
    parser.add_argument('--retention-days', type=int, default=31)
    parser.add_argument('--if-due', action='store_true', help='Capture only if no verified platform copy exists within 24 hours')
    args = parser.parse_args()
    if args.export_new and not args.verify:
        parser.error('--export-new requires --verify')
    try:
        if args.verify:
            result = export_new(args.verify, args.export_new) if args.export_new else verify(args.verify)
        else:
            if not 1 <= args.retention_days <= 3650:
                raise ValueError('Invalid retention days')
            folder = Path(os.environ['LOCALAPPDATA']) / 'TIO-emulator' / 'backups'
            _protect_directory(folder)
            with capture_lock(folder):
                result = recently_verified(folder) if args.if_due else None
                if result is None:
                    result = publish(_remote_capture(), folder, days=args.retention_days)
        print(json.dumps(result))
    except (OSError, ValueError, RuntimeError, tarfile.TarError):
        parser.exit(1, 'Offsite backup operation failed; check verified copies and scheduled status.\n')


if __name__ == '__main__':
    main()
