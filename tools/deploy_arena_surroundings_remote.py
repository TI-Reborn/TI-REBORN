"""Guarded five-file hosted update plus new immutable surroundings resources.

Never uploads/replaces hosted player data. Rollback restores code/manifest only.
"""
from collections import Counter
from contextlib import closing
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time

ROOT = Path('/opt/tio-emulator')
DB = Path('/var/lib/tio-server/reservation.sqlite3')
LIVE = Path('/var/www/tio-client/updates')
PATCH = Path('/root/tio-arena-surroundings-patch.tar.gz')
CANDIDATE = Path('/root/tio-arena-surroundings-candidate.json')
CONFIG = Path('/etc/tio-server/server.toml')
SERVER_FILES = {'tio/arena_map.py', 'tio/map_generation.py', 'tio/arena_surroundings.py',
                'config/battle_map_profiles.json', 'config/arena_surroundings.json'}
BASELINE_FILES = SERVER_FILES | {'config/arena_fragments.json', 'config/reservation_visuals.json', 'tio/protocol/battle_ground.py'}
ASSET_PROOF_FLAGS = ('passed', 'full_set_complete', 'all_gameplay_holes_clear', 'all_outer_diamonds_clear',
                    'all_four_sides_covered', 'all_four_corners_covered', 'all_models_noninteractive', 'all_scenes_1x1_empty_cells',
                    'all_patches_1024x1024_full_frame', 'all_scenes_foreground',
                    'all_scenes_no_nonlinear_warp', 'all_native_anchors_inside_game_grid')
OLD_VERSION = '2026.10.06.5'
NEW_VERSION = '2026.10.07.1'


def command(*args):
    return subprocess.check_output(args, text=True, cwd=ROOT).strip()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(path):
    return sha(path.read_bytes()) if path.exists() else None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def allowed_asset(name):
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or '..' in path.parts or '\\' in name or ':' in name:
        return False
    if path.name != path.name.lower() or not path.name.startswith('as_'):
        return False
    if path.parent == PurePosixPath('base/maps'):
        return re.fullmatch(r'as_(rv|de|ny|mz)_[1-3]_(38|57)\.s', path.name) is not None
    return path.parent == PurePosixPath('base/setting/arena_surroundings') and path.suffix in ('.t', '.png')


def database_state():
    with closing(sqlite3.connect(f'file:{DB}?mode=ro', uri=True)) as database:
        return dict(integrity=database.execute('PRAGMA integrity_check').fetchone()[0],
                    accounts=database.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
                    checkpoints=database.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],
                    pending=database.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0])


