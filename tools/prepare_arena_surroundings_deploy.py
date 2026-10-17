"""Build reviewed new-only assets and the five-file server overlay; no upload."""
from arena_surroundings_deployment import *
import argparse
import copy
import tarfile
import xml.etree.ElementTree as ET


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tests-report', type=Path, required=True, help='Completed local validation JSON with passed=true')
    args = parser.parse_args(argv)
    write_json(OUT / 'release-verification.json', dict(passed=False, version=NEW_VERSION, published=False,
                                                     status='Preparation started; all proofs must pass again'))
    asset_file = ROOT / 'reports/arena-surroundings-implementation/asset-verification.json'
    asset_proof = ROOT / 'reports/arena-surroundings-implementation/asset-proof.json'
    proof = json.loads(asset_file.read_text(encoding='utf-8'))
    tests = json.loads(args.tests_report.read_text(encoding='utf-8'))
    if not all(proof.get(key) is True for key in ASSET_PROOF_FLAGS) or tests.get('passed') is not True or not asset_proof.is_file():
        raise RuntimeError('Complete asset proof and passed local checks are required')
    native_file = ROOT / 'reports/arena-surroundings-implementation/native.json'
    if proof['native_proof']['path'] != native_file.relative_to(ROOT).as_posix():
        raise RuntimeError('Unexpected native proof path')
    native_raw = native_file.read_bytes()
    native = json.loads(native_raw)
    detailed = json.loads(asset_proof.read_bytes())
    before = json.loads((OUT / 'before-hashes.json').read_text(encoding='utf-8'))
    inspection = json.loads((OUT / 'inspection.json').read_text(encoding='utf-8'))
    current = remote_read(r'''
import pathlib,hashlib,json,sys
root=pathlib.Path('/opt/tio-emulator');files=json.load(sys.stdin)
print(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() if (root/name).exists() else None for name in files}))
''', BASELINE_FILES)
    if current != before:
        raise RuntimeError('Hosted baseline changed since inspection')
    previous = (OUT / 'previous-client-manifest.json').read_bytes()
    old = json.loads(previous)
    if old['version'] != OLD_VERSION or sha(previous) != inspection['manifest_sha256']:
        raise RuntimeError('Unexpected inspected client baseline')
    old_records = {record['path']: record for record in old['files']}
    palette_file = ROOT / 'reports/arena-surroundings-implementation/native-prop-palette/palette.json'
    palette_raw = palette_file.read_bytes()
    palette = json.loads(palette_raw)
    for entry in palette['models'].values():
        raster = (ROOT / entry['path_rel_root']).resolve()
        if not raster.is_relative_to(ROOT) or sha(raster.read_bytes()) != entry['raster_sha256']:
            raise RuntimeError('Original palette raster bytes changed')
    native_evidence_files = {}
    creative_source_files = {}
    for key in ('foreground_attachment_proof', 'foreground_renderer_proof'):
        reference = native[key]
        for path_key, hash_key in (('path', 'sha256'), ('script', 'script_sha256')):
            name = reference[path_key].replace('\\', '/')
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or sha(path.read_bytes()) != reference[hash_key]:
                raise RuntimeError('Native foreground evidence bytes changed')
            native_evidence_files[name] = reference[hash_key]
    for scene in detailed['scenes']:
        source = (ROOT / scene['source']['path']).resolve()
        if not source.is_relative_to(ROOT) or sha(source.read_bytes()) != scene['source']['sha256']:
            raise RuntimeError('Reviewed concept bytes changed')
        compositor = scene['composition']['compositor']
        if compositor['path'] != 'tools/arena_surroundings_composition.py' or sha((ROOT / compositor['path']).read_bytes()) != compositor['sha256']:
            raise RuntimeError('Artwork proof was made by a superseded compositor implementation')
        layout = scene['composition']['layout_source']
        if layout['path'] != 'tools/arena_surroundings_layout.py' or sha((ROOT / layout['path']).read_bytes()) != layout['sha256']:
            raise RuntimeError('Artwork proof was made by a superseded layout implementation')
        if scene['master_id'] == 'R3':
            composition = scene['composition']
            name = composition['approved_source']
            path = (ROOT / name).resolve()
            if not path.is_relative_to(ROOT) or sha(path.read_bytes()) != composition['approved_source_sha256']:
                raise RuntimeError('Canal module source bytes changed')
            creative_source_files[name] = composition['approved_source_sha256']
            if path.name == 'R3-detail-bank.png':
                edit_proof = ROOT/'reports/arena-surroundings-implementation/R3-detail-bank-proof.json'
                edit = json.loads(edit_proof.read_bytes())
                if edit['output']['path'] != name or edit['output']['sha256'] != composition['approved_source_sha256'] or \
                        edit['original_R3_unchanged'] is not True or edit['output']['mode'] != 'RGBA':
                    raise RuntimeError('Creative canal module provenance is incomplete')
                original = (ROOT / edit['source']['path']).resolve()
                if not original.is_relative_to(ROOT) or sha(original.read_bytes()) != edit['source']['sha256']:
                    raise RuntimeError('Original approved R3 was modified')
                for item in (edit_proof, ROOT/edit['prompt_file']):
                    if not item.resolve().is_relative_to(ROOT):
                        raise RuntimeError('Unsafe creative proof reference')
                    creative_source_files[item.relative_to(ROOT).as_posix()] = sha(item.read_bytes())
    if len(old_records) != len(old['files']):
        raise RuntimeError('Duplicate baseline manifest paths')
    old_basenames = {PurePosixPath(name).name.lower() for name in old_records}
    client = copy.deepcopy(old)
    release = OUT / 'client-release'
    (release / 'blobs').mkdir(parents=True, exist_ok=True)
    additions = {}
    for path in sorted(OVERLAY.rglob('*')):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise RuntimeError('Asset overlay must contain regular files only')
        name = path.relative_to(OVERLAY).as_posix()
        if not allowed_asset(name) or name in old_records or PurePosixPath(name).name.lower() in old_basenames:
            raise RuntimeError('Only uniquely named new surroundings resources are allowed: ' + name)
        raw = path.read_bytes()
        if not raw:
            raise RuntimeError('Empty runtime asset: ' + name)
        record = dict(path=name, size=len(raw), sha256=sha(raw), seed=False)
        additions[name] = record
        client['files'].append(record)
        blob = release / 'blobs' / record['sha256']
        if blob.exists() and sha(blob.read_bytes()) != record['sha256']:
            raise RuntimeError('Immutable local blob collision')
        blob.write_bytes(raw)
    expected_scenes = {f'base/maps/as_{city}_{variant}_{size}.s'
                       for city in ('rv', 'de', 'ny', 'mz') for variant in (1, 2, 3) for size in (38, 57)}
    if {name for name in additions if name.startswith('base/maps/')} != expected_scenes:
        raise RuntimeError('All 24 city/variant/dimension scene resources are required')
    if not any(name.startswith('base/setting/arena_surroundings/') and name.endswith('.t') for name in additions) or not any(
            name.startswith('base/setting/arena_surroundings/') and name.endswith('.png') for name in additions):
        raise RuntimeError('Model/texture overlay is incomplete')
    new_basenames = [PurePosixPath(name).name for name in additions]
    if len(set(new_basenames)) != len(new_basenames):
        raise RuntimeError('Native resource basenames must be unique')
    policy = json.loads((ROOT / 'config/arena_surroundings.json').read_bytes())
    validate_asset_proof(proof, detailed, additions, policy, native, native_raw, old, palette, palette_raw)
    validate_native_asset_bytes(detailed, lambda name: (OVERLAY / name).read_bytes())
    client['version'] = NEW_VERSION
    from verify_hosted_arena_surroundings import verify_published_assets
    pixel_proof = verify_published_assets(manifest=client,
        fetch=lambda record: (OVERLAY / record['path']).read_bytes(), progress=True)
    pixel_proof['scope'] = 'Actual local prepared SET/TILE/PNG alpha, four side/corner bands; no HTTPS, hosted clients or accounts'
    pixel_proof_file = OUT / 'local-pixel-verification.json'
    write_json(pixel_proof_file, pixel_proof)
    client['news'] = ('Арены продолжаются за границей игрового поля: по три варианта окружения для Reservation, Denver, New York и Military Zone. '
                      'Декоративный фон недоступен для перемещения. Грунт городов приведён к их родным материалам. '
                      'Обновите клиент через лаунчер перед игрой.\n\n' + old.get('news', ''))
    new_records = {record['path']: record for record in client['files']}
    if not all(new_records.get(name) == record for name, record in old_records.items()):
        raise RuntimeError('An existing client manifest record was changed')
    write_json(release / 'manifest.json', client)
    (release / 'previous-manifest.json').write_bytes(previous)
    tests_archive = OUT / 'tests.tar.gz'
    for pattern in TEST_PATTERNS:
        if not (ROOT / 'tests' / pattern).is_file():
            raise RuntimeError('Required candidate test is missing: ' + pattern)
    fixture_names = {
        'evidence/battle_ground_native.json', 'evidence/battle_ground_scene_native.json',
        'reports/forest-biomes/client/base/shared config/items.xml',
        'reports/forest-biomes/client/base/ground.xml', 'reports/forest-biomes/source/base/ground.xml',
    }
    items = ET.parse(ROOT / 'reports/forest-biomes/client/base/shared config/items.xml').getroot()
    for identity in (65487, 65488):
        node = items.find(f"item[@id='{identity}']")
        values = {entry.get('key'): entry.get('val') for entry in node}
        image = PurePosixPath(values['image'])
        if image.is_absolute() or len(image.parts) != 1 or image.name != values['image']:
            raise RuntimeError('Unexpected test-only forest material image path')
        fixture_names.add('reports/forest-biomes/client/base/items/' + image.name)
    fixture_hashes = {name: sha((ROOT / name).read_bytes()) for name in sorted(fixture_names)}
    with tarfile.open(tests_archive, 'w:gz') as archive:
        for path in sorted((ROOT / 'tests').rglob('*.py')):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.add(path, arcname=path.relative_to(ROOT).as_posix(), recursive=False)
        for name in sorted(fixture_names):
            archive.add(ROOT / name, arcname=name, recursive=False)
    guard = dict(schema=1, baseline_client_version=OLD_VERSION, client_version=NEW_VERSION,
        baseline_client_manifest_sha256=sha(previous),
        baseline_files=before, fragment_path=inspection['fragment_path'],
        fragment_sha256=inspection['fragment_sha256'], configuration_sha256=inspection['configuration_sha256'],
        server_files={name: dict(before=before[name], after=sha((ROOT / name).read_bytes())) for name in SERVER_FILES},
        client_files=additions, test_patterns=TEST_PATTERNS, tests_archive_sha256=sha(tests_archive.read_bytes()),
        candidate_only_fixture_files=fixture_hashes,
        asset_verification_sha256=sha(asset_file.read_bytes()), asset_proof_sha256=sha(asset_proof.read_bytes()),
        native_proof_sha256=sha(native_raw),
        proof_validator_sha256=sha((ROOT / 'tools/arena_surroundings_deployment.py').read_bytes()),
        palette_proof_sha256=sha(palette_raw), native_evidence_files=native_evidence_files,
        local_pixels_sha256=sha(pixel_proof_file.read_bytes()),
        local_pixel_validator_sha256=sha((ROOT / 'tools/verify_hosted_arena_surroundings.py').read_bytes()),
        compositor_sha256=sha((ROOT / 'tools/arena_surroundings_composition.py').read_bytes()),
        layout_sha256=sha((ROOT / 'tools/arena_surroundings_layout.py').read_bytes()),
        creative_source_files=creative_source_files,
        local_tests_sha256=sha(args.tests_report.read_bytes()))
    write_json(OUT / 'guard.json', guard)
    patch = OUT / 'patch.tar.gz'
    with tarfile.open(patch, 'w:gz') as archive:
        for name in SERVER_FILES:
            archive.add(ROOT / name, arcname=name, recursive=False)
        for path, name in ((OUT / 'guard.json', 'guard.json'),
                           (release / 'manifest.json', 'client/manifest.json'),
                           (release / 'previous-manifest.json', 'client/previous-manifest.json'),
                           (asset_file, 'proofs/asset-verification.json'),
                           (asset_proof, 'proofs/asset-proof.json'),
                           (native_file, 'proofs/native.json'),
                           (palette_file, 'proofs/native-prop-palette.json'),
                           (ROOT / 'tools/arena_surroundings_deployment.py', 'proofs/deployment-validator.py'),
                           (pixel_proof_file, 'proofs/local-pixel-verification.json'),
                           (ROOT / 'tools/verify_hosted_arena_surroundings.py', 'proofs/local-pixel-validator.py'),
                           (ROOT / 'tools/arena_surroundings_composition.py', 'proofs/native-compositor.py'),
                           (ROOT / 'tools/arena_surroundings_layout.py', 'proofs/native-layout.py'),
                           (args.tests_report, 'proofs/local-tests.json')):
            archive.add(path, arcname=name, recursive=False)
        for name in sorted(native_evidence_files):
            archive.add(ROOT / name, arcname='proofs/native-evidence/' + name, recursive=False)
        for name in sorted(creative_source_files):
            archive.add(ROOT / name, arcname='proofs/creative-sources/' + name, recursive=False)
        for digest in sorted({record['sha256'] for record in additions.values()}):
            archive.add(release / 'blobs' / digest, arcname='client/blobs/' + digest, recursive=False)
    report = dict(passed=True, version=NEW_VERSION, baseline_version=OLD_VERSION,
        new_client_files=len(additions), old_client_records_preserved=len(old_records),
        server_files=len(SERVER_FILES), patch_sha256=sha(patch.read_bytes()),
        tests_archive_sha256=guard['tests_archive_sha256'], candidate_patterns=TEST_PATTERNS,
        database_uploaded=False, published=False)
    write_json(OUT / 'release-verification.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
