"""Read-only process/TCP continuity proof for explicitly identified owned A/B QA.

Uses QUERY_LIMITED_INFORMATION process handles, Toolhelp metadata, disk hashes,
and Get-NetTCPConnection. No process memory access, attachment, game calls,
window operations, packets, remote requests, process control, or publication.
The module-file hash identifies the mapped file, not its in-memory text bytes.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess


ROOT = Path(__file__).resolve().parents[1]
QA_ROOT = ROOT / 'reports/arena-surroundings-implementation/client-qa'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
# Exact owned revision3 QA executable; documented by its independent route proof.
LAUNCHER_SHA = '2e3372ec3009e3e10f69d3a2d0afc821e3f59dfb3c5c64121fd1450724a3264a'
LAUNCHER_PATH = ROOT / 'reports/gameplay-followup/stage1-interfaces/graphical-adapter-revision3/bin/TIO Launcher.exe'
FILETIME_EPOCH = 116444736000000000
EXCLUDED_USER_PID = 5812


def require(value, message):
    if not value:
        raise ValueError(message)


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def utc_filetime(value):
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,7}))?(?:Z|\+00:00)', value)
    require(match, 'Expected UTC creation timestamp with up to seven fractional digits')
    dt = datetime.strptime(match[1], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
    return int(dt.timestamp()) * 10000000 + FILETIME_EPOCH + int((match[2] or '').ljust(7, '0'))


def filetime_utc(value):
    seconds, ticks = divmod(value - FILETIME_EPOCH, 10000000)
    dt = datetime.fromtimestamp(seconds, timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + f'.{ticks:07d}Z'


def file_identity(path):
    path = Path(path).resolve()
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
            'Mapped file changed while hashing: ' + str(path))
    require(len(data) == before.st_size, 'Mapped file size changed: ' + str(path))
    require(data[:2] == b'MZ', 'Expected PE image: ' + str(path))
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    require(data[pe:pe+4] == b'PE\0\0', 'Expected PE signature: ' + str(path))
    image_size = struct.unpack_from('<I', data, pe + 24 + 56)[0]
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'size_of_image': image_size, 'mtime_ns': before.st_mtime_ns}


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD), ('pid', wintypes.DWORD),
                ('heap', ctypes.c_size_t), ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG), ('flags', wintypes.DWORD),
                ('name', wintypes.WCHAR * 260)]


class ModuleEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('module_id', wintypes.DWORD), ('pid', wintypes.DWORD),
                ('global_usage', wintypes.DWORD), ('process_usage', wintypes.DWORD),
                ('base', ctypes.c_void_p), ('image_size', wintypes.DWORD), ('handle', wintypes.HMODULE),
                ('name', wintypes.WCHAR * 256), ('path', wintypes.WCHAR * 260)]


def kernel_api():
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GetProcessId.argtypes = [wintypes.HANDLE]
    k.GetProcessId.restype = wintypes.DWORD
    k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.DWORD)]
    k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    k.Module32FirstW.argtypes = k.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ModuleEntry)]
    return k


def parent_ids(k, pids):
    snapshot = k.CreateToolhelp32Snapshot(2, 0)
    require(snapshot not in (None, ctypes.c_void_p(-1).value), 'Process metadata snapshot failed')
    found = {}
    try:
        row = ProcessEntry(); row.size = ctypes.sizeof(row)
        more = k.Process32FirstW(snapshot, ctypes.byref(row))
        while more:
            if row.pid in pids:
                found[row.pid] = row.parent
            more = k.Process32NextW(snapshot, ctypes.byref(row))
    finally:
        k.CloseHandle(snapshot)
    require(set(found) == set(pids), 'An explicitly identified owned process is unavailable')
    return found


def module_metadata(k, pid):
    snapshot = k.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    require(snapshot not in (None, ctypes.c_void_p(-1).value), 'Module metadata snapshot failed')
    found = {}
    try:
        row = ModuleEntry(); row.size = ctypes.sizeof(row)
        more = k.Module32FirstW(snapshot, ctypes.byref(row))
        while more:
            if row.name.lower() in ('ti.exe', 'silver.dll'):
                found[row.name.lower()] = {'path': str(Path(row.path).resolve()),
                                           'base_address': hex(row.base), 'image_size': row.image_size}
            more = k.Module32NextW(snapshot, ctypes.byref(row))
    finally:
        k.CloseHandle(snapshot)
    require(set(found) == {'ti.exe', 'silver.dll'}, 'Required owned native modules are unavailable')
    return found


def handle_metadata(k, handle, pid):
    require(k.GetProcessId(handle) == pid, 'Opened handle PID mismatch')
    code = wintypes.DWORD()
    require(k.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259,
            'Owned process has exited')
    created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
    require(k.GetProcessTimes(handle, *map(ctypes.byref, (created, exited, kernel, user))),
            'Owned process creation metadata unavailable')
    stamp = created.dwLowDateTime | created.dwHighDateTime << 32
    path = ctypes.create_unicode_buffer(32768); size = wintypes.DWORD(len(path))
    require(k.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)),
            'Owned process executable metadata unavailable')
    return {'process_id': pid, 'path': str(Path(path.value).resolve()),
            'creation_filetime': stamp, 'creation_date_utc': filetime_utc(stamp)}


def validate_manifest(manifest):
    require(manifest.get('schema') == 1, 'Expected continuity manifest schema 1')
    require(re.fullmatch('[0-9a-f]{64}', manifest.get('native_candidate_sha256', '')),
            'Explicit expected Silver SHA256 is required')
    pairs = manifest.get('owned_pairs', [])
    require(len(pairs) == 2 and {p.get('label') for p in pairs} == {'game-a', 'game-b'},
            'Exactly the two owned game-a/game-b pairs are required')
    pids = []
    for pair in pairs:
        for kind in ('native', 'bridge'):
            pid = pair.get(kind + '_pid')
            require(isinstance(pid, int) and pid > 0 and pid != EXCLUDED_USER_PID,
                    'Invalid or excluded process PID')
            pids.append(pid)
            ft = pair.get(kind + '_creation_filetime')
            if ft is not None:
                require(isinstance(ft, int) and ft > FILETIME_EPOCH, 'Expected positive creation FILETIME')
            else:
                utc_filetime(pair.get(kind + '_creation_utc', ''))
                require(pair.get('creation_precision') == 'microsecond',
                        'UTC metadata from CIM must explicitly declare microsecond precision')
    require(len(set(pids)) == 4, 'Owned process PIDs must be unique')
    return pairs, set(pids)


def expected_creation(pair, kind, observed):
    expected = pair.get(kind + '_creation_filetime')
    if expected is not None:
        require(observed == expected, 'Exact expected process FILETIME mismatch')
    else:
        expected = utc_filetime(pair[kind + '_creation_utc'])
        require(observed // 10 == expected // 10, 'Expected CIM process creation microsecond mismatch')


def tcp_metadata(pids):
    # Only validated integer PIDs enter the fixed PowerShell metadata query.
    ids = ','.join(map(str, sorted(pids)))
    script = "$ErrorActionPreference='Stop'; $ids=@(" + ids + "); @(" + """
        Get-NetTCPConnection | Where-Object { $_.OwningProcess -in $ids } |
        ForEach-Object { [ordered]@{
            process_id=[int]$_.OwningProcess; state=$_.State.ToString();
            local_address=$_.LocalAddress; local_port=[int]$_.LocalPort;
            remote_address=$_.RemoteAddress; remote_port=[int]$_.RemotePort;
            creation_date_utc=$_.CreationTime.ToUniversalTime().ToString('o')
        } }
    ) | ConvertTo-Json -Depth 5 -Compress
    """
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, timeout=30, check=True)
    rows = json.loads(result.stdout)
    require(isinstance(rows, list), 'Expected TCP metadata array')
    require(all(row['process_id'] in pids for row in rows), 'TCP metadata contains an unowned PID')
    return sorted(rows, key=lambda r: (r['process_id'], r['state'], r['local_address'], r['local_port'],
                                      r['remote_address'], r['remote_port']))


def established_key(row):
    return tuple(row[k] for k in ('process_id', 'local_address', 'local_port', 'remote_address',
                                 'remote_port', 'creation_date_utc'))


def validate_topology(report):
    pairs = report['owned_pairs']
    rows = [r for r in report['tcp'] if r['state'] == 'Established']
    require(len(rows) == 6 and len({established_key(r) for r in rows}) == 6,
            'Expected six unique established owned TCP endpoints')
    for pair in pairs:
        native = [r for r in rows if r['process_id'] == pair['native_pid']]
        bridge = [r for r in rows if r['process_id'] == pair['bridge_pid']]
        require(len(native) == 1 and len(bridge) == 2, 'Expected one native/two bridge established endpoints')
        n = native[0]
        require(n['local_address'] == n['remote_address'] == '127.0.0.1', 'Expected owned native loopback transport')
        reverse = [r for r in bridge if r['local_address'] == n['remote_address']
                   and r['remote_address'] == n['local_address'] and r['local_port'] == n['remote_port']
                   and r['remote_port'] == n['local_port']]
        require(len(reverse) == 1, 'Native TCP socket does not pair with its expected parent bridge')
        public = [r for r in bridge if r['remote_address'] == '185.184.42.88' and r['remote_port'] == 29513]
        require(len(public) == 1, 'Expected hosted session transport endpoint is unavailable')
        require(reverse[0]['creation_date_utc'] == n['creation_date_utc'], 'Loopback endpoint creation mismatch')
    return rows


def capture(manifest):
    pairs, pids = validate_manifest(manifest)
    sha = manifest['native_candidate_sha256']
    launcher = file_identity(LAUNCHER_PATH)
    require(launcher['sha256'] == LAUNCHER_SHA, 'Unknown reviewed owned launcher')
    files = {}
    for pair in pairs:
        root = (QA_ROOT / pair['label']).resolve()
        marker = json.loads((root / '.tio-owned-qa').read_text(encoding='utf-8-sig'))
        require(marker.get('schema') == 1 and marker.get('creator') == 'tools/prepare_hosted_graphical_qa.py'
                and path_key(marker.get('root', '')) == path_key(root), 'Owned root marker mismatch')
        ti, silver = file_identity(root / 'ti.exe'), file_identity(root / 'silver.dll')
        require(ti['sha256'] == TI_SHA and silver['sha256'] == sha, 'Owned native disk file hash mismatch')
        files[pair['label']] = (ti, silver)
    k = kernel_api(); handles = {}; first = {}; modules = {}
    parents = parent_ids(k, pids)
    try:
        for pair in pairs:
            require(parents[pair['native_pid']] == pair['bridge_pid'], 'Owned native/bridge parent mismatch')
            for kind in ('native', 'bridge'):
                pid = pair[kind + '_pid']
                h = k.OpenProcess(0x1000, False, pid)  # Metadata only; no VM_READ/WRITE/operation/control.
                require(h, 'Cannot open explicitly identified owned process metadata handle')
                handles[pid] = h
                row = handle_metadata(k, h, pid)
                expected_creation(pair, kind, row['creation_filetime'])
                exe = files[pair['label']][0] if kind == 'native' else launcher
                require(path_key(row['path']) == path_key(exe['path']), 'Exact owned executable path mismatch')
                row.update(parent_process_id=parents[pid], executable_sha256=exe['sha256'],
                           executable_bytes=exe['bytes'], role=kind, label=pair['label'])
                if kind == 'native':
                    mapped = module_metadata(k, pid); modules[pid] = mapped
                    ti, silver = files[pair['label']]
                    for name, disk in (('ti.exe', ti), ('silver.dll', silver)):
                        require(path_key(mapped[name]['path']) == path_key(disk['path'])
                                and mapped[name]['image_size'] == disk['size_of_image'], 'Mapped module metadata mismatch')
                    require(mapped['ti.exe']['base_address'] == '0x400000', 'Unexpected native TI base')
                    row['silver'] = [{**silver, **mapped['silver.dll']}]
                    row['native_module'] = mapped['ti.exe']
                first[pid] = row
        tcp = tcp_metadata(pids)
        # Handles remain open across TCP collection. Recheck identities and files before publishing evidence.
        require(parent_ids(k, pids) == parents, 'Owned parent identities changed during capture')
        for pid, h in handles.items():
            require(handle_metadata(k, h, pid) == {key: first[pid][key] for key in
                    ('process_id', 'path', 'creation_filetime', 'creation_date_utc')},
                    'Owned process exited or changed during TCP capture')
            if pid in modules:
                require(module_metadata(k, pid) == modules[pid], 'Loaded module identities changed during capture')
        require(file_identity(LAUNCHER_PATH) == launcher, 'Owned launcher file changed during capture')
        for ti, silver in files.values():
            require(file_identity(ti['path']) == ti and file_identity(silver['path']) == silver,
                    'Owned native files changed during capture')
    finally:
        for h in handles.values():
            k.CloseHandle(h)
    report = {'schema': 1, 'creator': 'tools/verify_owned_ui_connection_continuity.py',
              'captured_utc': datetime.now(timezone.utc).isoformat(), 'native_candidate_sha256': sha,
              'owned_pairs': [{key: p[key] for key in ('label', 'native_pid', 'bridge_pid')} for p in pairs],
              'processes': [first[pid] for pid in sorted(first)], 'tcp': tcp, 'excluded_user_pid': EXCLUDED_USER_PID,
              'passed': True, 'processes_written': False, 'remote_mutations': 0, 'network_requests': 0,
              'process_memory_read': False, 'debugger_attached': False, 'native_handlers_invoked': False,
              'window_operations': False, 'candidate_publish_allowed': False,
              'method': {'process_rights': '0x1000 QUERY_LIMITED_INFORMATION',
                         'creation_guard': 'explicit expected creation; exact handle FILETIME stable across capture',
                         'module_identity': 'Toolhelp path/base/SizeOfImage plus byte SHA256 of stable disk file',
                         'in_memory_module_text_sha_verified': False,
                         'tcp': 'read-only Get-NetTCPConnection metadata',
                         'native_auth_fields_read': False, 'rendering_verified': False}}
    validate_topology(report)
    report['validation'] = {'established_tcp_tuples': 6, 'owned_parent_pairs_exact': True,
                            'loaded_silver_file_identities_exact': True,
                            'exact_process_filetimes_retained_for_after_compare': True}
    return report


def process_identity(row):
    creation = row.get('creation_filetime', row['creation_date_utc'])
    silver = tuple(sorted((path_key(m['path']), m['sha256'], m['bytes'], m['base_address']) for m in row.get('silver', [])))
    return (row['process_id'], row['parent_process_id'], path_key(row.get('path', row.get('executable_path'))), creation,
            row.get('executable_sha256'), silver, row.get('native_module'), row.get('start_time_utc'))


def validate_saved_identities(report):
    sha = report.get('native_candidate_sha256', '')
    require(re.fullmatch('[0-9a-f]{64}', sha), 'Expected captured candidate SHA256')
    pairs = report.get('owned_pairs', [])
    require(len(pairs) == 2 and {p['label'] for p in pairs} == {'game-a', 'game-b'},
            'Expected two named owned pairs')
    pids = [p[k] for p in pairs for k in ('native_pid', 'bridge_pid')]
    require(len(set(pids)) == 4 and all(type(p) is int and p > 0 and p != EXCLUDED_USER_PID for p in pids),
            'Invalid, duplicated, or excluded owned capture PID')
    processes = report.get('processes', [])
    require(len(processes) == 4 and {r['process_id'] for r in processes} == set(pids),
            'Expected exact captured owned process identities')
    by_pid = {r['process_id']: r for r in processes}
    for pair in pairs:
        native, bridge = by_pid[pair['native_pid']], by_pid[pair['bridge_pid']]
        require(native['parent_process_id'] == pair['bridge_pid'], 'Captured native parent is not its owned bridge')
        for row, expected in ((native, QA_ROOT / pair['label'] / 'ti.exe'), (bridge, LAUNCHER_PATH)):
            require(path_key(row.get('path', row.get('executable_path'))) == path_key(expected),
                    'Captured executable path does not identify the owned QA pair')
            utc_filetime(row['creation_date_utc'])
        silver = native.get('silver', [])
        require(len(silver) == 1 and silver[0]['sha256'] == sha
                and path_key(silver[0]['path']) == path_key(QA_ROOT / pair['label'] / 'silver.dll'),
                'Captured owned Silver identity does not match its candidate SHA/path')


def compare(before, after):
    require(before.get('passed') is True and after.get('passed') is True, 'Both captures must pass their guards')
    validate_saved_identities(before); validate_saved_identities(after)
    b_rows, a_rows = validate_topology(before), validate_topology(after)
    require(before['native_candidate_sha256'] == after['native_candidate_sha256'], 'Candidate SHA changed')
    pair_key = lambda pair: (pair['label'], pair['native_pid'], pair['bridge_pid'])
    require(sorted(map(pair_key, before['owned_pairs'])) == sorted(map(pair_key, after['owned_pairs'])),
            'Owned process pair identities changed')
    require(len(before['processes']) == len(after['processes']) == 4, 'Expected exact four process identities')
    require(sorted(map(process_identity, before['processes']), key=lambda r: r[0])
            == sorted(map(process_identity, after['processes']), key=lambda r: r[0]),
            'Owned process/creation/path/loaded-file identity changed')
    require({established_key(r) for r in b_rows} == {established_key(r) for r in a_rows},
            'Established TCP endpoints or exact connection creation times changed')
    return {'established_tcp_tuples_preserved': 6, 'exact_tcp_creation_times_preserved': True,
            'exact_four_process_identities_preserved': True, 'native_paths_and_silver_sha_preserved': True,
            'client_restarted': False, 'observed_connection_recreated': False,
            'scope': 'Snapshots prove endpoint/process continuity; rendering/authentication are separate evidence.'}


def self_test():
    before = json.loads((ROOT / 'reports/ui-modernization/graphical/connection-before-af023ada.json').read_text(encoding='utf-8-sig'))
    after = json.loads((ROOT / 'reports/ui-modernization/graphical/connection-after-af023ada.json').read_text(encoding='utf-8-sig'))
    compare(before, after)
    checks = ['saved valid AF before/after']
    edits = [
        ('PID reuse', lambda r: r['processes'][0].update(creation_date_utc='2026-10-09T18:00:00.0000000Z')),
        ('native path drift', lambda r: r['processes'][0].update(path='C:/unowned/ti.exe')),
        ('Silver hash drift', lambda r: next(p for p in r['processes'] if p.get('silver'))['silver'][0].update(sha256='0'*64)),
        ('Silver module base drift', lambda r: next(p for p in r['processes'] if p.get('silver'))['silver'][0].update(base_address='0x10000000')),
        ('candidate hash drift', lambda r: r.update(native_candidate_sha256='0'*64)),
        ('bridge parent drift', lambda r: r['processes'][1].update(parent_process_id=1)),
        ('TCP recreation', lambda r: next(t for t in r['tcp'] if t['state']=='Established').update(creation_date_utc='2026-10-09T18:00:00.0000000Z')),
        ('TCP local port drift', lambda r: next(t for t in r['tcp'] if t['state']=='Established').update(local_port=1)),
        ('hosted endpoint drift', lambda r: next(t for t in r['tcp'] if t['remote_address']=='185.184.42.88').update(remote_port=29514)),
        ('missing socket', lambda r: r['tcp'].remove(next(t for t in r['tcp'] if t['state']=='Established'))),
        ('duplicated socket', lambda r: r['tcp'].append(copy.deepcopy(next(t for t in r['tcp'] if t['state']=='Established')))),
        ('missing process', lambda r: r['processes'].pop()),
        ('unpassed capture', lambda r: r.update(passed=False)),
    ]
    for name, edit in edits:
        changed = copy.deepcopy(after); edit(changed)
        try:
            compare(before, changed)
        except ValueError:
            checks.append('reject ' + name)
        else:
            raise AssertionError('Comparator accepted ' + name)
    manifest = {'schema': 1, 'native_candidate_sha256': before['native_candidate_sha256'],
                'owned_pairs': []}
    by_pid = {r['process_id']: r for r in before['processes']}
    for pair in before['owned_pairs']:
        manifest['owned_pairs'].append({**pair, 'creation_precision': 'microsecond',
            **{kind+'_creation_utc': by_pid[pair[kind+'_pid']]['creation_date_utc'] for kind in ('native','bridge')}})
    validate_manifest(manifest); checks.append('valid explicit two-pair manifest')
    manifest_edits = [
        ('excluded user PID', lambda m: m['owned_pairs'][0].update(native_pid=EXCLUDED_USER_PID)),
        ('negative PID', lambda m: m['owned_pairs'][0].update(native_pid=-1)),
        ('duplicated PID', lambda m: m['owned_pairs'][0].update(native_pid=m['owned_pairs'][0]['bridge_pid'])),
        ('unowned root label', lambda m: m['owned_pairs'][0].update(label='game-user')),
        ('unknown candidate hash', lambda m: m.update(native_candidate_sha256='unknown')),
        ('missing process creation', lambda m: m['owned_pairs'][0].pop('native_creation_utc')),
        ('ambiguous UTC precision', lambda m: m['owned_pairs'][0].pop('creation_precision')),
        ('malformed UTC creation', lambda m: m['owned_pairs'][0].update(native_creation_utc='today')),
    ]
    for name, edit in manifest_edits:
        changed = copy.deepcopy(manifest); edit(changed)
        try:
            validate_manifest(changed)
        except ValueError:
            checks.append('reject ' + name + ' before opening handles')
        else:
            raise AssertionError('Manifest accepted ' + name)
    ft = utc_filetime('2026-10-09T17:37:37.3366223Z')
    assert filetime_utc(ft) == '2026-10-09T17:37:37.3366223Z'
    checks.append('100ns FILETIME exact UTC round trip')
    expected_creation(manifest['owned_pairs'][0], 'native', ft)
    checks.append('CIM microsecond expectation accepts exact handle final 100ns digit')
    try:
        expected_creation({'native_creation_filetime': ft}, 'native', ft+1)
    except ValueError:
        checks.append('reject exact handle FILETIME drift by one 100ns tick')
    else:
        raise AssertionError('Exact FILETIME guard accepted drift')
    require(('Read' + 'ProcessMemory') not in Path(__file__).read_text(encoding='utf-8'), 'No process memory API expected')
    checks.append('metadata-only API surface')
    return {'result': 'PASS', 'cases': len(checks), 'checks': checks, 'processes_opened': False,
            'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, help='Explicit two-pair PID/creation/Silver SHA expectations')
    parser.add_argument('--before', type=Path, help='Prior passing capture to compare against')
    parser.add_argument('--offline-after', type=Path, help='Compare saved report; opens no processes')
    parser.add_argument('--reported-apply-utc', help='Parent GUI action timestamp; not independently observed here')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
    elif args.offline_after:
        require(args.before, '--offline-after requires --before')
        b = json.loads(args.before.read_text(encoding='utf-8-sig'))
        a = json.loads(args.offline_after.read_text(encoding='utf-8-sig'))
        result = {'result': 'PASS', 'before_report': str(args.before.resolve()),
                  'after_report': str(args.offline_after.resolve()), 'comparison': compare(b, a),
                  'processes_opened': False}
    else:
        require(args.manifest, 'An explicit --manifest is required')
        result = capture(json.loads(args.manifest.read_text(encoding='utf-8-sig')))
        result['expectation_manifest'] = str(args.manifest.resolve())
        result['expectation_manifest_sha256'] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
        if args.before:
            result['comparison'] = compare(json.loads(args.before.read_text(encoding='utf-8-sig')), result)
            result['comparison']['before_report'] = str(args.before.resolve())
            if args.reported_apply_utc:
                result['comparison']['reported_parent_gui_apply_utc'] = args.reported_apply_utc
    result['helper_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('PASS: ' + ('read-only owned connection capture/continuity' if not args.self_test else str(result['cases'])+' offline guard cases'))


if __name__ == '__main__':
    main()