def rows():
    with closing(sqlite3.connect(f'file:{DB}?mode=ro', uri=True)) as database:
        return {name: Counter(repr(row) for row in database.execute('SELECT * FROM "' + name.replace('"', '""') + '"'))
                for name, in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def backup_database(destination):
    with closing(sqlite3.connect(f'file:{DB}?mode=ro', uri=True)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
        require(target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Backup database integrity failed')
    destination.chmod(0o600)


def publish_manifest(raw, name):
    temporary = LIVE / name
    temporary.write_bytes(raw)
    temporary.chmod(0o644)
    temporary.replace(LIVE / 'manifest.json')


def main():
    stage = Path(tempfile.mkdtemp(prefix='tio-arena-surroundings-stage-', dir='/root')).resolve()
    with tarfile.open(PATCH) as archive:
        members = archive.getmembers()
        require(len({member.name for member in members}) == len(members), 'Duplicate patch archive path')
        require(all(member.isfile() and (stage / member.name).resolve().is_relative_to(stage)
                    for member in members), 'Unsafe patch archive path/type')
        archive.extractall(stage, filter='data')
    guard = json.loads((stage / 'guard.json').read_text())
    require(set(guard['server_files']) == SERVER_FILES, 'Unexpected runtime overlay scope')
    candidate = json.loads(CANDIDATE.read_text())
    require(candidate.get('passed') is True and candidate['patch_sha256'] == digest(PATCH) and
            candidate['tests_archive_sha256'] == guard['tests_archive_sha256'] and
            candidate['guard_sha256'] == digest(stage / 'guard.json'), 'Matching passed candidate report required')
    require({check['pattern'] for check in candidate['checks'] if check['passed']} == set(guard['test_patterns']),
            'Candidate checks are incomplete')
    asset_summary = json.loads((stage / 'proofs/asset-verification.json').read_text())
    require(all(asset_summary.get(key) is True for key in ASSET_PROOF_FLAGS) and
            asset_summary.get('scene_count') == asset_summary.get('expected_scene_count') == 24 and
            json.loads((stage / 'proofs/local-tests.json').read_text())['passed'] is True, 'Local proofs are incomplete')
    for key, name in (('asset_verification_sha256', 'asset-verification.json'),
                      ('asset_proof_sha256', 'asset-proof.json'), ('native_proof_sha256', 'native.json'),
                      ('local_tests_sha256', 'local-tests.json')):
        require(digest(stage / 'proofs' / name) == guard[key], 'Packaged proof hash mismatch')
    require(set(guard['baseline_files']) == BASELINE_FILES, 'Baseline guard scope is incomplete')
    for name, expected in guard['baseline_files'].items():
        require(digest(ROOT / name) == expected, 'Hosted baseline changed: ' + name)
    for name, entry in guard['server_files'].items():
        require(digest(ROOT / name) == entry['before'] and digest(stage / name) == entry['after'], 'Server file guard mismatch: ' + name)
    old = (LIVE / 'manifest.json').read_bytes()
    require(old == (stage / 'client/previous-manifest.json').read_bytes() and sha(old) == guard['baseline_client_manifest_sha256'],
            'Published client baseline changed')
    new = (stage / 'client/manifest.json').read_bytes()
    previous = json.loads(old); release = json.loads(new)
    require(previous['version'] == OLD_VERSION and release['version'] == NEW_VERSION, 'Unexpected release versions')
    old_records = {record['path']: record for record in previous['files']}
    new_records = {record['path']: record for record in release['files']}
    require(len(old_records) == len(previous['files']) and len(new_records) == len(release['files']), 'Duplicate client manifest record')
    require(all(new_records.get(name) == record for name, record in old_records.items()), 'Existing client records changed')
    require(set(new_records) - set(old_records) == set(guard['client_files']), 'New-only client scope differs')
    expected_scenes = {f'base/maps/as_{city}_{variant}_{size}.s' for city in ('rv', 'de', 'ny', 'mz')
                       for variant in (1, 2, 3) for size in (38, 57)}
    require({name for name in guard['client_files'] if name.startswith('base/maps/')} == expected_scenes, 'Scene resource set is incomplete')
    proof_files = asset_summary['files']
    require(len(proof_files) == asset_summary['file_count'] == len(guard['client_files']) and
            {record['path']: record for record in proof_files} ==
            {name: {key: record[key] for key in ('path', 'size', 'sha256')} for name, record in guard['client_files'].items()},
            'Asset proof inventory differs from the release')
    native_proof = json.loads((stage / 'proofs/native.json').read_text())
    require(native_proof.get('status') == asset_summary['native_proof'].get('status') == 'PASS' and
            digest(stage / 'proofs/native.json') == asset_summary['native_proof']['sha256'], 'Native proof differs from the asset summary')
    detailed = json.loads((stage / 'proofs/asset-proof.json').read_text())
    scenes = detailed['scenes']
    require(len(scenes) == 24 and {scene['scene'] for scene in scenes} == expected_scenes and
            all(scene.get('passed') is True and scene.get('no_interactions') is True and
                scene.get('native_reconstruction_equals_clipped_master_alpha') is True and
                scene['alpha_proof'].get('passed') is True and scene['alpha_proof']['hole_nonzero_pixels'] ==
                scene['alpha_proof']['outside_nonzero_pixels'] == 0 and scene['cell_footprint'] == [1, 1] and
                scene['cell_payload_hex'] == '0000' and scene['scene_sha256'] == guard['client_files'][scene['scene']]['sha256']
                for scene in scenes), 'Detailed native asset proof is incomplete')
    validator_file = stage / 'proofs/deployment-validator.py'
    require(digest(validator_file) == guard['proof_validator_sha256'], 'Foreground validator bytes changed')
    palette_file = stage / 'proofs/native-prop-palette.json'
    require(digest(palette_file) == guard['palette_proof_sha256'], 'Original native palette proof changed')
    require(digest(stage / 'proofs/native-compositor.py') == guard['compositor_sha256'] and
            all(scene['composition']['compositor']['path'] == 'tools/arena_surroundings_composition.py' and
                scene['composition']['compositor']['sha256'] == guard['compositor_sha256'] for scene in scenes),
            'Artwork proof was produced by a superseded native compositor')
    require(digest(stage / 'proofs/native-layout.py') == guard['layout_sha256'] and
            all(scene['composition']['layout_source']['path'] == 'tools/arena_surroundings_layout.py' and
                scene['composition']['layout_source']['sha256'] == guard['layout_sha256'] for scene in scenes),
            'Artwork proof was produced by a superseded native layout')
    for name, expected in guard['creative_source_files'].items():
        path = (stage / 'proofs/creative-sources' / name).resolve()
        require(path.is_relative_to(stage / 'proofs/creative-sources') and digest(path) == expected,
                'Creative canal source/evidence bytes changed')
    require(all(guard['creative_source_files'].get(scene['composition']['approved_source']) ==
                scene['composition']['approved_source_sha256'] for scene in scenes if scene['master_id'] == 'R3'),
            'Prepared canal source differs from creative reference bytes')
    for key in ('foreground_attachment_proof', 'foreground_renderer_proof'):
        reference = native_proof[key]
        for path_key, hash_key in (('path', 'sha256'), ('script', 'script_sha256')):
            name = reference[path_key].replace('\\', '/')
            evidence = (stage / 'proofs/native-evidence' / name).resolve()
            require(evidence.is_relative_to(stage / 'proofs/native-evidence') and
                    guard['native_evidence_files'][name] == reference[hash_key] == digest(evidence),
                    'Native foreground execution evidence changed')
    spec = importlib.util.spec_from_file_location('prepared_surroundings_validator', validator_file)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    validator.validate_asset_proof(asset_summary, detailed, guard['client_files'],
        json.loads((stage / 'config/arena_surroundings.json').read_text()), native_proof,
        (stage / 'proofs/native.json').read_bytes(), previous,
        json.loads(palette_file.read_text()), palette_file.read_bytes())
    validator.validate_native_asset_bytes(detailed, lambda name:
        (stage / 'client/blobs' / guard['client_files'][name]['sha256']).read_bytes())
    pixel_proof_file = stage / 'proofs/local-pixel-verification.json'
    require(digest(pixel_proof_file) == guard['local_pixels_sha256'] and
            digest(stage / 'proofs/local-pixel-validator.py') == guard['local_pixel_validator_sha256'],
            'Independent local PNG pixel proof/validator changed')
    pixel_proof = json.loads(pixel_proof_file.read_text())
    require(pixel_proof.get('passed') is True and pixel_proof['scene_count'] == 24 and
            pixel_proof['client_version'] == NEW_VERSION and pixel_proof['accounts_created'] ==
            pixel_proof['game_connections_created'] == 0, 'Independent local PNG verification is incomplete')
    pixel_files = {}
    for result in pixel_proof['scenes'].values():
        alpha = result['alpha_proof']
        require(alpha.get('passed') is True and alpha['hole_nonzero_pixels'] == alpha['outside_nonzero_pixels'] == 0 and
                alpha['minimum_opaque_fraction'] >= .95 and len(alpha['four_sides']) == len(alpha['four_corners']) == 4 and
                all(region['pixels'] > 0 and region['opaque_fraction'] >= .95 for group in
                    (alpha['four_sides'], alpha['four_corners']) for region in group.values()),
                'Independent actual PNG side/corner coverage proof is incomplete')
        for record in result['exact_published_records']:
            require(record['path'] not in pixel_files, 'Duplicate independently inspected asset path')
            pixel_files[record['path']] = record
    require(pixel_files == {name: {key: record[key] for key in ('path', 'size', 'sha256')}
                            for name, record in guard['client_files'].items()},
            'Independent PNG proof does not cover the complete packaged asset inventory')
    before_basenames = {PurePosixPath(name).name.lower() for name in old_records}
    added_basenames = [PurePosixPath(name).name.lower() for name in guard['client_files']]
    require(len(set(added_basenames)) == len(added_basenames) and not set(added_basenames) & before_basenames,
            'Native resource basename collision')
    for name, record in guard['client_files'].items():
        require(allowed_asset(name) and new_records[name] == record and record.get('seed') is False,
                'Unexpected new runtime resource: ' + name)
        require(re.fullmatch('[0-9a-f]{64}', record['sha256']) is not None, 'Invalid immutable blob name')
        blob = stage / 'client/blobs' / record['sha256']
        require(digest(blob) == record['sha256'] and blob.stat().st_size == record['size'], 'Asset blob mismatch: ' + name)
    fragment = Path(command('systemctl', 'show', 'tio-server', '--property=FragmentPath', '--value'))
    require(str(fragment) == guard['fragment_path'] and digest(fragment) == guard['fragment_sha256'] and
            digest(CONFIG) == guard['configuration_sha256'], 'Service/configuration baseline changed')
    require(command('systemctl', 'is-active', 'tio-server') == 'active', 'Hosted service is not active')
    require(not command('ss', '-Htn', 'state', 'established', '( sport = :28512 or sport = :28513 )'),
            'Active players connected; deployment aborted')
    state = database_state()
    require(state['integrity'] == 'ok' and state['checkpoints'] == 0 and state['pending'] == 0,
            'Hosted database has unfinished battles or settlements')
    backup = Path(tempfile.mkdtemp(prefix='tio-before-arena-surroundings-', dir='/root'))
    backup_database(backup / 'reservation-live.sqlite3')
    shutil.copy2(CONFIG, backup / 'server.toml')
    shutil.copy2(fragment, backup / 'tio-server.service')
    (backup / 'systemctl-cat.txt').write_text(command('systemctl', 'cat', 'tio-server'))
    (backup / 'client-manifest.json').write_bytes(old)
    with tarfile.open(backup / 'previous-code-config.tar.gz', 'w:gz') as archive:
        for folder in ('tio', 'server', 'tools', 'config', 'evidence'):
            archive.add(ROOT / folder, arcname=folder)
    require(not command('ss', '-Htn', 'state', 'established', '( sport = :28512 or sport = :28513 )'),
            'A player connected while backups were being prepared; no service/code change applied')
    require((LIVE / 'manifest.json').read_bytes() == old and
            all(digest(ROOT / name) == expected for name, expected in guard['baseline_files'].items()),
            'Hosted code/manifest baseline changed while backups were being prepared')
    command('systemctl', 'stop', 'tio-server')
    applied = []
    try:
        stopped = database_state()
        require(stopped['integrity'] == 'ok' and stopped['checkpoints'] == 0 and stopped['pending'] == 0,
                'Battle/settlement appeared during shutdown; no code applied')
        backup_database(backup / 'reservation.sqlite3')
        before_rows = rows()
        for name in sorted(SERVER_FILES):
            target = ROOT / name; saved = backup / 'files' / name
            if target.exists():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            applied.append(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / name, target)
            target.chmod(0o644)
        for record in guard['client_files'].values():
            target = LIVE / 'blobs' / record['sha256']
            if target.exists():
                require(digest(target) == record['sha256'] and target.stat().st_size == record['size'], 'Existing immutable blob differs')
            else:
                shutil.copyfile(stage / 'client/blobs' / record['sha256'], target)
                target.chmod(0o644)
        check = command('runuser', '-u', 'tio', '--', str(ROOT / '.venv/bin/python'), '-m', 'server', '--config', str(CONFIG), '--check')
        require((LIVE / 'manifest.json').read_bytes() == old, 'Client baseline changed during deployment')
        publish_manifest(new, 'manifest-arena-surroundings.new')
        command('systemctl', 'start', 'tio-server')
        time.sleep(1)
        require(command('systemctl', 'is-active', 'tio-server') == 'active', 'Updated service is not active')
        after_rows = rows()
        require(all(not (data - after_rows.get(table, Counter())) for table, data in before_rows.items()),
                'A previous hosted row changed or disappeared')
        health = database_state()
        require(health['integrity'] == 'ok', 'Post-deployment database integrity failed')
        require(all(digest(ROOT / name) == entry['after'] for name, entry in guard['server_files'].items()), 'Applied source verification failed')
        report = dict(backup=str(backup), service='active', client_version=release['version'],
                      new_client_files=len(guard['client_files']), previous_client_records_preserved=len(old_records),
                      existing_tables_preserved=len(before_rows), database_uploaded=False,
                      server_files={name: digest(ROOT / name) for name in SERVER_FILES},
                      client_manifest_sha256=sha(new), preflight=check, health=health,
                      candidate_tests=candidate['total_tests'])
        (backup / 'deployment.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)
    except BaseException:
        command('systemctl', 'stop', 'tio-server')
        for name in applied:
            target = ROOT / name; saved = backup / 'files' / name
            if saved.exists():
                shutil.copy2(saved, target)
            else:
                target.unlink(missing_ok=True)
        publish_manifest(old, 'manifest-arena-surroundings-rollback.new')
        command('systemctl', 'start', 'tio-server')
        # Preserve the current hosted database, including legitimate later rows.
        raise


if __name__ == '__main__':
    main()
