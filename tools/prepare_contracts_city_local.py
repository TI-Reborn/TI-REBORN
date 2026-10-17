"""Install/roll back the reviewed city skin in the two owned loopback clients.

No network, account access or process launch. Existing hardlinked resources are
replaced, never edited in place; full provenance and source pins are checked
before either client is changed. A private journal permits explicit recovery
even if installation was interrupted before provenance was committed.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.prepare_contracts_local import (BINARIES, CREATOR as CLIENT_CREATOR,
                                         MARKER, PROOF, SOURCE_CREATOR,
                                         SOURCE_PROOF, atomic, checked, digest)

CREATOR = 'tools/prepare_contracts_city_local.py'
OVERLAY_ID = 'contracts-city-field-hq-v1'
CLIENTS = ('reports/contracts-local/clients/game-a', 'reports/contracts-local/clients/game-b')
PACKAGE = 'assets/contracts-city-ui-v1/runtime'
PLAN = 'reports/contracts-local/city-ui/native/patch-plan.json'
BACKUPS = 'reports/contracts-local/city-ui/backups'
SOURCE = 'reports/arena-surroundings-implementation/client-qa/game-a'
FILES = {'silver.dll', 'base/pda/contracts_button.png', 'base/pda/contracts_frame.png',
         'base/pda/contracts_icon.png', 'base/pda/group_icon.png'}
OVERLAY_KEY = 'contracts_city_overlay'
SETTINGS_FILES = {'base/config.cfg', 'base/autoexec.cfg'}
# Exact native save keys observed in both reports/new-player/client-*/base/config.cfg.
# Keep opaque remembered identity fields in their original config only: values
# are never logged, copied to fixtures or returned by this validator.
SETTINGS_SWITCHES = set(('autoheal d_force_low_ground d_skiplogic fastcursor g_offscreen_scroll '
    'groundgrid help_arena help_bank help_clan help_clan_created help_map help_ratings '
    'help_recruits help_shop help_squad help_trade help_warehouse net_report r_alterground '
    'r_debugevent r_debugground r_debugprocess r_debugrender r_debugtiles r_drawfps '
    'r_drawground r_drawhud r_drawradar r_drawwalkpath r_flash r_fullscreen r_mini_onlive '
    'r_newanimation r_old_ground r_optimizedfog r_postprocess r_renderstage_1 '
    'r_renderstage_2 r_renderstage_3 r_renderstage_4 r_renderstage_5 r_renderstage_6 '
    'r_renderstage_7 r_renderusage r_showcollisionmap r_skipmask r_skipplayers r_softfog '
    'r_soldier_panel_autohide r_textured_models r_vsync referal_dont_show shredder_old '
    'shredder_spam shredder_unpack sound_enable tutorial_completed').split())
SETTINGS_BOUNDS = {key: (0, 1) for key in SETTINGS_SWITCHES}
SETTINGS_BOUNDS.update({
    'r_width': (640, 7680), 'r_height': (480, 4320), 'r_monitor': (0, 32),
    'arenalist_settings': (0, 4294967295), 'auc_def_buyout': (0, 2147483647),
    'auc_def_duration': (0, 168), 'bl_height': (0, 8192), 'bl_width': (0, 8192),
    'chat_settings': (0, 4294967295), 'chat_str_max': (1, 10000), 'com_maxfps': (0, 1000),
    'con_height': (0, 8192), 'd_processor': (0, 256), 'g_lastserverid': (0, 2147483647),
    'g_randomidle_interval': (0, 86400), 'last_user_agreement_hash': (-2147483648, 4294967295),
    'n4_camera_height': (-10000, 10000), 'n4_camera_len': (0, 10000),
    'n4_camera_scale': (0, 10000), 'n4_camera_shift_x': (-10000, 10000),
    'n4_camera_shift_y': (-10000, 10000), 'n4_camera_speed_x': (-10000, 10000),
    'n4_camera_speed_y': (-10000, 10000), 'n4_primitive_scale': (0, 10000),
    'n4_surface_h': (0, 8192), 'n4_surface_w': (0, 8192), 'r_burn_res': (0, 8192),
    'r_burn_speed': (0, 1000000), 'r_cam_y': (-10000, 10000), 'r_camerasmoothness': (0, 100000),
    'r_explosion_magnitude': (0, 10000), 'r_explosion_time': (0, 86400000),
    'r_flash_time': (0, 86400000), 'r_light3_pos_x': (-100000, 100000),
    'r_light3_pos_y': (-100000, 100000), 'r_light3_pos_z': (-100000, 100000),
    'r_nirvana_time': (0, 86400000), 'r_soldier_panel_opacity': (0, 100),
    'shredder_days_value': (0, 36500), 'SquadPage.InventoryList.Settings': (0, 4294967295),
    'sv_gametype': (0, 65535), 'sv_players': (0, 256), 'sv_timeperturn': (0, 86400),
    'tempx': (-32768, 32768), 'tempy': (-32768, 32768), 'volume': (0, 100), 'volume_ambient': (0, 100),
})
SETTINGS_OPAQUE = {'cl_lastlogin', 'cl_lastpass', 'orange_login', 'orange_plogin', 'orange_pchar', 'name', 'r_device_name'}
SETTINGS_LINKS = {'g_reglink', 'g_weblink'}


class InvocationDigests:
    """Hash each stable physical file once per invocation, including hardlinks.

    Every resource record is still checked. Open-handle identity and content
    change times guard cache hits; no cache survives between processes/calls.
    Windows CreationTime alone is insufficient, so native NTFS ChangeTime is
    required. Unsupported filesystems simply fall back to uncached hashing.
    """
    def __init__(self):
        self._values = {}
        self.hash_reads = 0
        self.cache_hits = 0

    @staticmethod
    def _fingerprint(stream):
        info = os.fstat(stream.fileno())
        if not info.st_ino:
            return None
        key = (info.st_dev, info.st_ino, info.st_size, info.st_mode,
               info.st_mtime_ns, info.st_ctime_ns)
        if os.name == 'nt':
            import ctypes
            import msvcrt

            class BasicInfo(ctypes.Structure):
                _fields_ = [('creation', ctypes.c_longlong), ('access', ctypes.c_longlong),
                            ('write', ctypes.c_longlong), ('change', ctypes.c_longlong),
                            ('attributes', ctypes.c_uint32)]

            native = ctypes.WinDLL('kernel32', use_last_error=True).GetFileInformationByHandleEx
            native.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
            native.restype = ctypes.c_int
            basic = BasicInfo()
            if not native(msvcrt.get_osfhandle(stream.fileno()), 0, ctypes.byref(basic), ctypes.sizeof(basic)):
                return None
            key += (basic.creation, basic.write, basic.change, basic.attributes)
        return key

    def __call__(self, path):
        with Path(path).open('rb') as stream:
            before = self._fingerprint(stream)
            if before is not None and before in self._values:
                value = self._values[before]
                self.cache_hits += 1
            else:
                sha = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    sha.update(block)
                value = sha.hexdigest()
                self.hash_reads += 1
            after = self._fingerprint(stream)
            if before is not None and before != after:
                raise ValueError('Managed resource changed during hash verification')
            if before is not None:
                self._values[before] = value
            return value
LAUNCHER = r'''$ErrorActionPreference = 'Stop'
$clientRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$marker = Get-Content -LiteralPath (Join-Path $clientRoot '.tio-owned-contracts-local') -Raw | ConvertFrom-Json
if ($marker.schema -ne 1 -or $marker.creator -ne 'tools/prepare_contracts_local.py' -or $marker.root -ne $clientRoot) { throw 'Unowned local client copy' }
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $clientRoot '..\..\..\..'))
$helper = Join-Path (Split-Path -Parent $clientRoot) 'bin\TioContractsQaClient.exe'
if (-not (Test-Path -LiteralPath $helper -PathType Leaf)) { throw 'Local guarded client helper is missing' }
$pythonCommand = Get-Command python -ErrorAction Stop
$launchTimer = [Diagnostics.Stopwatch]::StartNew()
Write-Host 'Проверяю файлы тестового клиента. При первом запуске это может занять около минуты...'
& $pythonCommand.Source (Join-Path $workspaceRoot 'tools\prepare_contracts_city_local.py') --root $workspaceRoot --refresh-settings
if ($LASTEXITCODE -ne 0) { throw 'Local client verification failed; no game process was started' }
Write-Host 'Проверка завершена. Открываю игровое окно...'
$startedJson = & $helper start $clientRoot --native-multi
if ($LASTEXITCODE -ne 0) { throw 'Guarded local client startup failed' }
$started = $startedJson | ConvertFrom-Json
if (-not $started.pid -or $started.host -ne '127.0.0.1') { throw 'Guarded helper returned no owned local game process' }
Write-Host ('Тестовый клиент запущен. PID=' + $started.pid + '; время запуска: ' + [Math]::Round($launchTimer.Elapsed.TotalSeconds, 1) + ' с.')
'''


def install_launchers(root=ROOT):
    root = Path(root).absolute()
    for relative in CLIENTS:
        verify_client(root, relative)
    helper = safe(root, 'reports/contracts-local/clients/bin/TioContractsQaClient.exe')
    if not helper.is_file():
        raise ValueError('Guarded local client helper has not been built')
    for relative in CLIENTS:
        # Windows PowerShell 5.1 otherwise reads non-ASCII script text as ANSI.
        atomic(safe(own_client(root, relative), 'launch-client.ps1'), data=LAUNCHER.encode('utf-8-sig'))
    return dict(status='launchers_updated', clients=list(CLIENTS), helper=str(helper), graphical_clients_started=0)


def validate_settings(data):
    if len(data) > 64 * 1024:
        raise ValueError('Local settings file is too large')
    try:
        text = data.decode('cp1251')
    except UnicodeDecodeError as error:
        raise ValueError('Local settings must contain ordinary scalar preferences') from error
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', text):
        raise ValueError('Local settings contain unsupported control characters')
    found = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '//')):
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_.]*)\s+(?:"([^";\x00-\x1f\x7f]*)"|([^\s";\x00-\x1f\x7f]+))', line)
        if match:
            key, value = match[1], match[2] if match[2] is not None else match[3]
        else:
            # The native saver emits empty identity fields with no quotes and
            # the GPU description as an unquoted string containing spaces.
            # Only known opaque fields may use this form, without separators,
            # quotes or controls. Numeric and endpoint grammar stays strict.
            opaque = re.fullmatch(r'([A-Za-z][A-Za-z0-9_.]*)(?:[ \t]+([^"\';\x00-\x1f\x7f]*))?', line)
            if not opaque or opaque[1] not in SETTINGS_OPAQUE:
                raise ValueError('Local settings contain duplicate or unsupported commands')
            key, value = opaque[1], opaque[2] or ''
        if key in found:
            raise ValueError('Local settings contain duplicate or unsupported commands')
        if key == 'orange_addr':
            if value != '127.0.0.1':
                raise ValueError('Local settings endpoint must remain 127.0.0.1:28512')
        elif key == 'orange_port':
            if value != '28512':
                raise ValueError('Local settings endpoint must remain 127.0.0.1:28512')
        elif key == 'g_language':
            if value not in ('russian', 'english'):
                raise ValueError('Unsupported local language preference')
        elif key in SETTINGS_BOUNDS:
            if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?', value):
                raise ValueError('Unsupported scalar display/audio/input preference')
            low, high = SETTINGS_BOUNDS[key]
            if not low <= float(value) <= high:
                raise ValueError('Local preference is outside its allowed bounds')
            if key in SETTINGS_SWITCHES or key in ('r_width', 'r_height', 'last_user_agreement_hash'):
                if '.' in value:
                    raise ValueError('Display dimensions, switches and CRC values must be integers')
        elif key in SETTINGS_OPAQUE:
            if len(value) > 4096 or value.startswith(('exec ', 'script ')):
                raise ValueError('Unsupported remembered native scalar field')
        elif key in SETTINGS_LINKS:
            if value and not re.fullmatch(r'https?://[A-Za-z0-9.\-]+(?::[0-9]{1,5})?(?:/[A-Za-z0-9_./?=&%#\-]*)?', value):
                raise ValueError('Unsupported native link preference')
        else:
            raise ValueError('Unknown local console command; settings were preserved')
        found.add(key)
    if not {'orange_addr', 'orange_port'} <= found:
        raise ValueError('Local settings lack the required loopback endpoint')
    return found


@contextmanager
def settings_lock(root):
    path = safe(root, 'reports/contracts-local/city-ui/.settings-reconcile.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'\0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('Local settings verification is already running; retry after it completes') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def safe(root, relative):
    """Reject symlinks, Windows junctions and every other reparse-point kind."""
    target = checked(root, relative)
    current = target
    while True:
        if current.exists() or current.is_symlink():
            attributes = getattr(current.lstat(), 'st_file_attributes', 0)
            if attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                raise ValueError('City overlay path contains a Windows reparse point')
        if current == Path(root).absolute():
            break
        current = current.parent
    return target


def data_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def checksum(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Invalid city overlay SHA256 pin')
    return value


def size(value):
    if type(value) is not int or not 0 <= value <= 512 * 1024 * 1024:
        raise ValueError('Invalid city overlay resource size')
    return value


def matches(path, sha256, length, *, digests=None):
    return path.is_file() and path.stat().st_size == length and (digests or digest)(path) == sha256


def identity(path):
    info = path.stat()
    return dict(device=info.st_dev, inode=info.st_ino, sha256=digest(path), size=info.st_size)


def own_client(root, client):
    if client not in CLIENTS:
        raise ValueError('Only the two designated loopback clients may receive the city overlay')
    folder = safe(root, client)
    marker = read_json(safe(folder, MARKER))
    if marker != dict(schema=1, creator=CLIENT_CREATOR, root=str(folder)):
        raise ValueError('Unowned local contracts client')
    return folder


def proof_records(proof, folder):
    if (proof.get('schema') != 1 or proof.get('creator') != CLIENT_CREATOR
            or proof.get('root') != str(folder) or proof.get('endpoint') != '127.0.0.1:28512'):
        raise ValueError('Invalid local contracts client provenance')
    records = proof.get('files')
    if not isinstance(records, list) or not records or proof.get('resources') != len(records):
        raise ValueError('Invalid local contracts resource inventory')
    rows = {}
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('Invalid client resource record')
        relative = row.get('path')
        path = safe(folder, relative)
        if relative.lower() in rows or not (relative.lower() in BINARIES or relative.startswith('base/')):
            raise ValueError('Duplicate or unsupported local client resource')
        checksum(row.get('sha256'))
        size(row.get('size'))
        rows[relative.lower()] = row
    if not BINARIES <= rows.keys():
        raise ValueError('Client provenance lacks native binaries')
    return rows


def verify_source(root, proof, rows, *, digests=None):
    hashes = digests or digest
    origin = safe(root, SOURCE)
    source_proof = safe(origin, SOURCE_PROOF)
    if (proof.get('source') != str(origin) or proof.get('source_provenance', {}).get('path') != str(source_proof)
            or hashes(source_proof) != checksum(proof.get('source_provenance', {}).get('sha256'))):
        raise ValueError('Source QA provenance changed')
    marker = read_json(safe(origin, '.tio-owned-qa'))
    metadata = read_json(source_proof)
    if (marker != dict(schema=1, creator=SOURCE_CREATOR, root=str(origin))
            or metadata.get('schema') != 1 or metadata.get('creator') != SOURCE_CREATOR
            or metadata.get('game_root') != str(origin)):
        raise ValueError('Unowned source QA copy')
    source_rows = {}
    for record in metadata.get('files', []):
        relative = record.get('path')
        safe(origin, relative)
        if relative.lower() in source_rows:
            raise ValueError('Duplicate source QA resource')
        source_rows[relative.lower()] = record
    if metadata.get('manifest_files') != len(source_rows):
        raise ValueError('Invalid source QA resource inventory')
    for name in ('ti.exe', 'orange.dll', 'silver.dll'):
        source_row = source_rows.get(name, {})
        if metadata.get('native_pins', {}).get(name) != source_row.get('qa_sha256'):
            raise ValueError('Source QA native pin changed')
    for relative, row in rows.items():
        pin = row.get('source_sha256')
        if pin is None:
            if row.get('method') != 'private_city_overlay' or row.get('path') not in FILES:
                raise ValueError('Unpinned client resource is outside the city overlay')
            continue
        checksum(pin)
        original = source_rows.get(relative)
        if original is None or original.get('qa_sha256') != pin:
            raise ValueError('Client source pin differs from QA provenance: ' + row['path'])
        if not matches(safe(origin, original['path']), pin, size(original.get('qa_size')), digests=digests):
            raise ValueError('Source QA resource changed: ' + row['path'])
    return origin


def verify_client(root, client, *, allow_settings_changes=False, digests=None):
    """Verify every managed client file and its pinned source; return provenance."""
    digests = digests or InvocationDigests()
    folder = own_client(root, client)
    proof = read_json(safe(folder, PROOF))
    rows = proof_records(proof, folder)
    verify_source(root, proof, rows, digests=digests)
    for row in rows.values():
        if not matches(safe(folder, row['path']), row['sha256'], row['size'], digests=digests):
            if allow_settings_changes and row['path'] in SETTINGS_FILES:
                validate_settings(safe(folder, row['path']).read_bytes())
            else:
                raise ValueError('Local client resource changed: ' + row['path'])
    overlay = proof.get(OVERLAY_KEY)
    if overlay:
        manifest, manifest_hash, plan_hash = package(root, digests=digests)
        if (overlay.get('schema') != 1 or overlay.get('creator') != CREATOR
                or overlay.get('overlay_id') != OVERLAY_ID or overlay.get('manifest_sha256') != manifest_hash
                or overlay.get('patch_plan_sha256') != plan_hash
                or set(overlay.get('files', [])) != FILES):
            raise ValueError('Installed city overlay descriptor differs from its reviewed package')
        for row in manifest['files']:
            managed = rows.get(row['path'].lower(), {})
            if (managed.get('sha256'), managed.get('size'), managed.get('method')) != (row['sha256'], row['size'], 'private_city_overlay'):
                raise ValueError('Installed city overlay provenance differs from its package')
            if safe(folder, row['path']).stat().st_nlink != 1:
                raise ValueError('Installed city overlay resource is not a private copy')
        backup = overlay.get('backup')
        if not isinstance(backup, str) or not re.fullmatch(re.escape(BACKUPS) + r'/[0-9]{8}T[0-9]{6}-[a-f0-9]{12}', backup):
            raise ValueError('Unsafe installed city overlay backup path')
        journal = read_json(safe(root, backup + '/install.json'))
        entry = next((record for record in journal.get('clients', []) if record.get('relative') == client), {})
        if (journal.get('schema') != 1 or journal.get('creator') != CREATOR or journal.get('root') != str(Path(root).absolute())
                or journal.get('backup') != backup or journal.get('overlay_id') != OVERLAY_ID
                or journal.get('status') not in ('applying', 'applied')
                or digests(safe(folder, PROOF)) != checksum(entry.get('effective_proof_sha256', entry.get('applied_proof_sha256')))):
            raise ValueError('Installed city overlay provenance differs from its private journal')
    return proof


def refresh_settings(root=ROOT):
    """Accept only safe preferences, without changing either actual config file."""
    root = Path(root).absolute()
    with settings_lock(root):
        digests = InvocationDigests()
        clients = []
        for relative in CLIENTS:
            proof = verify_client(root, relative, allow_settings_changes=True, digests=digests)
            folder = own_client(root, relative)
            rows = {row['path']: row for row in proof['files']}
            changes = {}
            for name in SETTINGS_FILES:
                data = safe(folder, name).read_bytes()
                validate_settings(data)
                pin = hashlib.sha256(data).hexdigest()
                if name not in rows:
                    raise ValueError('Settings resource is absent from provenance')
                if (rows[name]['sha256'], rows[name]['size']) != (pin, len(data)):
                    changes[name] = dict(sha256=pin, size=len(data))
            clients.append(dict(relative=relative, proof=proof, changes=changes))
        changed = [row for row in clients if row['changes']]
        if not changed:
            return dict(status='settings_unchanged', clients=list(CLIENTS), network_requests=0,
                        hash_reads=digests.hash_reads, physical_file_cache_hits=digests.cache_hits)
        backups = {row['proof'].get(OVERLAY_KEY, {}).get('backup') for row in clients}
        if len(backups) != 1 or None in backups:
            raise ValueError('Settings reconciliation requires a common installed city overlay')
        backup = backups.pop()
        backup_folder = safe(root, backup)
        journal_path = safe(backup_folder, 'install.json')
        journal_bytes = journal_path.read_bytes()
        journal = json.loads(journal_bytes)
        if journal.get('status') != 'applied':
            raise ValueError('Settings reconciliation requires a completed city installation')
        staged = []
        for client in changed:
            folder = own_client(root, client['relative'])
            proof_bytes = safe(folder, PROOF).read_bytes()
            updated = json.loads(proof_bytes)
            for row in updated['files']:
                if row['path'] in client['changes']:
                    row.update(client['changes'][row['path']])
            new_bytes = data_json(updated)
            entry = next(row for row in journal['clients'] if row['relative'] == client['relative'])
            filename = Path(client['relative']).name + '/settings-provenance-' + uuid4().hex + '.json'
            atomic(safe(backup_folder, filename), data=new_bytes)
            entry['effective_proof'] = filename
            entry['effective_proof_sha256'] = hashlib.sha256(new_bytes).hexdigest()
            entry.setdefault('accepted_settings', {}).update(client['changes'])
            staged.append((folder, proof_bytes, new_bytes, client['changes']))
        try:
            # Revalidate all immutable files and the old, still active proofs.
            for relative in CLIENTS:
                verify_client(root, relative, allow_settings_changes=True, digests=digests)
            for folder, before, after, changes in staged:
                if safe(folder, PROOF).read_bytes() != before:
                    raise ValueError('Client provenance changed during settings verification')
                for name, expected in changes.items():
                    if not matches(safe(folder, name), expected['sha256'], expected['size']):
                        raise ValueError('Settings changed during their verification; retry')
                atomic(safe(folder, PROOF), data=after)
            atomic(journal_path, data=data_json(journal))
            for relative in CLIENTS:
                verify_client(root, relative, digests=digests)
        except Exception:
            for folder, before, after, changes in staged:
                current = safe(folder, PROOF).read_bytes()
                if current == after:
                    atomic(safe(folder, PROOF), data=before)
            atomic(journal_path, data=journal_bytes)
            raise
        return dict(status='settings_verified', clients=[row['relative'] for row in changed],
                    changed_files=sum(len(row['changes']) for row in changed), config_files_written=0, network_requests=0)


def package(root, *, digests=None):
    hashes = digests or digest
    folder = safe(root, PACKAGE)
    manifest_path = safe(folder, 'overlay-manifest.json')
    manifest = read_json(manifest_path)
    if manifest.get('schema') != 1 or manifest.get('overlay_id') != OVERLAY_ID:
        raise ValueError('Unsupported city overlay manifest')
    records = manifest.get('files')
    if (not isinstance(records, list) or len(records) != len(FILES)
            or {row.get('path') for row in records if isinstance(row, dict)} != FILES):
        raise ValueError('City overlay must contain precisely the five reviewed resources')
    for row in records:
        checksum(row.get('sha256'))
        size(row.get('size'))
        before = row.get('before_sha256')
        if before is None:
            if row.get('before_size') is not None or row['path'] == 'silver.dll':
                raise ValueError('Native city patch requires a supported source pin')
        else:
            checksum(before)
            size(row.get('before_size'))
        if not matches(safe(folder, row['path']), row['sha256'], row['size'], digests=digests):
            raise ValueError('City runtime package changed: ' + row['path'])
    silver = next(row for row in records if row['path'] == 'silver.dll')
    pins = manifest.get('native_pins', {}).get('silver.dll', {})
    plan_path = safe(root, PLAN)
    plan = read_json(plan_path)
    if (pins != dict(before_sha256=silver['before_sha256'], after_sha256=silver['sha256'])
            or plan.get('source_sha256') != silver['before_sha256']
            or plan.get('payload_sha256') != silver['sha256']):
        raise ValueError('Unsupported native binary or city patch plan mismatch')
    return manifest, hashes(manifest_path), hashes(plan_path)


def source_identity(root, manifest):
    origin = safe(root, SOURCE)
    return {row['path']: identity(safe(origin, row['path'])) for row in manifest['files']
            if row['before_sha256'] is not None}


def _preflight(root):
    manifest, manifest_hash, plan_hash = package(root)
    clients = []
    for client in CLIENTS:
        proof = verify_client(root, client)
        overlay = proof.get(OVERLAY_KEY)
        if overlay:
            if (overlay.get('creator') != CREATOR or overlay.get('overlay_id') != OVERLAY_ID
                    or overlay.get('manifest_sha256') != manifest_hash or overlay.get('patch_plan_sha256') != plan_hash):
                raise ValueError('A different city overlay is already installed')
            for row in manifest['files']:
                managed = next((entry for entry in proof['files'] if entry['path'] == row['path']), {})
                if (managed.get('sha256'), managed.get('size'), managed.get('method')) != (row['sha256'], row['size'], 'private_city_overlay'):
                    raise ValueError('Installed city overlay provenance differs from its package')
        else:
            rows = {entry['path']: entry for entry in proof['files']}
            for row in manifest['files']:
                destination = safe(own_client(root, client), row['path'])
                if row['before_sha256'] is None:
                    if row['path'] in rows or destination.exists():
                        raise ValueError('Refuse to replace an unowned new city resource: ' + row['path'])
                else:
                    prior = rows.get(row['path'], {})
                    if (prior.get('sha256'), prior.get('size')) != (row['before_sha256'], row['before_size']):
                        raise ValueError('Unsupported client binary/resource before the city patch: ' + row['path'])
        clients.append(dict(relative=client, proof=proof, installed=bool(overlay)))
    if len({row['installed'] for row in clients}) != 1:
        raise ValueError('Client overlays disagree; roll back the recorded incomplete installation first')
    return manifest, manifest_hash, plan_hash, clients


def prepare(root=ROOT, *, dry_run=False):
    root = Path(root).absolute()
    manifest, manifest_hash, plan_hash, clients = _preflight(root)
    if clients[0]['installed']:
        return dict(status='already_installed', overlay_id=OVERLAY_ID,
                    clients=list(CLIENTS), backup=clients[0]['proof'][OVERLAY_KEY]['backup'], network_requests=0)
    source_before = source_identity(root, manifest)
    if dry_run:
        return dict(status='ready', overlay_id=OVERLAY_ID, clients=list(CLIENTS),
                    files=[row['path'] for row in manifest['files']], network_requests=0)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:12]
    backup_relative = BACKUPS + '/' + stamp
    backup_folder = safe(root, backup_relative)
    backup_folder.mkdir(parents=True, exist_ok=False)
    journal = dict(schema=1, creator=CREATOR, root=str(root), backup=backup_relative, overlay_id=OVERLAY_ID,
                   status='prepared', manifest=manifest, manifest_sha256=manifest_hash,
                   patch_plan_sha256=plan_hash, source_identity_before=source_before, clients=[])
    for client in clients:
        relative, proof = client['relative'], client['proof']
        folder = own_client(root, relative)
        suffix = Path(relative).name
        original = safe(folder, PROOF).read_bytes()
        saved_proof = safe(backup_folder, suffix + '/original-provenance.json')
        atomic(saved_proof, data=original)
        files = []
        for row in manifest['files']:
            entry = dict(row)
            entry['backup_file'] = None
            if row['before_sha256'] is not None:
                entry['backup_file'] = suffix + '/files/' + row['path']
                saved = safe(backup_folder, entry['backup_file'])
                atomic(saved, source=safe(folder, row['path']))
                if not matches(saved, row['before_sha256'], row['before_size']) or saved.stat().st_nlink != 1:
                    raise ValueError('City overlay private backup verification failed')
            files.append(entry)
        updated = json.loads(json.dumps(proof))
        by_path = {entry['path']: entry for entry in updated['files']}
        for row in manifest['files']:
            prior = by_path.get(row['path'])
            record = dict(path=row['path'], sha256=row['sha256'], size=row['size'],
                          source_sha256=prior.get('source_sha256') if prior else None,
                          method='private_city_overlay')
            by_path[row['path']] = record
        updated['files'] = list(by_path.values())
        updated['resources'] = len(updated['files'])
        updated['methods'] = dict(Counter(entry['method'] for entry in updated['files']))
        updated[OVERLAY_KEY] = dict(schema=1, creator=CREATOR, overlay_id=OVERLAY_ID,
                                  manifest_sha256=manifest_hash, patch_plan_sha256=plan_hash,
                                  backup=backup_relative, installed_utc=datetime.now(timezone.utc).isoformat(),
                                  files=[row['path'] for row in manifest['files']])
        applied = data_json(updated)
        atomic(safe(backup_folder, suffix + '/applied-provenance.json'), data=applied)
        journal['clients'].append(dict(relative=relative, files=files,
                                       original_proof=suffix + '/original-provenance.json',
                                       applied_proof=suffix + '/applied-provenance.json',
                                       original_proof_sha256=hashlib.sha256(original).hexdigest(),
                                       applied_proof_sha256=hashlib.sha256(applied).hexdigest()))
    journal_path = safe(backup_folder, 'install.json')
    atomic(journal_path, data=data_json(journal))
    try:
        # Recheck the complete inventory after the backups and before mutation.
        _preflight(root)
        journal['status'] = 'applying'
        atomic(journal_path, data=data_json(journal))
        for client in journal['clients']:
            folder = own_client(root, client['relative'])
            for row in client['files']:
                destination = safe(folder, row['path'])
                if row['before_sha256'] is None:
                    if destination.exists():
                        raise ValueError('New city texture appeared during installation')
                elif not matches(destination, row['before_sha256'], row['before_size']):
                    raise ValueError('Client resource changed during installation')
                atomic(destination, source=safe(safe(root, PACKAGE), row['path']))
                if not matches(destination, row['sha256'], row['size']) or destination.stat().st_nlink != 1:
                    raise ValueError('City overlay replacement verification failed')
            atomic(safe(folder, PROOF), source=safe(backup_folder, client['applied_proof']))
        for relative in CLIENTS:
            verify_client(root, relative)
        source_after = source_identity(root, manifest)
        if source_after != source_before:
            raise ValueError('Source QA file identity changed during city overlay installation')
        journal.update(status='applied', source_identity_after=source_after)
        atomic(journal_path, data=data_json(journal))
    except Exception:
        rollback(root, backup=backup_relative)
        raise
    return dict(status='installed', overlay_id=OVERLAY_ID, clients=list(CLIENTS), backup=backup_relative,
                source_hashes_and_inodes_preserved=True, files=len(FILES), network_requests=0)


def rollback(root=ROOT, *, backup=None):
    root = Path(root).absolute()
    if backup is None:
        active = [read_json(safe(own_client(root, client), PROOF)).get(OVERLAY_KEY, {}) for client in CLIENTS]
        if not any(active):
            return dict(status='not_installed', clients=list(CLIENTS), network_requests=0)
        if any(entry.get('creator') != CREATOR for entry in active) or len({entry.get('backup') for entry in active}) != 1:
            raise ValueError('No common owned city overlay backup')
        backup = active[0]['backup']
    if not isinstance(backup, str) or not re.fullmatch(re.escape(BACKUPS) + r'/[0-9]{8}T[0-9]{6}-[a-f0-9]{12}', backup):
        raise ValueError('Unsafe city overlay backup path')
    backup_folder = safe(root, backup)
    journal_path = safe(backup_folder, 'install.json')
    journal = read_json(journal_path)
    if (journal.get('schema') != 1 or journal.get('creator') != CREATOR or journal.get('root') != str(root)
            or journal.get('backup') != backup or journal.get('overlay_id') != OVERLAY_ID
            or {entry.get('relative') for entry in journal.get('clients', [])} != set(CLIENTS)
            or len(journal['clients']) != len(CLIENTS)):
        raise ValueError('Unowned city overlay backup journal')
    pending = []
    # Validate every client/source/backup before restoring any of the two clients.
    for client in journal['clients']:
        folder = own_client(root, client['relative'])
        original_path = safe(backup_folder, client['original_proof'])
        applied_path = safe(backup_folder, client['applied_proof'])
        if (digest(original_path) != checksum(client['original_proof_sha256'])
                or digest(applied_path) != checksum(client['applied_proof_sha256'])):
            raise ValueError('City overlay provenance backup changed')
        if digest(safe(folder, PROOF)) not in (client['original_proof_sha256'], client['applied_proof_sha256'], client.get('effective_proof_sha256')):
            raise ValueError('Client provenance changed after city overlay installation')
        original = read_json(original_path)
        rows = proof_records(original, folder)
        verify_source(root, original, rows)
        accepted = client.get('accepted_settings', {})
        if accepted:
            if not isinstance(accepted, dict) or not accepted.keys() <= SETTINGS_FILES:
                raise ValueError('Backup journal contains unsupported reconciled settings')
            effective_path = safe(backup_folder, client['effective_proof'])
            if digest(effective_path) != checksum(client['effective_proof_sha256']):
                raise ValueError('Reconciled settings provenance backup changed')
            effective = {row['path']: row for row in read_json(effective_path)['files']}
            for name, accepted_row in accepted.items():
                current = safe(folder, name)
                validate_settings(current.read_bytes())
                if (not matches(current, checksum(accepted_row['sha256']), size(accepted_row['size']))
                        or (effective.get(name, {}).get('sha256'), effective.get(name, {}).get('size')) != (accepted_row['sha256'], accepted_row['size'])):
                    raise ValueError('Reconciled settings changed; rollback refused')
                rows[name].update(accepted_row)
        replacements = {row['path']: row for row in client['files']}
        if len(replacements) != len(FILES) or set(replacements) != FILES:
            raise ValueError('Backup journal contains unsupported city overlay files')
        for row in rows.values():
            destination = safe(folder, row['path'])
            replacement = replacements.get(row['path'])
            if not replacement:
                if not matches(destination, row['sha256'], row['size']):
                    raise ValueError('Unrelated client resource changed; rollback refused: ' + row['path'])
            elif (row['sha256'], row['size']) != (replacement['before_sha256'], replacement['before_size']):
                raise ValueError('Original provenance differs from backup journal')
        actions = []
        for row in replacements.values():
            checksum(row['sha256'])
            size(row['size'])
            destination = safe(folder, row['path'])
            if row['before_sha256'] is not None:
                saved = safe(backup_folder, row['backup_file'])
                if not matches(saved, checksum(row['before_sha256']), size(row['before_size'])) or saved.stat().st_nlink != 1:
                    raise ValueError('City overlay resource backup changed')
                if matches(destination, row['before_sha256'], row['before_size']):
                    continue
                if not matches(destination, row['sha256'], row['size']):
                    raise ValueError('Modified city resource changed; rollback refused: ' + row['path'])
                actions.append((destination, saved))
            elif destination.exists():
                if row['path'] in rows or not matches(destination, row['sha256'], row['size']):
                    raise ValueError('New city resource changed; rollback refused: ' + row['path'])
                actions.append((destination, None))
        restore_proof = data_json(original) if accepted else original_path.read_bytes()
        pending.append((folder, restore_proof, actions))
    for folder, restore_proof, actions in pending:
        for destination, saved in actions:
            if saved is None:
                destination.unlink()
            else:
                atomic(destination, source=saved)
        atomic(safe(folder, PROOF), data=restore_proof)
        verify_client(root, folder.relative_to(root).as_posix())
    journal['status'] = 'rolled_back'
    journal['rolled_back_utc'] = datetime.now(timezone.utc).isoformat()
    atomic(journal_path, data=data_json(journal))
    return dict(status='rolled_back', overlay_id=OVERLAY_ID, clients=list(CLIENTS), backup=backup, network_requests=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    parser.add_argument('--refresh-settings', action='store_true', help='Verify safe preferences and record hashes without writing config files')
    parser.add_argument('--install-launchers', action='store_true', help='Install the guarded local native-multi launcher in both owned clients')
    parser.add_argument('--backup', help='Explicit owned journal for an interrupted installation')
    options = parser.parse_args()
    if (options.backup and not options.rollback or options.rollback and options.dry_run
            or options.refresh_settings and (options.rollback or options.dry_run or options.backup or options.install_launchers)
            or options.install_launchers and (options.rollback or options.dry_run or options.backup)):
        parser.error('--backup requires --rollback; --refresh-settings and --rollback cannot be combined with other actions')
    result = (install_launchers(options.root) if options.install_launchers else
              refresh_settings(options.root) if options.refresh_settings else
              rollback(options.root, backup=options.backup) if options.rollback else prepare(options.root, dry_run=options.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
