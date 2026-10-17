"""Prepare an offline .1 -> .2 client-only RGB tint release; never uploads.

Only 552 already-published foreground TILE records may change. Their decoded
native bytes must differ solely at 52/53/54: RGB white -> B1/B1/B1. Existing
24 SETs, 552 PNGs, 5090 legacy records and every other TILE field remain exact.
The generated ZIP is an owner deployment bundle, not a new player download.
"""
from collections import Counter
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT/'reports/arena-surroundings-fog'
OLD = '2026.10.07.1'
NEW = '2026.10.07.2'
COLOR = 0x00b1b1b1
OLD_OVERLAY = ROOT/'assets/arena-surroundings-v1/client-overlay'
OVERLAY = ROOT/'assets/arena-surroundings-v2/client-overlay'
NATIVE_V1 = ROOT/'reports/arena-surroundings-implementation/native.json'
NATIVE_HASHES = {'ti_exe':'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
                 'silver_dll':'7137403658a66f8c9ee571960f29203bf6049d2722fa9719526049aec01670c1'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def records(manifest):
    require(manifest.get('schema') == 1 and isinstance(manifest.get('files'), list), 'Invalid launcher manifest')
    result, folded = {}, set()
    for record in manifest['files']:
        path = record['path']
        pure = PurePosixPath(path)
        require(not pure.is_absolute() and pure.as_posix() == path and '..' not in pure.parts and
                '\\' not in path and ':' not in path and path.lower() not in folded and
                re.fullmatch('[a-f0-9]{64}', record['sha256']) and type(record['size']) is int and
                0 <= record['size'] <= 512*1024*1024,
                'Unsafe/duplicate launcher record')
        result[path] = record;folded.add(path.lower())
    return result


def surroundings(path):
    return (re.fullmatch(r'base/maps/as_(rv|de|ny|mz)_[1-3]_(38|57)\.s', path) is not None or
            re.fullmatch(r'base/setting/arena_surroundings/as_(rv|de|ny|mz)_[1-3]_(38|57)_p[0-9]{4}\.(t|png)', path) is not None)


def native(raw):
    if raw[:4] == b'\x03ZIP':
        require(len(raw) >= 16, 'Truncated native ZIP envelope')
        decoded = zlib.decompress(raw[16:])
        require(len(decoded) == struct.unpack_from('<I', raw, 8)[0], 'Native ZIP length differs')
        return decoded
    return raw


def tint_pair(old, new):
    a, b = native(old), native(new)
    require(len(a) == len(b) == 544 and a[:8] == b[:8] == b'TI TILE\0', 'Expected native TILE v2')
    require(struct.unpack_from('<II', a, 52) == (0x00ffffff, 255), 'Baseline TILE is not opaque white')
    require(struct.unpack_from('<II', b, 52) == (COLOR, 255), 'New TILE must use exactly B1B1B1 RGB and alpha255')
    changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    require(changed == [52, 53, 54], 'Native TILE changed outside exactly three RGB bytes')
    # Reuse the immutable .1 field predicate only after verifying the whole
    # original/new byte delta. Normalization is validation-only, never runtime.
    from tools.verify_hosted_arena_surroundings import validate_tile_blob
    validate_tile_blob(a)
    normalized = bytearray(b);normalized[52:55] = b'\xff\xff\xff'
    validate_tile_blob(bytes(normalized))
    return dict(changed_raw_offsets=changed, old_native_sha256=sha(a), new_native_sha256=sha(b),
                color_hex='00b1b1b1', alpha=255)


def validate_manifest_delta(previous, release, replacements):
    require(previous['version'] == OLD and release['version'] == NEW, 'Unexpected release versions')
    before, after = records(previous), records(release)
    require(set(before) == set(after) and len(before) == 6218, 'Client record set changed')
    changed = {p for p in before if before[p] != after[p]}
    expected = {p for p in before if surroundings(p) and p.endswith('.t')}
    require(len(expected) == 552 and changed == expected == set(replacements), 'Only all552 existing surroundings TILE records may change')
    for path in changed:
        old_metadata = {k:v for k,v in before[path].items() if k not in ('size', 'sha256')}
        new_metadata = {k:v for k,v in after[path].items() if k not in ('size', 'sha256')}
        require(old_metadata == new_metadata and after[path] == replacements[path], 'TILE record metadata changed')
    old_meta = {k:v for k,v in previous.items() if k not in ('version', 'news', 'files')}
    new_meta = {k:v for k,v in release.items() if k not in ('version', 'news', 'files')}
    require(old_meta == new_meta, 'Launcher manifest schema/metadata changed')
    return dict(changed_records=552, unchanged_records=len(before)-552, all_paths_preserved=True,
                png_records_preserved=552, scene_records_preserved=24, legacy_records_preserved=5090)


def validate_native_proof(proof, v1_sha):
    require(proof.get('schema') == 'arena-surroundings-native-fog/v1' and proof.get('status') == 'PASS', 'Native RGB proof is incomplete')
    require(proof.get('tint_color_hex', '').lower() == '00b1b1b1' and proof.get('alpha') == 255 and
            proof.get('changed_raw_offsets') == [52,53,54], 'Native proof tint/alpha/offsets differ')
    require(proof.get('immutable_native_binary_sha256') == NATIVE_HASHES and
            proof.get('native_v1_proof_sha256') == v1_sha, 'Native executable or .1 proof pin differs')
    rgb = proof.get('runtime_rgb', {})
    colors = rgb.get('final_vertex_colors_hex', [])
    require(rgb.get('passed') is True and rgb.get('input_raw_color_hex', '').lower() == '00b1b1b1' and
            bool(colors) and all(str(value).lower() == 'ffb1b1b1' for value in colors), 'Executed native vertex RGB differs')
    require(proof.get('fog_independent') is True and proof.get('interactive_fields_zero') is True,
            'Permanent noninteractive native tint proof is incomplete')


def validate_baseline(snapshot, manifest_raw, launcher):
    require(snapshot.get('read_only') is True and snapshot['client_version'] == OLD and
            snapshot['manifest_sha256'] == sha(manifest_raw), 'Fresh .1 baseline/manifest differs')
    require(snapshot['service'] == 'active' and snapshot['gameplay_listeners'] == 2 and
            snapshot['established_connections'] == 0 and snapshot['database']['integrity'] == 'ok' and
            snapshot['database']['checkpoints'] == snapshot['database']['pending'] == 0, 'Baseline is busy/unhealthy')
    require(snapshot['manifest_record_count'] == 6218 and snapshot['surroundings_extensions'] == {'.s':24,'.t':552,'.png':552}, 'Baseline resource set differs')
    require(snapshot['previous_5090_records_exactly_preserved'] and snapshot['five_live_sources_match_completed_release_1'], 'Verified .1 baseline source/legacy proof differs')
    require(all(entry['path'].startswith('/var/www/tio-client/') and
                entry['relative'] == str(PurePosixPath(entry['path']).relative_to('/var/www/tio-client'))
                for entry in launcher['files']), 'Invalid launcher download baseline')


def prepare(proof_path, native_path, tests_path):
    save(OUT/'release-verification.json', dict(passed=False, version=NEW,
         status='preparing', published=False, server_contacted=False))
    snapshot_path, previous_path = OUT/'remote-before.json', OUT/'previous-client-manifest.json'
    launcher_path = OUT/'launcher-baseline.json'
    snapshot = json.loads(snapshot_path.read_bytes());previous_raw = previous_path.read_bytes()
    previous = json.loads(previous_raw);launcher = json.loads(launcher_path.read_bytes())
    validate_baseline(snapshot, previous_raw, launcher)
    before = records(previous)
    proof_raw, native_raw, tests_raw = proof_path.read_bytes(), native_path.read_bytes(), tests_path.read_bytes()
    proof, native_proof, tests = map(json.loads, (proof_raw, native_raw, tests_raw))
    require(proof.get('schema') == 'arena-surroundings-fog/v1' and proof.get('passed') is True and
            proof.get('previous_version') == OLD and proof.get('client_version') == NEW and
            proof.get('previous_manifest_sha256') == sha(previous_raw) and
            proof.get('tint_rgb_hex') == 'b1b1b1' and proof.get('native_vertex_argb') == 'ffb1b1b1' and
            proof.get('native_alpha') == 255 and proof.get('changed_offsets') == [52,53,54] and
            proof.get('changed_tile_count') == proof.get('pngs_unchanged') == 552 and
            proof.get('scene_count') == proof.get('scenes_unchanged') == 24 and
            proof.get('inventory_file_count') == 1128 and all(proof.get(k) is True for k in
              ('source_png_pixels_and_alpha_unchanged','gameplay_holes_and_all_four_sides_unchanged',
               'model_anchors_dimensions_uv_flags_and_interactions_unchanged')),
            'Completed exact fog asset proof required')
    require(tests.get('passed') is True and max(int(tests.get('tests_run',0)), int(tests.get('checks',0))) > 0,
            'Completed positive-count local checks required')
    require(tests.get('failures',0) == tests.get('errors',0) == 0, 'Local checks contain failures/errors')
    native_v1_raw = NATIVE_V1.read_bytes()
    validate_native_proof(native_proof, sha(native_v1_raw))
    require(json.loads(native_v1_raw)['status'] == 'PASS', 'Original foreground native proof differs')
    original_asset_raw = (ROOT/'reports/arena-surroundings-implementation/asset-proof.json').read_bytes()
    require(proof.get('original_asset_proof_sha256') == sha(original_asset_raw), 'Original asset proof pin differs')
    reference = native_proof['full_native_audit']
    audit_path = (ROOT/reference['path']).resolve()
    require(audit_path.is_relative_to(ROOT/'reports') and not audit_path.is_symlink(), 'Invalid native audit reference')
    audit_raw = audit_path.read_bytes()
    require(sha(audit_raw) == reference['sha256'] and json.loads(audit_raw).get('status') == 'PASS',
            'Executed native audit pin differs')
    paths = {p.relative_to(OVERLAY).as_posix():p for p in OVERLAY.rglob('*') if p.is_file()}
    expected = {p for p in before if surroundings(p)}
    require(set(paths) == expected and len(expected) == 1128 and not any(p.is_symlink() for p in paths.values()), 'Exactly the original1128 regular surroundings assets are required')
    release = copy.deepcopy(previous);release['version'] = NEW
    release['news'] = ('Декоративное окружение арен постоянно затемнено как туман войны. '
        'Закройте игру и откройте лаунчер для установки обновления.\n\n'+previous.get('news',''))
    inventory, changes, blobs = [], {}, {}
    for path in sorted(paths):
        old = (OLD_OVERLAY/path).read_bytes();new = paths[path].read_bytes();baseline = before[path]
        require(len(old) == baseline['size'] and sha(old) == baseline['sha256'], 'Old mirror differs from actual published .1: '+path)
        entry = dict(path=path, size=len(new), sha256=sha(new));inventory.append(entry)
        if path.endswith('.t'):
            require(len(old) == len(new) == 544 and old[:8] == new[:8] == b'TI TILE\0',
                    'Published TILE envelope changed: '+path)
            delta = tint_pair(old, new)
            record = copy.deepcopy(baseline);record.update(size=len(new), sha256=sha(new))
            changes[path] = dict(before=baseline, after=record, **delta)
            blobs[record['sha256']] = new
        else:
            require(old == new, 'A scene/PNG changed: '+path)
    require(isinstance(proof.get('files'), list) and len(proof['files']) == 1128, 'Exact fog inventory required')
    recorded = {e['path']:{k:e[k] for k in ('path','size','sha256')} for e in proof['files']}
    require(recorded == {e['path']:e for e in inventory}, 'Fog proof inventory differs from actual overlay')
    expected_changes = {p:dict(path=p,old_sha256=d['before']['sha256'],sha256=d['after']['sha256'],
                      size=d['after']['size'],changed_offsets=[52,53,54]) for p,d in changes.items()}
    require(len(proof.get('changes',[])) == 552 and
            {e['path']:e for e in proof['changes']} == expected_changes, 'Fog proof change list differs')
    for index, record in enumerate(release['files']):
        if record['path'] in changes:
            release['files'][index] = changes[record['path']]['after']
    delta = validate_manifest_delta(previous, release, {p:d['after'] for p,d in changes.items()})
    current_raw = (json.dumps(release, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    package_proofs = {'proofs/fog-proof.json':proof_raw, 'proofs/native-fog-tint.json':native_raw,
                      'proofs/local-tests.json':tests_raw, 'proofs/native-v1.json':native_v1_raw,
                      'proofs/native-full-audit.json':audit_raw, 'proofs/original-asset-proof.json':original_asset_raw}
    guard = dict(schema='arena-surroundings-fog-release/v1', before_version=OLD, version=NEW,
        baseline=snapshot, launcher_baseline=launcher, baseline_manifest_sha256=sha(previous_raw),
        new_manifest_sha256=sha(current_raw), tint_color_hex='00b1b1b1', alpha=255,
        changed_raw_offsets=[52,53,54], replacements=changes, manifest_delta=delta,
        native_v1_proof_sha256=sha(native_v1_raw), proof_files={p:sha(v) for p,v in package_proofs.items()},
        tool_sources={name:sha((ROOT/name).read_bytes()) for name in
                     ('tools/prepare_arena_fog_deploy.py','tools/publish_arena_fog.py')},
        database_uploaded=False, server_code_uploaded=False, service_restart_required=False,
        executable_or_launcher_changes=False, native_proof_scope='Isolated execution of original native RGB/alpha routines; genuine GPU/UI verification remains separate')
    release_dir = OUT/'client-release';release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir/'manifest.json').write_bytes(current_raw)
    (release_dir/'previous-manifest.json').write_bytes(previous_raw)
    save(OUT/'guard.json', guard);save(OUT/'overlay-verification.json', dict(passed=True,files=inventory,**delta))
    archive = OUT/'patch.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.writestr('guard.json', (OUT/'guard.json').read_bytes())
        bundle.writestr('client/manifest.json', current_raw)
        bundle.writestr('client/previous-manifest.json', previous_raw)
        for path, raw in package_proofs.items():bundle.writestr(path, raw)
        for digest, raw in blobs.items():bundle.writestr('client/blobs/'+digest, raw)
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, 'Prepared ZIP CRC failed')
    report = dict(passed=True, version=NEW, previous_version=OLD, **delta,
        manifest_sha256=sha(current_raw), baseline_manifest_sha256=sha(previous_raw),
        patch_zip_sha256=sha(archive.read_bytes()), patch_zip_size=archive.stat().st_size,
        guard_sha256=sha((OUT/'guard.json').read_bytes()), unique_immutable_blobs=len(blobs),
        archive_format='ZIP deployment transport; launcher consumes manifest + immutable SHA blobs',
        output=str(archive), native_rgb_proof_sha256=sha(native_raw), local_tests_sha256=sha(tests_raw),
        published=False, server_contacted=False, database_uploaded=False, service_restarted=False)
    save(OUT/'release-verification.json', report)
    print(json.dumps({k:report[k] for k in ('passed','version','changed_records','unchanged_records','patch_zip_sha256','published')}))
    return report


def self_test():
    from tools.arena_surroundings_native import encode_tile
    original = encode_tile('as_mz_1_57_p0000.png',1024,1024,32,0,render_type=1)
    tinted = bytearray(original);struct.pack_into('<I',tinted,52,COLOR)
    tint_pair(original, bytes(tinted));checks = 1
    for offset in (0,28,48,55,56,60,64,68,69,203,340,440,539):
        bad = bytearray(tinted);bad[offset] ^= 1
        try:tint_pair(original, bytes(bad))
        except (RuntimeError, AssertionError):checks += 1
        else:raise AssertionError('NonRGB change accepted at'+str(offset))
    compressed = lambda x:b'\x03ZIP'+b'\0'*4+struct.pack('<I',len(x))+b'\0'*4+zlib.compress(x)
    tint_pair(compressed(original),compressed(bytes(tinted)));checks += 1
    old = json.loads((OUT/'previous-client-manifest.json').read_bytes())
    new = copy.deepcopy(old);new['version'] = NEW
    replacements = {}
    for record in new['files']:
        if surroundings(record['path']) and record['path'].endswith('.t'):
            record['sha256'] = 'a'*64;replacements[record['path']] = record
    validate_manifest_delta(old,new,replacements);checks += 1
    for select in (lambda r:not surroundings(r['path']),lambda r:r['path'].endswith('.png'),lambda r:r['path'].endswith('.s')):
        bad = copy.deepcopy(new);target = next(r for r in bad['files'] if select(r));target['sha256']='b'*64
        try:validate_manifest_delta(old,bad,replacements)
        except RuntimeError:checks += 1
        else:raise AssertionError('Unchanged legacy/PNG/SET record change accepted')
    print(json.dumps(dict(offline_self_test='passed',checks=checks,server_contacted=False,accounts_created=0)))
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proof',type=Path,default=ROOT/'assets/arena-surroundings-v2/fog-proof.json')
    parser.add_argument('--native-proof',type=Path,default=OUT/'native-fog-tint.json')
    parser.add_argument('--tests-report',type=Path)
    parser.add_argument('--self-test',action='store_true')
    args = parser.parse_args()
    if args.self_test:self_test()
    else:
        require(args.tests_report is not None,'Completed local test report required')
        prepare(args.proof,args.native_proof,args.tests_report)
