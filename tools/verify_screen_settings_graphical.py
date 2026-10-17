"""Owned native Screen QA; no startup on import, --help or check-only.

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

OUT = ROOT / 'reports/screen-settings/graphical'
MANIFEST_SHA = 'c49d005ded4accda151637e75b3076f28c3d2b927b24f27607ef9c2274f94fae'
BASE_SHA = 'bd0ce7a29d4cfdb4689330da8086052c287146fe7a383ed50710493a7ba0b0ac'
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
    """Prove the candidate is solely both current pure Screen transformers."""
    from deploy import client_screen_resolution_ui as ui
    from deploy import client_screen_settings as apply
    path = Path(path).absolute()
    require(path.is_relative_to((ROOT / 'reports/screen-settings').absolute())
            and path.name == 'silver.dll' and not path.is_symlink(), 'Candidate is outside Screen reports')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'Exact reviewed candidate SHA differs')
    base = next((p for p in (OUT / 'source/silver.dll', preparation.QA_BASE / 'game-a/silver.dll',
                           preparation.QA_BASE / 'game-b/silver.dll') if p.is_file() and digest(p) == BASE_SHA), None)
    require(base is not None, 'Exact published Screen base is unavailable')
    prior = ui.patch(base.read_bytes())
    require(apply.patch(prior, expected_sha=hashlib.sha256(prior).hexdigest()) == data,
            'Candidate changes unrelated native bytes')
    return data


def native_guards(root, expected_silver=BASE_SHA):
    import pefile
    root = adapter.own_copy(root)
    for name, sha in (('ti.exe', auth.HASHES['ti.exe']), ('orange.dll', auth.HASHES['orange.dll']),
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


def prepare(copies, check_only):
    roots = [adapter.own_copy(preparation.QA_BASE / ('game-' + c)) for c in copies]
    for root in roots:
        adapter.no_running_copy(root)
    raw = adapter.https(preparation.ORIGIN + 'manifest.json', 8 * 1024 * 1024)
    require(hashlib.sha256(raw).hexdigest() == MANIFEST_SHA, 'Latest reviewed public manifest moved')
    value = json.loads(raw)
    require(value['version'] == '2026.10.09.10' and len(value['files']) == 6330, 'Reviewed release differs')
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
        require(receipt.get('creator') == 'tools/verify_screen_settings_graphical.py'
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
        if not check_only:
            preparation.replace_private(root / 'silver.dll', data=data)
        if not check_only:
            native_guards(root, expected)
    if not check_only:
        source = OUT / 'source' / expected / 'silver.dll'
        preparation.replace_private(source, data=data)
        receipt_path.write_text(json.dumps(dict(creator='tools/verify_screen_settings_graphical.py',
            manifest_sha256=MANIFEST_SHA, candidate_sha256=expected, verified_candidate=str(source),
            pure_transform_reconstruction=True), indent=2) + '\n', encoding='utf-8')
    return dict(check_only=check_only, candidate_sha256=expected, copies=list(copies),
                staged=0 if check_only else len(copies), graphical_clients_started=0, remote_mutations=0)


def launch(copy, candidate, expected, fixture_path, seconds):
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
    # Hidden long-lived TLS child may retain inherited pipe handles. Do not use
    # communicate() on captured pipes when waiting only for the CLI parent.
    starter = subprocess.Popen([str(launcher), '--tls-qa-start', str(root), str(readiness)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    require(starter.wait(timeout=65) == 0, 'Owned TLS launcher failed')
    info = adapter.readiness(readiness, root, launcher)
    from tools.hosted_new_player_graphical_qa import game_in_bridge_job
    require(game_in_bridge_job(info['Pid'], info['BridgePid']), 'Owned game/helper job is unconfirmed')
    handle = adapter.OwnedProcessHandle(info['Pid'], root)
    session = None
    failures = []
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
        record(dict(event='screen_qa_ready', pid=info['Pid'], bridge_pid=info['BridgePid'],
                    directory=str(directory), controls=str(control), native_auth_ui_tested=False,
                    endpoint_certificates_validated=True, own_process_only=True))
        until = time.monotonic() + seconds
        while time.monotonic() < until and not failures:
            try:
                command = commands.get(timeout=.2)
            except queue.Empty:
                continue
            action = command['action']
            if action == 'cleanup':
                break
            try:
                if action == 'connect':
                    bridge.exports_sync.startconnectwithprogress()
                elif action == 'status':
                    record(dict(event='screen_qa_status', state=bridge.exports_sync.status(),
                                display=trace.exports_sync.status()))
                elif action == 'snapshot':
                    trace.exports_sync.snapshot(command.get('label', 'requested'))
                elif action == 'expose':
                    record(dict(event='owned_window_reexposed', results=window.exports_sync.expose()))
            except Exception as error:
                record(dict(event='screen_qa_control_error', action=action, error_type=type(error).__name__,
                            detail=adapter.redact(str(error), fixture)))
                raise
        record(dict(event='screen_qa_final', state=bridge.exports_sync.status(), display=trace.exports_sync.status(),
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
    parser.add_argument('mode', choices=('prepare', 'stage', 'run'))
    parser.add_argument('--copies', choices=('a', 'b'), nargs='+', default=['a', 'b'])
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--candidate-sha')
    parser.add_argument('--fixture', type=Path, default=FIXTURE)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(len(args.copies) == len(set(args.copies)), 'Duplicate owned copy')
    require(1 <= args.seconds <= 1800, 'Observation time exceeds 1..1800')
    if args.mode == 'prepare':
        emit(prepare(args.copies, args.check_only))
    else:
        require(args.candidate is not None and args.candidate_sha is not None, 'Exact candidate path/SHA required')
        if args.mode == 'stage':
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
                launch(args.copies[0], args.candidate, args.candidate_sha, args.fixture, args.seconds)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        emit(dict(event='screen_qa_failed', error_type=type(error).__name__))
        raise SystemExit(1)
