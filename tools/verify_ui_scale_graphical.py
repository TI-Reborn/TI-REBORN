"""Owned native UI-scale/portrait QA; no startup on import/help/check-only.

Preparation downloads only the exact public manifest and creates independent
seed configs in the existing marker-owned game-a/game-b copies. The run mode
uses the pinned launcher TLS/auth gate and retained proven-owned QA credentials.
Window input/capture is done separately through the computer-use skill.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import prepare_hosted_graphical_qa as preparation
from tools import hosted_graphical_qa_bridge as auth
from tools import hosted_stage9_graphical_qa_revision3 as adapter
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA, PRIVATE, OWNERSHIP

OUT = ROOT / 'reports/ui-modernization/graphical'
MANIFEST_SHA = 'b05f5ff717480e540dde4c13d152e2169861cc29d86801ee4ee591da8f079e6f'
BASE_SHA = '7a58e792614a179cfef1920e7f2d3b1775bc573ef0c39c8dc00eef3ccf23a8a8'
TI_CANDIDATE_SHA = auth.HASHES['ti.exe']
# A never-launched, owned prototype used an executable transform. Only staging
# can retire that exact hash; every launch/auth guard requires the original TI.
RETIRED_OWNED_TI_SHA = '953376a72ed6f94d79f8d82e76a77e64919acd59b8f1400ac783dbe2f78f12bb'
FIXTURE = PRIVATE / 'qsa1496217.json'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def candidate_bytes(path, expected):
    """Reconstruct solely .11 -> scaling core -> controls -> portrait."""
    from deploy import client_ui_scale as ui
    from deploy import client_ui_scale_controls as controls
    from deploy import client_portrait_quality as portrait
    path = Path(path).absolute()
    require(any(path.is_relative_to((ROOT / 'reports' / name).absolute()) for name in ('ui-scale', 'ui-modernization', 'portrait-quality'))
            and path.name == 'silver.dll' and not path.is_symlink(), 'Candidate is outside Screen reports')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'Exact reviewed candidate SHA differs')
    frozen = ROOT/'reports/screen-settings/graphical/source'/BASE_SHA/'silver.dll'
    base = next((p for p in (OUT / 'source/silver.dll', frozen, preparation.QA_BASE / 'game-a/silver.dll',
                           preparation.QA_BASE / 'game-b/silver.dll') if p.is_file() and digest(p) == BASE_SHA), None)
    require(base is not None, 'Exact published Screen base is unavailable')
    prior = ui.patch(base.read_bytes())
    prior = controls.patch(prior, expected_sha=hashlib.sha256(prior).hexdigest())
    require(portrait.patch(prior, expected_sha=hashlib.sha256(prior).hexdigest()) == data,
            'Candidate changes unrelated native bytes')
    return data


def native_guards(root, expected_silver=BASE_SHA, expected_ti=None):
    import pefile
    root = adapter.own_copy(root)
    if expected_ti is None:
        expected_ti = auth.HASHES['ti.exe'] if expected_silver == BASE_SHA else TI_CANDIDATE_SHA
    for name, sha in (('ti.exe', expected_ti), ('orange.dll', auth.HASHES['orange.dll']),
                      ('silver.dll', expected_silver)):
        require(digest(root / name) == sha, 'Exact owned native module differs: ' + name)
    # Configuration is generated independently; inherited player data is never accepted.
    for name in ('autoexec.cfg', 'config.cfg'):
        text = (root / 'base' / name).read_text(encoding='cp1251')
        require('orange_addr 185.184.42.88' in text and 'orange_port 28512' in text,
                'Owned hosted seed endpoint differs')
    rows = []
    with pefile.PE(str(root / 'silver.dll')) as pe:
        for name, va, size, expected in auth.SPANS:
            data = pe.get_data(va - 0x400000, size)
            require(hashlib.sha256(data).hexdigest() == expected, 'Native auth function differs: ' + name)
            offsets = [entry.rva - (va - 0x400000)
                       for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                       if entry.type == 3 and 0 <= entry.rva - (va - 0x400000) <= 8]
            rows.append(dict(name=name, va=va, entry12=data[:12].hex(), entry_relocations=offsets))
    return rows


def config_value(data, name):
    text = data.decode('cp1251')
    match = re.search(r'^\s*"?'+re.escape(name)+r'"?\s+"?([^"\s]+)"?\s*$', text, re.M)
    return match.group(1) if match else None


def seed(copies, qhd_a, check_only):
    """Generate only independent owned test settings; never import player data."""
    rows = []
    for copy in copies:
        root = adapter.own_copy(preparation.QA_BASE / ('game-'+copy))
        adapter.no_running_copy(root)
        width, height = (2560, 1440) if qhd_a and copy == 'a' else (1024, 768)
        data = ('orange_addr 185.184.42.88\r\norange_port 28512\r\n'
                'g_language russian\r\nr_fullscreen 0\r\nr_monitor 2\r\n'
                f'r_width {width}\r\nr_height {height}\r\nr_vsync 0\r\n'
                'sound_enable 0\r\ng_reglink https://185.184.42.88/register/\r\n').encode('ascii')
        require(config_value(data, 'ui_scale') is None, 'Automatic scale fixture contains explicit preference')
        if not check_only:
            for name in ('config.cfg', 'autoexec.cfg'):
                preparation.replace_private(root/'base'/name, data=data)
        rows.append(dict(copy=copy, width=width, height=height, mode=0, monitor=2, vsync=0,
                         ui_scale_absent=True, configuration_sha256=hashlib.sha256(data).hexdigest()))
    result = dict(creator='tools/verify_ui_scale_graphical.py', independent_owned_seed=True,
                  configurations=rows, check_only=check_only, personal_data_imported=False, started=0)
    if not check_only:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT/'seed.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result


def owned_exited(handle):
    from ctypes import wintypes
    wait = handle.kernel.WaitForSingleObject
    wait.argtypes = (wintypes.HANDLE, wintypes.DWORD); wait.restype = wintypes.DWORD
    return wait(handle.handle, 0) == 0


def save_native_configuration(root, directory, expected, copy, info):
    """Copy exact native-written owned bytes only after the bound game exits."""
    folder = directory/'native-config'; folder.mkdir()
    rows = []
    for name in ('config.cfg', 'autoexec.cfg'):
        data = (root/'base'/name).read_bytes()
        destination = folder/name
        preparation.replace_private(destination, data=data)
        rows.append(dict(name=name, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                         ui_scale=config_value(data, 'ui_scale')))
    receipt = dict(creator='tools/verify_ui_scale_graphical.py', kind='exact-native-owned-restart-config',
                   copy=copy, root=str(root), native_game_exited=True, process_pid=info['Pid'],
                   candidate_sha256=expected, ti_candidate_sha256=TI_CANDIDATE_SHA,
                   manifest_sha256=MANIFEST_SHA, files=rows, generated_ui_scale=False,
                   permitted_endpoints=[['185.184.42.88','28512'],
                                        ['127.0.0.1',str(info['LoginPort'])],
                                        ['127.0.0.1',str(info['SessionPort'])]])
    path = folder/'receipt.json'
    preparation.replace_private(path, data=(json.dumps(receipt, indent=2)+'\n').encode('utf-8'))
    return path, receipt


def restart_configuration(copy, receipt_path, expected):
    path = Path(receipt_path).absolute()
    require(path.is_relative_to((OUT/'runs').absolute()) and path.name == 'receipt.json'
            and path.parent.name == 'native-config' and not path.is_symlink(), 'Foreign restart receipt')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    root = adapter.own_copy(preparation.QA_BASE/('game-'+copy))
    require(receipt.get('creator') == 'tools/verify_ui_scale_graphical.py'
            and receipt.get('kind') == 'exact-native-owned-restart-config'
            and receipt.get('copy') == copy and Path(receipt['root']).absolute() == root
            and receipt.get('native_game_exited') is True and receipt.get('generated_ui_scale') is False
            and receipt.get('manifest_sha256') == MANIFEST_SHA
            and receipt.get('candidate_sha256') == expected
            and receipt.get('ti_candidate_sha256') == TI_CANDIDATE_SHA, 'Owned restart provenance differs')
    require({row['name'] for row in receipt['files']} == {'config.cfg','autoexec.cfg'}, 'Restart file scope differs')
    result = {}
    explicit_endpoint = False
    for row in receipt['files']:
        source = path.parent/row['name']
        require(not source.is_symlink() and digest(source) == row['sha256'], 'Exact native restart bytes differ')
        data = source.read_bytes()
        require(len(data) == row['bytes'] and config_value(data, 'ui_scale') == row['ui_scale'], 'Native scale receipt differs')
        endpoint = [config_value(data, 'orange_addr'), config_value(data, 'orange_port')]
        # Native archive output can omit non-archived network cvars. Preserve
        # that exact file when the other native file proves the allowed route;
        # reject partial or foreign explicit routes without inventing values.
        if endpoint != [None, None]:
            require(endpoint in receipt['permitted_endpoints'], 'Restart endpoint is outside proven hosted/owned bridge route')
            explicit_endpoint = True
        result[row['name']] = data
    require(explicit_endpoint, 'Native restart files contain no proven hosted/owned route')
    return root, result, receipt


def prepare(copies, check_only):
    roots = [adapter.own_copy(preparation.QA_BASE / ('game-' + c)) for c in copies]
    for root in roots:
        adapter.no_running_copy(root)
    raw = adapter.https(preparation.ORIGIN + 'manifest.json', 8 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'Latest reviewed public manifest moved')
    value = json.loads(raw)
    require(value['version'] == '2026.10.09.11' and len(value['files']) == 6330, 'Reviewed release differs')
    # Reuse the established pathname/seed/source validation with one exact new
    # published Silver SHA; the native auth span checks remain unchanged.
    preparation.accepted_native_hashes = lambda name: {BASE_SHA if name == 'silver.dll' else auth.HASHES[name]}
    records = preparation.validate_manifest(value)
    if check_only:
        return dict(check_only=True, manifest_sha256=MANIFEST_SHA, manifest_version=value['version'],
                    owned_copies=[p.name for p in roots], graphical_clients_started=0, remote_mutations=0)
    OUT.mkdir(parents=True, exist_ok=True)
    source = OUT / 'source'
    source.mkdir(exist_ok=True)
    preparation.replace_private(source / 'manifest.json', data=raw)
    preparation.static_guards = native_guards
    verified = {}
    proofs = [preparation.prepare_copy(p, value, records, MANIFEST_SHA, verified) for p in roots]
    preparation.replace_private(source / 'silver.dll', source=roots[0] / 'silver.dll')
    result = dict(manifest_version=value['version'], manifest_sha256=MANIFEST_SHA,
                  owned_copies=[p.name for p in roots], manifest_files=6330,
                  owned_native_auth_functions=len(auth.SPANS), independent_seed_configs=True,
                  personal_files_copied=0, credentials_printed=False, graphical_clients_started=0, remote_mutations=0)
    (OUT / 'prepared.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def stage(copies, candidate, expected, check_only):
    data = candidate_bytes(candidate, expected)
    receipt_path = OUT / 'staged-candidate.json'
    previous = None
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        require(receipt.get('creator') == 'tools/verify_ui_scale_graphical.py'
                and receipt.get('manifest_sha256') == MANIFEST_SHA
                and receipt.get('pure_transform_reconstruction') is True, 'Prior stage receipt differs')
        source = Path(receipt['verified_candidate']).absolute()
        require(source.is_relative_to((OUT / 'source').absolute()) and source.name == 'silver.dll'
                and not source.is_symlink() and digest(source) == receipt['candidate_sha256'],
                'Prior exact reconstructed candidate is unavailable')
        previous = receipt['candidate_sha256']
    for copy in copies:
        root = adapter.own_copy(preparation.QA_BASE / ('game-' + copy))
        adapter.no_running_copy(root)
        require(digest(root / 'silver.dll') in (BASE_SHA, expected, previous), 'Owned copy is not the reviewed base/candidate')
        require(digest(root / 'ti.exe') in (TI_CANDIDATE_SHA, RETIRED_OWNED_TI_SHA), 'Owned TI is not the reviewed original/retired prototype')
        if not check_only:
            preparation.replace_private(root / 'silver.dll', data=data)
            if digest(root / 'ti.exe') == RETIRED_OWNED_TI_SHA:
                from deploy import client_portrait_quality as portrait
                ti = portrait.patch_ti((ROOT / 'reports/ui-modernization/baseline/ti.exe').read_bytes())
                require(hashlib.sha256(ti).hexdigest() == TI_CANDIDATE_SHA, 'Pinned original TI restoration differs')
                preparation.replace_private(root / 'ti.exe', data=ti)
        if not check_only:
            native_guards(root, expected)
    if not check_only:
        source = OUT / 'source' / expected / 'silver.dll'
        preparation.replace_private(source, data=data)
        receipt_path.write_text(json.dumps(dict(creator='tools/verify_ui_scale_graphical.py',
            manifest_sha256=MANIFEST_SHA, candidate_sha256=expected, verified_candidate=str(source),
            ti_candidate_sha256=TI_CANDIDATE_SHA,
            pure_transform_reconstruction=True), indent=2) + '\n', encoding='utf-8')
    return dict(check_only=check_only, candidate_sha256=expected, ti_candidate_sha256=TI_CANDIDATE_SHA, copies=list(copies),
                staged=0 if check_only else len(copies), graphical_clients_started=0, remote_mutations=0)


def launch(copy, candidate, expected, fixture_path, seconds, restart_receipt=None):
    import frida
    candidate_bytes(candidate, expected)
    root = adapter.own_copy(preparation.QA_BASE / ('game-' + copy))
    guards = native_guards(root, expected)
    adapter.no_running_copy(root)
    fixture = FreshSurroundingsQA.load_private(fixture_path)
    require(len(fixture.names) == 2 and fixture.host == '185.184.42.88', 'Retained own QA pair required')
    # Ownership proof is read-only against the original backup and salted hashes.
    require(fixture.remote(OWNERSHIP + '\nprint(json.dumps(dict(owned=True)))', fixture.ownership_payload()) == {'owned': True},
            'Hosted fixture ownership is unconfirmed')
    launcher = adapter.launcher_guard()
    directory = OUT / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory.mkdir(parents=True)
    readiness_folder = adapter.FOLDER / 'readiness'
    readiness_folder.mkdir(parents=True, exist_ok=True)
    readiness = readiness_folder / ('screen-' + directory.name + '-' + copy + '.json')
    events = directory / 'events.jsonl'
    control = directory / 'controls.jsonl'
    control.write_text('', encoding='utf-8')
    configurations = {root / 'base' / n: (root / 'base' / n).read_bytes() for n in ('config.cfg', 'autoexec.cfg')}
    if restart_receipt:
        resumed_root, saved, resumed = restart_configuration(copy, restart_receipt, expected)
        require(resumed_root == root, 'Restart copy differs')
        for name, data in saved.items():
            preparation.replace_private(root/'base'/name, data=data)
    # Hidden long-lived TLS child may retain inherited pipe handles. Do not use
    # communicate() on captured pipes when waiting only for the CLI parent.
    try:
        starter = subprocess.Popen([str(launcher), '--tls-qa-start', str(root), str(readiness)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        require(starter.wait(timeout=65) == 0, 'Owned TLS launcher failed')
        info = adapter.readiness(readiness, root, launcher)
        from tools.hosted_new_player_graphical_qa import game_in_bridge_job
        require(game_in_bridge_job(info['Pid'], info['BridgePid']), 'Owned game/helper job is unconfirmed')
        handle = adapter.OwnedProcessHandle(info['Pid'], root)
    except BaseException:
        # A failed restart must also restore the initial independent owned
        # configs when no verified game process handle was obtained yet.
        for path, data in configurations.items():
            preparation.replace_private(path, data=data)
        raise
    session = None
    failures = []
    finish_persistence = False
    native_exit = False
    final_state = final_display = None
    def record(value):
        value = adapter.redact(dict(utc=datetime.now(timezone.utc).isoformat(), **value), fixture)
        with events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        emit(value)
    def receive(message, _):
        if message.get('type') != 'send':
            failures.append(message.get('type', 'unknown'))
            handle.terminate()
            record(dict(event='qa_runtime_error', error_type=message.get('type', 'unknown')))
        elif isinstance(message.get('payload'), dict):
            record(message['payload'])
    commands = queue.Queue()
    def reader():
        with control.open(encoding='utf-8') as stream:
            while True:
                line = stream.readline()
                if not line:
                    time.sleep(.1)
                    continue
                try:
                    value = json.loads(line)
                    if isinstance(value, dict) and set(value) <= {'action', 'label'}:
                        commands.put(value)
                except ValueError:
                    pass
    try:
        session = frida.get_local_device().attach(info['Pid'])
        bridge = session.create_script(adapter.native_source(info['LoginPort'], info['SessionPort']))
        bridge.on('message', receive)
        bridge.load()
        index = 0 if copy == 'a' else 1
        bridge.exports_sync.initialize(dict(executable=str(root / 'ti.exe'), silver_path=str(root / 'silver.dll'),
                                            entry_guards=guards, login=fixture.names[index], password=fixture.passwords[index],
                                            auto_select=True, loopback_login_port=info['LoginPort'],
                                            loopback_session_port=info['SessionPort']))
        from tools.window_compat import install
        window = install(session, receive)
        trace = session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))
        trace.on('message', receive)
        trace.load()
        from deploy import client_screen_settings as screen_module
        screen_names = {name:screen_module.IMAGE_BASE+screen_module.STRINGS+i*0x40+12
                        for i,name in enumerate(screen_module.CVARS[:4])}
        if hasattr(screen_module, 'VSYNC_NAME'):
            screen_names['r_vsync'] = screen_module.IMAGE_BASE+screen_module.VSYNC_NAME+12
        trace.exports_sync.initialize(dict(executable=str(root / 'ti.exe'), silver_path=str(root / 'silver.dll'),
            screen_signature_va=screen_module.IMAGE_BASE + getattr(screen_module, 'SIGNATURE_RVA', screen_module.STRINGS + 8*0x40),
            screen_apply_result_va=screen_module.IMAGE_BASE + screen_module.STATE + getattr(screen_module, 'RESULT_OFFSET', 0x30),
            screen_cvar_names=screen_names))
        threading.Thread(target=reader, daemon=True).start()
        initial_display = trace.exports_sync.status()
        rendering_ready = initial_display['presentCount'] > 0 and initial_display['startup']['guiManager'] != '0x0'
        pending_connect = False
        record(dict(event='screen_qa_ready', pid=info['Pid'], bridge_pid=info['BridgePid'],
                    directory=str(directory), controls=str(control), native_auth_ui_tested=False,
                    endpoint_certificates_validated=True, own_process_only=True,
                    native_render_ready=rendering_ready))
        until = time.monotonic() + seconds
        while time.monotonic() < until and not failures:
            if not rendering_ready or pending_connect:
                display = trace.exports_sync.status()
                if display['presentCount'] > 0 and display['startup']['guiManager'] != '0x0':
                    if not rendering_ready:
                        rendering_ready = True
                        record(dict(event='owned_native_render_ready', pid=info['Pid'],
                                    present_count=display['presentCount'], gui_manager=display['startup']['guiManager']))
                    if pending_connect:
                        bridge.exports_sync.startconnectwithprogress()
                        pending_connect = False
            if finish_persistence and owned_exited(handle):
                native_exit = True
                path, receipt = save_native_configuration(root, directory, expected, copy, info)
                record(dict(event='native_persistence_saved', receipt=str(path), files=receipt['files'],
                            exact_native_bytes=True, generated_ui_scale=False, native_game_exited=True))
                break
            try:
                command = commands.get(timeout=.2)
            except queue.Empty:
                continue
            action = command['action']
            if action == 'cleanup':
                break
            try:
                if action == 'connect':
                    if rendering_ready:
                        bridge.exports_sync.startconnectwithprogress()
                    else:
                        pending_connect = True
                        record(dict(event='owned_native_connect_deferred', reason='Native GUI/render initialization is incomplete'))
                elif action == 'status':
                    record(dict(event='screen_qa_status', state=bridge.exports_sync.status(),
                                display=trace.exports_sync.status()))
                elif action == 'snapshot':
                    trace.exports_sync.snapshot(command.get('label', 'requested'))
                elif action == 'expose':
                    record(dict(event='owned_window_reexposed', results=window.exports_sync.expose()))
                elif action == 'finish-persistence':
                    final_state, final_display = bridge.exports_sync.status(), trace.exports_sync.status()
                    finish_persistence = True
                    record(dict(event='native_persistence_armed', owned_pid=info['Pid'],
                                requires_real_native_exit=True, copied_before_exit=False))
            except Exception as error:
                record(dict(event='screen_qa_control_error', action=action, error_type=type(error).__name__,
                            detail=adapter.redact(str(error), fixture)))
                raise
        record(dict(event='screen_qa_final', state=final_state if native_exit else bridge.exports_sync.status(),
                    display=final_display if native_exit else trace.exports_sync.status(),
                    status_taken_before_native_exit=native_exit, native_exit=native_exit,
                    failures=len(failures), native_auth_ui_tested=False))
    finally:
        handle.terminate()
        handle.close()
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
        for path, data in configurations.items():
            preparation.replace_private(path, data=data)
        for relative in ('login.ini', 'base/login.ini'):
            generated = preparation.checked_target(root, relative)
            if generated.is_file():
                generated.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'stage', 'run', 'seed', 'prepare-restart'))
    parser.add_argument('--copies', choices=('a', 'b'), nargs='+', default=['a', 'b'])
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--candidate-sha')
    parser.add_argument('--fixture', type=Path, default=FIXTURE)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--qhd-a', action='store_true')
    parser.add_argument('--restart-receipt', type=Path)
    args = parser.parse_args()
    require(len(args.copies) == len(set(args.copies)), 'Duplicate owned copy')
    require(1 <= args.seconds <= 1800, 'Observation time exceeds 1..1800')
    if args.mode == 'seed':
        emit(seed(args.copies, args.qhd_a, args.check_only))
    elif args.mode == 'prepare':
        emit(prepare(args.copies, args.check_only))
    else:
        require(args.candidate is not None and args.candidate_sha is not None, 'Exact candidate path/SHA required')
        if args.mode == 'prepare-restart':
            require(len(args.copies) == 1 and args.restart_receipt is not None, 'One owned restart receipt required')
            candidate_bytes(args.candidate, args.candidate_sha)
            root, saved, receipt = restart_configuration(args.copies[0], args.restart_receipt, args.candidate_sha)
            adapter.no_running_copy(root); native_guards(root, args.candidate_sha)
            emit(dict(check_only=True, valid=True, exact_native_configuration=True,
                      native_config_ui_scale=next(row['ui_scale'] for row in receipt['files'] if row['name']=='config.cfg'),
                      owned_copy=args.copies[0], started=0, changed=0))
        elif args.mode == 'stage':
            emit(stage(args.copies, args.candidate, args.candidate_sha, args.check_only))
        else:
            require(len(args.copies) == 1, 'Run one owned copy at a time')
            if args.check_only:
                candidate_bytes(args.candidate, args.candidate_sha)
                native_guards(preparation.QA_BASE / ('game-' + args.copies[0]), args.candidate_sha)
                fixture = FreshSurroundingsQA.load_private(args.fixture)
                adapter.launcher_guard()
                emit(dict(check_only=True, valid=True, credentials_printed=False, started=0))
            else:
                launch(args.copies[0], args.candidate, args.candidate_sha, args.fixture, args.seconds, args.restart_receipt)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(dict(event='screen_qa_failed', error_type=type(error).__name__))
        raise SystemExit(1)
