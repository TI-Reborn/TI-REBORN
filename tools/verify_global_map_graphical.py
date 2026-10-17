"""Owned global-map graphical QA using the established TLS/native-auth harness.

Import, help and check-only never start a client. Preparation/staging target only
the two existing marker-owned QA copies. Observation attaches only to the exact
readiness-owned process and does not send input or alter gameplay state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import verify_ui_scale_graphical as ui
from tools import build_global_map_assets as assets
from deploy import client_global_map as native

preparation, adapter, auth = ui.preparation, ui.adapter, ui.auth
OUT = ROOT / 'reports/global-map-integration-20261010/graphical'
BASELINE = ROOT / 'reports/global-map-integration-20261010/baseline'
CANDIDATE = ROOT / 'reports/global-map-integration-20261010/client/candidate'
BASE_SHA = '077a80c0f856a9496745c50b19ef51d31a6e85e857b2f22025cbcd60c0bed1c0'
MANIFEST_SHA = 'a76ff9795f02da06064e7eb4f522e2f4dd99571f54abbc4149a5bb422cfb0232'
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
FIXTURE = ui.PRIVATE / 'qsa1496217.json'
CREATOR = 'tools/verify_global_map_graphical.py'
VERIFIED = {BASE_SHA}
require, digest, emit = ui.require, ui.digest, ui.emit


def candidate_bytes(path, expected):
    path = Path(path).absolute()
    require(path.is_relative_to((OUT.parent).absolute()) and path.name == 'silver.dll'
            and not path.is_symlink(), 'Candidate is outside global-map reports')
    require(re.fullmatch(r'[a-f0-9]{64}', expected or '') is not None, 'Exact candidate SHA required')
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected, 'Reviewed candidate SHA differs')
    base = BASELINE / 'client/silver.dll'
    require(digest(base) == BASE_SHA and native.BASE_SHA == BASE_SHA, 'Exact hosted .4 baseline differs')
    require(native.patch(base.read_bytes(), expected_sha=BASE_SHA) == data,
            'Candidate contains bytes outside the exact global-map transform')
    VERIFIED.add(expected)
    return data


def native_guards(root, expected_silver=BASE_SHA, expected_ti=None):
    import pefile
    adapter.dependency_guards()
    root = adapter.own_copy(root)
    require(expected_ti in (None, TI_SHA) and expected_silver in VERIFIED,
            'Only the pinned original TI and reconstructed Silver are accepted')
    for name, expected in (('ti.exe', TI_SHA), ('orange.dll', auth.HASHES['orange.dll']),
                           ('silver.dll', expected_silver)):
        require(digest(adapter.safe_path(root, name)) == expected, 'Owned native module differs: ' + name)
    for name in ('autoexec.cfg', 'config.cfg'):
        value = adapter.safe_path(root, 'base/' + name).read_text(encoding='cp1251')
        addresses = re.findall(r'^\s*orange_addr\s+(\S+)', value, re.M)
        ports = re.findall(r'^\s*orange_port\s+(\S+)', value, re.M)
        require(addresses and set(addresses) == {'185.184.42.88'}
                and ports and set(ports) == {'28512'}, 'Owned hosted seed endpoint differs')
    rows = []
    with pefile.PE(str(root / 'silver.dll')) as pe:
        for name, va, size, expected in auth.SPANS:
            raw = pe.get_data(va - 0x400000, size)
            require(len(raw) == size and hashlib.sha256(raw).hexdigest() == expected,
                    'Full original native auth span differs: ' + name)
            relocations = []
            for block in pe.DIRECTORY_ENTRY_BASERELOC:
                for entry in block.entries:
                    offset = entry.rva - (va - 0x400000)
                    if 0 <= offset < 12:
                        require(entry.type == 3 and offset + 4 <= 12, 'Unexpected auth entry relocation')
                        relocations.append(offset)
            rows.append(dict(name=name, va=va, entry12=raw[:12].hex(), entry_relocations=relocations))
    return rows


def install_overrides():
    # Keep ui.__file__ unchanged: ui.launch loads the reviewed existing trace JS.
    ui.OUT, ui.BASE_SHA, ui.TI_CANDIDATE_SHA = OUT, BASE_SHA, TI_SHA
    ui.MANIFEST_SHA, ui.FIXTURE = MANIFEST_SHA, FIXTURE
    ui.candidate_bytes, ui.native_guards = candidate_bytes, native_guards


def manifest_pin(path, expected):
    path = Path(path).absolute()
    require(path.is_relative_to(OUT.parent.absolute()) and not path.is_symlink(),
            'Public manifest pin must belong to global-map reports')
    raw = path.read_bytes()
    require(digest(path) == expected, 'Pinned public manifest SHA differs')
    value = json.loads(raw)
    require(value.get('version') in ('2026.10.10.4', '2026.10.10.5'), 'Unsupported public map baseline')
    rows = {r['path']: r for r in value['files']}
    expected_silver = rows['silver.dll']['sha256']
    if value['version'] == '2026.10.10.4':
        require(expected == MANIFEST_SHA and expected_silver == BASE_SHA, 'Hosted .4 pin differs')
    else:
        candidate_bytes(CANDIDATE / 'silver.dll', expected_silver)
        wanted = png_records(CANDIDATE)
        require(all(rows.get(r['path'], {}).get('sha256') == r['sha256']
                    and rows[r['path']]['size'] == r['size'] for r in wanted), 'Published PNG pins differ')
    require(rows['ti.exe']['sha256'] == TI_SHA, 'Original TI pin differs')
    for name, sha in auth.HASHES.items():
        if name != 'silver.dll':
            require(rows[name]['sha256'] == sha, 'Published native module pin differs: ' + name)
    return raw, value, expected_silver


def prepare(copies, check_only, pin_path, pin_sha):
    pinned, expected, silver_sha = manifest_pin(pin_path, pin_sha)
    roots = [adapter.own_copy(preparation.QA_BASE / ('game-' + c)) for c in copies]
    for root in roots:
        adapter.no_running_copy(root)
    fresh = adapter.https(preparation.ORIGIN + 'manifest.json', 8 * 1024 * 1024)
    require(fresh == pinned, 'Fresh HTTPS public manifest differs from the exact reviewed pin')
    preparation.accepted_native_hashes = lambda name: {silver_sha if name == 'silver.dll' else auth.HASHES[name]}
    records = preparation.validate_manifest(expected)
    result = dict(check_only=check_only, manifest_version=expected['version'], manifest_sha256=pin_sha,
                  manifest_files=len(records), copies=[p.name for p in roots],
                  independent_seed_configs=True, personal_files_copied=0, credentials_printed=False,
                  original_auth_full_spans=len(auth.SPANS), graphical_clients_started=0, remote_mutations=0)
    if check_only:
        return result
    OUT.mkdir(parents=True, exist_ok=True)
    preparation.replace_private(OUT / 'source/manifest.json', data=fresh)
    preparation.static_guards = lambda root: native_guards(root, silver_sha)
    verified = {}
    proofs = [preparation.prepare_copy(root, expected, records, pin_sha, verified) for root in roots]
    preparation.replace_private(OUT / 'source/silver.dll', source=roots[0] / 'silver.dll')
    result['copies'] = [{k: proof[k] for k in ('game_root', 'manifest_files', 'methods', 'estimated_bytes_written')}
                       for proof in proofs]
    (OUT / 'prepared.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def png_records(candidate_root):
    candidate_root = Path(candidate_root).absolute()
    require(candidate_root == CANDIDATE.absolute(), 'Only the isolated map asset candidate is accepted')
    folder = candidate_root / assets.RESOURCE_DIR
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    require(manifest.get('schema') == 1 and manifest.get('png_count') == 23
            and manifest.get('object_count') == 22 and manifest.get('software_pixel_edits') is False,
            'Expected the original 23-PNG builder manifest')
    require(digest(assets.SOURCE / 'catalog.json') == manifest['source_catalog_sha256']
            and digest(assets.SOURCE / 'asset-manifest.json') == manifest['source_manifest_sha256'],
            'Original catalog/asset manifest pin differs')
    originals = {r['file']: r for r in json.loads((assets.SOURCE / 'asset-manifest.json').read_text())['images']}
    required_paths = {'base/' + r['path'].replace('\\', '/') for r in native.resources()}
    rows = manifest['files']
    require(len(rows) == 23 and {r['path'] for r in rows} == required_paths, 'Native PNG resource paths differ')
    for row in rows:
        require(row['copy_byte_for_byte'] is True and row['path'].endswith('.png'), 'PNG copy policy differs')
        source = adapter.safe_path(assets.SOURCE, row['source'])
        candidate = adapter.safe_path(candidate_root, row['path'])
        original = originals.get(row['source'])
        require(original and original['sha256'] == row['sha256'] and digest(source) == row['sha256']
                and source.stat().st_size == row['size'] and source.read_bytes() == candidate.read_bytes(),
                'Source/candidate PNG differs: ' + row['path'])
        require(assets.png_header(source.read_bytes()) == {'pixels': row['pixels'], 'mode': row['mode']},
                'Source PNG metadata differs')
    return rows


def stage(copies, candidate, expected, check_only):
    data = candidate_bytes(candidate, expected)
    pngs = png_records(Path(candidate).parent)
    receipt_path = OUT / 'staged-candidate.json'
    previous = None
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        require(receipt.get('creator') == CREATOR and receipt.get('pure_transform_reconstruction') is True,
                'Previous map stage ownership receipt differs')
        previous_path = Path(receipt['verified_candidate']).absolute()
        require(previous_path.is_relative_to((OUT / 'source').absolute())
                and not previous_path.is_symlink() and digest(previous_path) == receipt['candidate_sha256'],
                'Previous exact map candidate is unavailable')
        previous = receipt['candidate_sha256']
    roots = [adapter.own_copy(preparation.QA_BASE / ('game-' + c)) for c in copies]
    for root in roots:
        adapter.no_running_copy(root)
        require(digest(root / 'silver.dll') in (BASE_SHA, expected, previous), 'Owned Silver is not the prepared base/candidate')
        require(digest(root / 'ti.exe') == TI_SHA, 'Owned original TI differs')
        proof = json.loads((root / preparation.PROOF).read_text(encoding='utf-8'))
        require(proof.get('creator') == preparation.CREATOR and proof.get('game_root') == str(root),
                'Prepared owned provenance differs')
    result = dict(check_only=check_only, candidate_sha256=expected, ti_sha256=TI_SHA, copies=list(copies),
                  png_count=23, object_count=22, copied_byte_for_byte=True, installed_json_count=0,
                  staged=0 if check_only else len(roots), graphical_clients_started=0, remote_mutations=0)
    if check_only:
        return result
    for root in roots:
        for row in pngs:
            preparation.replace_private(adapter.safe_path(root, row['path']), source=CANDIDATE / row['path'])
        preparation.replace_private(root / 'silver.dll', data=data)
        native_guards(root, expected)
        require(all(preparation.matches(root / row['path'], row) for row in pngs), 'Staged original PNG differs')
        # Extend the existing QA-only management receipt so subsequent refresh
        # can remove these exact owned additions; no game layout JSON is installed.
        proof = json.loads((root / preparation.PROOF).read_text(encoding='utf-8'))
        proof['managed_paths'] = sorted(set(proof['managed_paths']) | {r['path'] for r in pngs})
        preparation.replace_private(root / preparation.PROOF, data=(json.dumps(proof, indent=2) + '\n').encode())
    source = OUT / 'source' / expected / 'silver.dll'
    preparation.replace_private(source, data=data)
    receipt = dict(creator=CREATOR, verified_candidate=str(source), candidate_sha256=expected,
                   baseline_sha256=BASE_SHA, pure_transform_reconstruction=True,
                   pngs=[{k: r[k] for k in ('path', 'size', 'sha256')} for r in pngs])
    preparation.replace_private(receipt_path, data=(json.dumps(receipt, indent=2) + '\n').encode())
    return result


def observer_configuration(root):
    layout = json.loads((CANDIDATE / assets.RESOURCE_DIR / 'layout.json').read_text(encoding='utf-8'))
    fields = {name.lower(): getattr(native, name) for name in
              ('READY', 'LOADS', 'DRAWS', 'CLICKS', 'LEFT', 'TOP', 'WIDTH', 'HEIGHT',
               'OLD_TABLE', 'OLD_X', 'OLD_Y', 'OLD_AVX', 'OLD_AVY', 'AVX', 'AVY', 'LENGTH')}
    guards = []
    from deploy import client_global_map_visual as visual
    for address, raw in visual.extra_entries(native):
        guards.append(dict(rva=address-native.IMAGE_BASE, hex=raw.hex()))
    for address, _before, after in visual.native_edits(native):
        guards.append(dict(rva=address-native.IMAGE_BASE, hex=after.hex()))
    for address, raw in native.filters.extra_entries(native):
        guards.append(dict(rva=address-native.IMAGE_BASE, hex=raw.hex()))
    filtering = native.filters.metadata(native)
    filtering['state_fields'].update({name.lower(): getattr(native.filters, name) for name in
                                      ('IAT_OLD', 'IAT_SLOT', 'SAMPLER', 'OLD_MAG', 'OLD_MIN', 'OLD_MIP')})
    filtering['sampler_end_va'] = native.DRAW + native.filters.END_OFFSET
    return dict(executable=str(root / 'ti.exe'), silver_path=str(root / 'silver.dll'),
                draw_va=native.DRAW, click_va=native.CLICK, state_rva=native.STATE,
                rows_rva=native.ROWS, row_stride=native.ROW_SIZE, fields=fields,
                signature_rva=native.SIGNATURE_RVA, signature=native.SIGNATURE.decode(),
                original_table_va=0xb749e4, original_click_va=0x9ee684, native_travel_va=0x889e5c,
                code_guard_rva=native.REGION,
                code_guard_hex=native.extension()[:native.STATE-native.REGION].hex(),
                additional_code_guards=guards,
                filtering=filtering,
                resources=native.resources(), authority=[dict(id=r['id'], enabled=r['authority_enabled'],
                    bounds=r['native_bounds_world']) for r in layout['objects']])


def observe(copy, candidate, expected, readiness, seconds, check_only):
    candidate_bytes(candidate, expected)
    root = adapter.own_copy(preparation.QA_BASE / ('game-' + copy))
    native_guards(root, expected)
    pngs = png_records(CANDIDATE)
    require(all(preparation.matches(root / row['path'], row) for row in pngs), 'Live owned PNG pins differ')
    info = adapter.readiness(readiness, root, adapter.launcher_guard())
    from tools.hosted_new_player_graphical_qa import game_in_bridge_job
    require(game_in_bridge_job(info['Pid'], info['BridgePid']), 'Readiness process is not in the owned TLS bridge job')
    configuration = observer_configuration(root)
    if check_only:
        return dict(check_only=True, valid=True, pid=info['Pid'], attached=False, gameplay_mutations=0)
    import frida
    # The established exact process handle also guards PID reuse. Observation
    # only closes the handle; it never terminates the process or its TLS helper.
    handle = adapter.OwnedProcessHandle(info['Pid'], root)
    directory = OUT / 'observation' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory.mkdir(parents=True)
    events = directory / 'events.jsonl'
    controls = directory / 'controls.jsonl'
    controls.write_text('', encoding='utf-8')
    session = None
    try:
        session = frida.get_local_device().attach(info['Pid'])
        script = session.create_script(Path(__file__).with_suffix('.js').read_text(encoding='utf-8'))
        def receive(message, _data):
            row = message.get('payload') if message.get('type') == 'send' else dict(event='observer_script_error', type=message.get('type'))
            with events.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        script.on('message', receive)
        script.load()
        script.exports_sync.initialize(configuration)
        emit(dict(event='global_map_observer_ready', pid=info['Pid'], directory=str(directory), controls=str(controls), gameplay_mutations=0))
        started, position = time.monotonic(), 0
        while time.monotonic() - started < seconds and not ui.owned_exited(handle):
            with controls.open('r', encoding='utf-8') as stream:
                stream.seek(position)
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    command = json.loads(line)
                    require(set(command) <= {'action', 'label'}, 'Unknown observer control field')
                    if command.get('action') == 'snapshot':
                        script.exports_sync.snapshot(command.get('label', 'requested'))
                    elif command.get('action') == 'finish':
                        return dict(event='global_map_observer_finished', pid=info['Pid'], directory=str(directory), gameplay_mutations=0)
                    else:
                        require(command.get('action') == 'status', 'Observer accepts only status/snapshot/finish')
                    position = stream.tell()
            status = script.exports_sync.status()
            preparation.replace_private(directory / 'status.json', data=(json.dumps(status, indent=2) + '\n').encode())
            time.sleep(0.5)
        return dict(event='global_map_observer_finished', pid=info['Pid'], directory=str(directory), gameplay_mutations=0)
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass
        handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'stage', 'seed', 'run', 'observe'))
    parser.add_argument('--copies', choices=('a', 'b'), nargs='+', default=['a', 'b'])
    parser.add_argument('--candidate', type=Path, default=CANDIDATE / 'silver.dll')
    parser.add_argument('--candidate-sha')
    parser.add_argument('--manifest-pin', type=Path, default=BASELINE / 'manifest.json')
    parser.add_argument('--manifest-sha', default=MANIFEST_SHA)
    parser.add_argument('--fixture', type=Path, default=FIXTURE)
    parser.add_argument('--readiness', type=Path)
    parser.add_argument('--seconds', type=int, default=900)
    parser.add_argument('--qhd-a', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    require(args.copies and len(args.copies) == len(set(args.copies)), 'Duplicate owned copy')
    require(1 <= args.seconds <= 1800, 'Observation time exceeds 1..1800')
    require(args.fixture.absolute() == FIXTURE.absolute() and not args.fixture.is_symlink(), 'Only the retained owned private fixture is accepted')
    install_overrides()
    if args.mode == 'prepare':
        emit(prepare(args.copies, args.check_only, args.manifest_pin, args.manifest_sha))
    elif args.mode == 'seed':
        emit(ui.seed(args.copies, args.qhd_a, args.check_only))
    elif args.mode == 'stage':
        emit(stage(args.copies, args.candidate, args.candidate_sha, args.check_only))
    else:
        require(len(args.copies) == 1, 'Run or observe one owned copy at a time')
        if args.mode == 'observe':
            require(args.readiness is not None, 'Exact owned readiness file is required')
            emit(observe(args.copies[0], args.candidate, args.candidate_sha, args.readiness, args.seconds, args.check_only))
        else:
            candidate_bytes(args.candidate, args.candidate_sha)
            root = adapter.own_copy(preparation.QA_BASE / ('game-' + args.copies[0]))
            native_guards(root, args.candidate_sha)
            require(all(preparation.matches(root / row['path'], row) for row in png_records(CANDIDATE)), 'Staged original PNGs differ')
            if args.check_only:
                ui.FreshSurroundingsQA.load_private(args.fixture)
                adapter.launcher_guard()
                emit(dict(check_only=True, valid=True, credentials_printed=False, graphical_clients_started=0))
            else:
                ui.launch(args.copies[0], args.candidate, args.candidate_sha, args.fixture, args.seconds)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        failure = dict(event='global_map_graphical_qa_failed', error_type=type(error).__name__)
        if len(sys.argv) > 1 and sys.argv[1] in ('prepare', 'stage', 'seed'):
            failure['reason'] = str(error)
        emit(failure)
        raise SystemExit(1)
