"""Bind release .3 to 25 original native captures and final read-only health.

Run only after all five owned graphical matches are cleaned up. This helper
does not create accounts, run clients/matches, publish, or change hosted data.
--self-test is offline. --gallery-only validates available local originals.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_arena_boundaries as publication
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

OUT = ROOT / 'reports/arena-boundaries-implementation'
SHOTS = OUT / 'screenshots'
QA = ROOT / 'reports/arena-surroundings-implementation/client-qa'
VERSION = '2026.10.07.3'
SOURCE = '@oai/sky get_window_state original JPEG'
SOURCES = {'JPEG': SOURCE, 'PNG': '@oai/sky get_window_state original PNG'}
CITIES = {
    'reservation': ('rv', 'R', 'Reservation'),
    'denver': ('de', 'D', 'Denver'),
    'new_york': ('ny', 'N', 'New York'),
    'military_zone': ('mz', 'M', 'Military Zone'),
}
CASES = [(city, 0, 38) for city in CITIES] + [('military_zone', 1, 57)]
SIDES = ('NW', 'NE', 'SW', 'SE')
require = publication.require
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def case_key(city, mode):
    return city + ('-mode1' if mode == 1 else '')


class Evidence:
    def __init__(self):
        self.hashes = {}

    def raw(self, path):
        path = Path(path)
        require(not path.is_symlink(), 'Evidence cannot be a symbolic link')
        path = path.resolve()
        require(path.is_relative_to(ROOT.resolve()) and path.is_file(),
                'Evidence must be a regular workspace file')
        require(not path.is_relative_to(ROOT / 'reports/arena-surroundings/private'),
                'Private credentials cannot become public evidence')
        raw = path.read_bytes()
        self.hashes[path.relative_to(ROOT).as_posix()] = sha(raw)
        return raw

    def read(self, path, *, passed=True):
        value = json.loads(self.raw(path))
        require(not passed or value.get('passed') is True,
                'Incomplete evidence: ' + Path(path).name)
        return value


def timestamp(value):
    require(isinstance(value, str), 'Capture time must be ISO8601 text')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Capture time needs a timezone')
    require(parsed.timestamp() <= datetime.now(timezone.utc).timestamp() + 30,
            'Capture time lies in the future')
    return parsed.timestamp()


def capture_records(value):
    if isinstance(value, dict):
        value = value.get('records', value.get('captures'))
    require(isinstance(value, list), 'captures.json needs a list or records list')
    return value


def validate_capture(record, folder, match=None):
    from PIL import Image
    city, mode = record.get('city'), record.get('mode')
    require(city in CITIES and type(mode) is int and mode in (0, 1),
            'Capture city/mode is invalid')
    width = 38 if mode == 0 else 57
    require((city, mode, width) in CASES, 'Unexpected city/mode capture')
    client, side = record.get('client'), record.get('side')
    require((client == 'a' and side in SIDES) or (client == 'b' and side == 'initial'),
            'A needs four sides; B needs an initial view')
    name = record.get('file', '')
    stem = city + ('-57' if mode == 1 else '') + '-' + str(side) + '-' + str(client)
    require(name in (stem + '.jpg', stem + '.png'), 'Capture basename differs from its case/side/client')
    require(record.get('version') == VERSION and type(record.get('map_size')) is int
            and record['map_size'] == width, 'Capture release/field differs')
    require(record.get('source') in SOURCES.values(), 'Capture is not an original native-window image')
    require(re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')),
            'Capture SHA256 is missing')
    require(isinstance(record.get('match_id'), str) and bool(record['match_id']), 'Capture match ID is missing')
    prefix, letter, _ = CITIES[city]
    scene = re.fullmatch('as_' + prefix + r'_([1-3])_' + str(width), record.get('scene', ''))
    require(scene is not None, 'Capture has another city/size scene')
    require(str(record.get('variant')) in (scene[1], letter + scene[1]), 'Capture variant differs')
    captured = timestamp(record.get('captured_at', record.get('time')))
    if match is not None:
        require(record['match_id'] == match['match'] and record['scene'] == match['scene']
                and mode == match['mode'] and width == match['width'],
                'Capture differs from the real hosted match')
        require(captured >= match['disconnected_at_unix'] - 1,
                'Capture predates native reconnect staging')
    path = Path(folder) / name
    require(not path.is_symlink(), 'Capture cannot be a symbolic link')
    path = path.resolve()
    require(path.parent == Path(folder).resolve(), 'Capture path escapes screenshots folder')
    raw = path.read_bytes()
    require(sha(raw) == record['sha256'], 'Original image SHA differs: ' + name)
    with Image.open(io.BytesIO(raw)) as image:
        fmt = image.format
        require(fmt in SOURCES and record['source'] == SOURCES[fmt]
                and name.endswith('.jpg' if fmt == 'JPEG' else '.png'),
                'Actual image format/extension/source differ: ' + name)
        require(type(record.get('width')) is int and type(record.get('height')) is int
                and image.size == (record['width'], record['height']),
                'Original image dimensions differ: ' + name)
        require(1024 <= image.width <= 1200 and 768 <= image.height <= 900,
                'Capture must contain the full 1024x768 native window')
        image.verify()
    return path, raw


def validate_capture_set(records, *, complete=True):
    expected = {(city, mode, 'a', side) for city, mode, _ in CASES for side in SIDES} | {
        (city, mode, 'b', 'initial') for city, mode, _ in CASES}
    actual = {(r.get('city'), r.get('mode'), r.get('client'), r.get('side')) for r in records}
    require(len(actual) == len(records) and actual <= expected, 'Unexpected or duplicate capture slot')
    if complete:
        require(len(records) == 25 and actual == expected,
                'Exactly20 A-side captures and5 B-initial captures are required')
    require(len({r['file'].lower() for r in records}) == len(records)
            and len({r['sha256'] for r in records}) == len(records),
            'Every capture needs distinct original image bytes')


def validate_status(status, start, cleanup):
    clients = status.get('clients', [])
    require(status.get('event') == 'graphical_status' and len(clients) == 2,
            'Actual status of both native clients is required')
    observed = status.get('observed_at_unix')
    require(type(observed) in (int, float) and observed >= start['disconnected_at_unix'] - 1,
            'Native status predates this match')
    pids = []
    for client, account in zip(clients, start['graphical_accounts']):
        require(all(client.get(k) is True for k in
                    ('connected', 'authenticated', 'worldStartSent', 'charactersLoaded')),
                'Native client did not reach the authenticated world')
        require(all(type(client.get(k)) is int and client[k] == 0 for k in
                    ('authChallengeStatus', 'loginStatus', 'serverLoginStatus',
                     'gameAuth1Status', 'gameAuth2Status', 'characterSelectStatus')),
                'Native authentication or character selection failed')
        require(client.get('fault') is None and client.get('runtime_errors') == []
                and client.get('selectedCharacter', {}).get('name') == account,
                'Native fault/account/runtime error differs')
        require(client.get('selectedServer', {}).get('host') == '185.184.42.88'
                and client['selectedServer'].get('port') == 28513, 'Native client used another host')
        camera, pid = client.get('camera', {}), client.get('pid')
        require(type(pid) is int and pid > 0 and camera.get('pid') == pid
                and camera.get('read_only') is True and camera.get('available') is True
                and camera.get('field_width') == start['width']
                and camera.get('field_height') == start['height']
                and camera.get('updates', 0) > 0 and camera.get('runtime_errors') == [],
                'Native camera/status field is incomplete')
        pids.append(pid)
    require(len(set(pids)) == 2 and pids == cleanup.get('native_pids'),
            'Observed native PIDs differ from the two owned cleanup PIDs')


def validate_cleanup(cleanup, start, roster):
    require(cleanup.get('match') == start['match'] and cleanup.get('checkpoint_cleared') is True
            and cleanup.get('online') == 0, 'Owned match cleanup failed')
    forfeits = cleanup.get('explicit_forfeit_accounts', [])
    hashes = cleanup.get('replay_ground_hashes', [])
    require(isinstance(forfeits, list) and len(set(forfeits)) == len(forfeits)
            and set(forfeits) <= set(roster), 'Cleanup includes duplicate or foreign accounts')
    require(hashes == [start['ground_sha256']] * len(forfeits),
            'Cleanup reconnect shared authoritative ground differs')
    require(bool(forfeits) or cleanup.get('already_cleared') is True,
            'Cleanup needs explicit owned forfeit or an already-cleared checkpoint')
    require(cleanup.get('preservation', {}).get('integrity') == 'ok'
            and cleanup['preservation'].get('existing_account_rows_preserved', {}).get('accounts', 0) > 0,
            'Original-account preservation evidence is incomplete')


def validate_matches(evidence, fixture, manifest):
    resources = publication.gate.records(manifest)
    matches = {}
    for city, mode, size in CASES:
        key = case_key(city, mode)
        stem = fixture.prefix + '-' + key
        start = evidence.read(OUT / 'client-qa/matches' / (stem + '.json'))
        cleanup = evidence.read(OUT / 'client-qa/matches' / (stem + '-cleanup.json'))
        count = 2 if mode == 0 else 4
        require(len(fixture.names) >= count, 'Mode1 needs four existing owned accounts')
        roster = fixture.names[:count]
        for report, action in ((start, 'start'), (cleanup, 'cleanup')):
            require(report.get('action') == action and report.get('city') == city
                    and type(report.get('mode')) is int and report['mode'] == mode
                    and report.get('accounts') == roster and report.get('accounts_created') == 0,
                    'Owned match scope differs')
        require(start.get('client_version') == VERSION and start.get('host') == fixture.host
                and start.get('participants') == count and start.get('bots') == 0
                and start.get('width') == start.get('height') == size
                and start.get('graphical_accounts') == fixture.names[:2]
                and start.get('disconnected_additional_accounts') == fixture.names[2:count]
                and start.get('owned_roster_verified') is True and start.get('checkpoint_preserved') is True,
                'Real native match staging is incomplete')
        prefix = CITIES[city][0]
        require(re.fullmatch('as_' + prefix + r'_[1-3]_' + str(size), start.get('scene', ''))
                and str(start.get('variant')) == start['scene'].split('_')[2], 'Match scene differs')
        brushes = set(start.get('brushes', []))
        require(bool(brushes) and (brushes <= {10, 11} if city == 'reservation' else
                brushes == {{'denver': 3, 'new_york': 2, 'military_zone': 1}[city]}),
                'City terrain brush differs')
        resource = start.get('published_resource', {})
        path = 'base/maps/' + start['scene'] + '.s'
        require(resource.get('path') == path and resource.get('sha256') == resources[path]['sha256']
                and len(resource.get('sides', [])) == len(resource.get('corners', [])) == 4,
                'Hosted scene differs from .3 manifest or four-side proof')
        validate_cleanup(cleanup, start, roster)
        status = evidence.read(OUT / 'client-qa' / (key + '-native-status.json'), passed=False)
        validate_status(status, start, cleanup)
        matches[(city, mode)] = start
    require(len({m['match'] for m in matches.values()}) == 5, 'Cases cannot share one staged match')
    return matches


def validate_copies(evidence, manifest, guard):
    resources = publication.gate.records(manifest)
    prepared = evidence.read(QA / 'prepared-copies.json', passed=False)
    require(prepared.get('client_version') == VERSION
            and prepared.get('manifest_sha256') == guard['new_manifest_sha256']
            and prepared.get('personal_files_copied') == prepared.get('accounts_created') == 0,
            'Dedicated native copies were not prepared from .3')
    for letter in ('a', 'b'):
        folder = QA / ('game-' + letter)
        require((folder / '.tio-owned-qa').is_file(), 'Dedicated QA ownership marker is missing')
        proof = evidence.read(folder / 'qa-client-provenance.json', passed=False)
        require(Path(proof.get('game_root', '')).resolve() == folder.resolve()
                and proof.get('manifest_version') == VERSION
                and proof.get('manifest_sha256') == guard['new_manifest_sha256']
                and proof.get('manifest_files') == len(resources)
                and proof.get('non_config_files_verified') == len(resources) - 2,
                'Actual native copy provenance is incomplete')
        pins = {name: resources[name]['sha256'] for name in ('ti.exe', 'silver.dll', 'orange.dll')}
        require(proof.get('native_pins') == pins, 'Original native binary pins differ')
        for name, digest in pins.items():
            require(sha(evidence.raw(folder / name)) == digest, 'On-disk native binary changed')
        for path, replacement in guard['replacements'].items():
            raw = (folder / path).read_bytes()
            require(sha(raw) == replacement['after']['sha256'] and len(raw) == replacement['after']['size'],
                    'Native copy has an obsolete or modified boundary resource')


def readonly_health_source():
    marker = '\ndef atomic_manifest('
    remote = publication.transport.REMOTE
    require(remote.count(marker) == 1, 'Publisher read-only boundary changed')
    source = remote.split(marker, 1)[0]
    equality = (" check(state['accounts']==b['database']['accounts'] and state['table_counts']==b['database']['table_counts'],\n"
                "       'Hosted database table-count drift')\n")
    require(source.count(equality) == 1, 'Publisher database count guard changed')
    source = source.replace(equality, '')
    source += "\nOLD='2026.10.07.2';NEW='2026.10.07.3'\n" + '''
def main(request):
 check(request['action']=='final-health','Only final read-only health is supported')
 g=request['guard'];result=health(g,g['new_manifest_sha256'])
 state=result['database']
 check(state['table_counts']['battle_checkpoint_members']==0,'Checkpoint members remain')
 actual=json.loads((LIVE/'manifest.json').read_bytes())
 check(actual['version']==NEW,'Hosted release version differs')
 result.update(passed=True,read_only=True,client_version=actual['version'],checkpoint_members=0)
 return result
'''
    tree = ast.parse(source)
    forbidden = {'write', 'write_text', 'write_bytes', 'unlink', 'replace', 'mkdir',
                 'chmod', 'copy', 'copy2', 'backup', 'connect_ex'}
    require(not any(isinstance(node, ast.Attribute) and node.attr in forbidden
                    and not (node.attr == 'replace' and isinstance(node.value, ast.Name)
                             and node.value.id == 'name') for node in ast.walk(tree)),
            'Final health includes a mutation endpoint')
    return source


def fresh_health(guard):
    original = publication.transport.REMOTE
    try:
        publication.transport.REMOTE = readonly_health_source()
        return publication.transport.remote('final-health', guard)
    finally:
        publication.transport.REMOTE = original


def render_gallery(records, *, complete=False):
    indexed = {(r['city'], r['mode'], r['client'], r['side']): r for r in records}
    sections = []
    labels = {'NW': 'Северо-запад', 'NE': 'Северо-восток', 'SW': 'Юго-запад',
              'SE': 'Юго-восток', 'initial': 'Начальный вид'}
    for city, mode, size in CASES:
        key, title = case_key(city, mode), CITIES[city][2]
        title += f' · {size}×{size}'
        cards = []
        for client, side in [('a', s) for s in SIDES] + [('b', 'initial')]:
            record = indexed.get((city, mode, client, side))
            label = f'Клиент {client.upper()} · {labels[side]}'
            if record:
                name = quote(record['file'])
                cards.append('<figure><a href="' + name + '"><img loading="lazy" src="' + name
                    + '" alt="' + html.escape(title + ' ' + label) + '"></a><figcaption>' + label
                    + '<br>' + html.escape(record['scene']) + f' · режим {mode}<br><small>'
                    + html.escape(record.get('captured_at', record.get('time', '')))
                    + f'<br>Размер оригинала: {record["width"]}×{record["height"]}'
                    + '<br>Матч ' + html.escape(record['match_id']) + '<br>SHA256 '
                    + html.escape(record['sha256']) + '</small></figcaption></figure>')
            else:
                cards.append('<figure class="pending"><p>Кадр ожидается</p><figcaption>'
                             + label + '</figcaption></figure>')
        sections.append('<section id="' + key + '"><h2>' + title + '</h2><div class="grid">'
                        + ''.join(cards) + '</div></section>')
    status = ('Проверены 25 исходных снимков и их связь с пятью настоящими hosted матчами.' if complete else
              f'Сбор исходных кадров продолжается: {len(records)}/25. Финальная проверка ещё не завершена.')
    metadata_link = ('<a href="captures.json">Метаданные кадров</a>' if records or complete else
                     '<span>Метаданные кадров ожидаются</span>')
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Границы арен · 2026.10.07.3</title><style>
body{margin:0;background:#151812;color:#e9eddf;font:16px/1.5 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:28px}
h1{font-size:28px}h2{margin-top:36px}a{color:#c8ddb2}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
figure{margin:0;background:#22281d;border:1px solid #4a5740;border-radius:8px;overflow:hidden}img{display:block;width:100%;height:auto}
figcaption{padding:14px}small{display:block;overflow-wrap:anywhere;color:#b9c3ac;font-size:12px}.pending{min-height:160px;padding:20px}
.note{max-width:1100px;color:#c2cbb7}nav{display:flex;flex-wrap:wrap;gap:20px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style><main><h1>Выбранные границы городских арен</h1><p>Версия 2026.10.07.3 · вариант A для четырёх городов · постоянное затемнение окружения сохранено</p><p>''' + status + '''</p>
<p class="note">Это исходные изображения настоящих окон клиента, полученные через @oai/sky get_window_state; они не пересобраны и не перерисованы.
Нажмите на кадр для открытия оригинала. Для каждого матча показаны четыре стороны клиента A и стартовый вид клиента B.
Съёмка охватывает четыре города в режиме 0 (38×38) и Military Zone в режиме 1 (57×57), по одному случайному варианту на матч.
Проверка всех 24 сцен, восьми периметров и сохранности игровой геометрии проводится отдельно по локальным и native доказательствам.
Автоматическая проверка происхождения кадров не заменяет визуальную оценку границ и углов.</p>
<nav><a href="#reservation">Reservation</a><a href="#denver">Denver</a><a href="#new_york">New York</a>
<a href="#military_zone">Military Zone 38×38</a><a href="#military_zone-mode1">Military Zone 57×57</a>
''' + metadata_link + '</nav>' + ''.join(sections) + '</main></html>\n'


def main(fixture_path, tests_path):
    evidence = Evidence()
    release, guard, old_raw, new_raw = publication.load_bundle()
    deployment = evidence.read(OUT / 'deployment.json')
    delta = guard['manifest_delta']
    require(deployment.get('version') == VERSION and deployment.get('previous_version') == '2026.10.07.2'
            and deployment.get('patch_zip_sha256') == release['patch_zip_sha256']
            and all(deployment.get(k) == delta[k] for k in
                    ('changed_scene_records', 'new_resource_records', 'unchanged_existing_records')),
            'Completed deployed .3 release differs from its reviewed bundle')
    require(all(deployment.get(k) is False for k in ('database_uploaded', 'database_replaced',
                'code_uploaded', 'configuration_changed', 'service_restarted'))
            and all(deployment.get(k) is True for k in ('pid_unchanged', 'all_hosted_table_rows_preserved',
                'launcher_executable_and_download_metadata_preserved', 'public_https_passed', 'postflight_passed')),
            'Client-only preservation or publication proof failed')
    for name in ('release-verification.json', 'asset-verification.json', 'guard.json'):
        evidence.read(OUT / name, passed=name != 'guard.json')
    proofs = {
        'proofs/boundary-proof.json': ROOT / 'assets/arena-boundaries-v1/boundary-proof.json',
        'proofs/asset-verification.json': OUT / 'asset-verification.json',
        'proofs/local-tests.json': tests_path,
        'proofs/native-fog-tint.json': ROOT / 'reports/arena-surroundings-fog/native-fog-tint.json',
        'proofs/native-v1.json': ROOT / 'reports/arena-surroundings-implementation/native.json',
        'proofs/approved-proposals.json': ROOT / 'assets/arena-boundary-proposals-v1/review.json',
    }
    for packaged, path in proofs.items():
        require(sha(evidence.raw(path)) == guard['proof_files'][packaged], 'Frozen proof file changed: ' + packaged)
    tests = evidence.read(tests_path)
    require(max(tests.get('tests_run', 0), tests.get('checks', 0)) > 0
            and tests.get('failures', 0) == tests.get('errors', 0) == 0, 'Local tests are incomplete')
    native = evidence.read(proofs['proofs/native-fog-tint.json'], passed=False)
    publication.prep.fog.validate_native_proof(native, guard['native_v1_proof_sha256'])
    https = evidence.read(OUT / 'https-release.json')
    require(https.get('client_version') == VERSION and https.get('manifest_sha256') == guard['new_manifest_sha256']
            and https.get('verified_changed_and_new_resources') == len(guard['replacements'])
            and https.get('b1_tiles_preserved') == https.get('source_pngs_preserved') == 552
            and https.get('legacy_records_preserved') == 5090, 'Actual public boundary release proof differs')
    require(sha(evidence.raw(OUT / 'client-release/manifest.json')) == guard['new_manifest_sha256'],
            'Local release manifest changed')
    manifest = json.loads(new_raw)
    fixture = FreshSurroundingsQA.load_private(fixture_path)
    require(fixture.host == '185.184.42.88', 'Only established hosted QA fixture is supported')
    matches = validate_matches(evidence, fixture, manifest)
    validate_copies(evidence, manifest, guard)
    captures = capture_records(evidence.read(SHOTS / 'captures.json', passed=False))
    validate_capture_set(captures)
    for record in captures:
        path, _ = validate_capture(record, SHOTS, matches[(record['city'], record['mode'])])
        evidence.raw(path)
    # Neither operation below can mutate hosted game/player data.
    require(publication.transport.get(publication.transport.ORIGIN + 'manifest.json') == new_raw,
            'Fresh public HTTPS manifest changed')
    health = fresh_health(guard)
    preservation = fixture.preservation()
    require(preservation.get('integrity') == 'ok'
            and preservation.get('existing_account_rows_preserved', {}).get('accounts', 0) > 0,
            'Fresh original-account preservation failed')
    SHOTS.mkdir(parents=True, exist_ok=True)
    (SHOTS / 'review.html').write_text(render_gallery(captures, complete=True), encoding='utf-8')
    gallery_proof = dict(schema='arena-boundaries-original-captures/v1', passed=True,
        version=VERSION, originals=25, a_side_captures=20, b_initial_captures=5,
        cases=[dict(city=city, mode=mode, map_size=size) for city, mode, size in CASES],
        source='Original JPEG/PNG @oai/sky native window captures; source verified against actual image format.',
        captures_sha256=sha((SHOTS / 'captures.json').read_bytes()),
        review_html_sha256=sha((SHOTS / 'review.html').read_bytes()),
        checks=dict(original_bytes_formats_and_dimensions=True, five_matches_four_a_sides=True,
            two_authenticated_native_clients_per_match=True, owned_pid_match=True,
            scene_variant_mode_size=True, all_matches_cleaned_up=True),
        visual_review_automatically_claimed=False,
        limitation='Provenance/structure checks cannot independently prove screenshot source, assess aesthetics, or cover every camera angle.')
    publication.save(SHOTS / 'gallery-verification.json', gallery_proof)
    evidence.raw(SHOTS / 'review.html'); evidence.raw(SHOTS / 'gallery-verification.json')
    report = dict(schema='arena-boundaries-completion/v1', passed=True,
        verified_at_utc=datetime.now(timezone.utc).isoformat(), version=VERSION,
        manifest_sha256=guard['new_manifest_sha256'], **delta,
        local_tests=max(tests.get('tests_run', 0), tests.get('checks', 0)),
        graphical_matches=5, actual_native_clients_per_match=2, bots=0,
        owned_participants_by_case={case_key(city, mode): (2 if mode == 0 else 4) for city, mode, _ in CASES},
        screenshots=25, four_side_screenshots=20, second_client_screenshots=5,
        graphical_scope='Four cities mode0/38x38 and Military Zone mode1/57x57; one random variant per match.',
        selected_boundary_variant='A', border_proposals_integrated=True,
        native_tcolor_hex='00b1b1b1', alpha=255, all_native_binary_bytes_unchanged=True,
        gameplay_geometry_preserved=True, inherited_outside_fog_preserved=True,
        remote_backup=deployment['backup'], database_uploaded=False, code_uploaded=False,
        service_restarted=False, health=health, preservation=preservation, evidence_sha256=evidence.hashes,
        limitations=['GUI captures sample five matches rather than all12 variants and every camera angle.',
            'All24 scene append operations and eight boundary rings use separate exact-byte/native/pixel proofs.',
            'Original low native materials may differ in detail from concept drawings; full native scale and biome remain unchanged.'])
    publication.save(OUT / 'completion.json', report)
    print(json.dumps(dict(passed=True, version=VERSION, screenshots=25, graphical_matches=5,
        service=health['service'], established_connections=health['established_connections'],
        original_accounts_preserved=True)))
    return report


def self_test():
    from PIL import Image
    checks = 0
    with tempfile.TemporaryDirectory(prefix='tio-boundary-final-offline-') as local:
        folder = Path(local)
        for fmt, suffix in (('JPEG', '.jpg'), ('PNG', '.png')):
            buffer = io.BytesIO(); Image.new('RGB', (1026, 795), '#252b20').save(buffer, format=fmt)
            raw = buffer.getvalue(); name = 'denver-NW-a' + suffix; (folder / name).write_bytes(raw)
            record = dict(file=name, city='denver', mode=0, side='NW', client='a', version=VERSION,
                match_id='offline', scene='as_de_1_38', variant='D1', map_size=38, source=SOURCES[fmt],
                sha256=sha(raw), width=1026, height=795, captured_at='2026-10-07T00:00:00Z')
            validate_capture(record, folder); checks += 1
            bad_values = {'file':'../' + name, 'city':'reservation', 'version':'2026.10.07.2',
                'source':'imagegen', 'client':'b', 'map_size':57, 'mode':True, 'sha256':'0'*64,
                'width':1024, 'variant':'D2', 'captured_at':'2026-10-07T00:00:00'}
            for key, value in bad_values.items():
                try: validate_capture(dict(record, **{key:value}), folder)
                except (RuntimeError, ValueError): checks += 1
                else: raise AssertionError('Bad capture accepted: ' + key)
        png = folder / 'denver-NW-a.png'
        jpg = folder / 'denver-NW-a.jpg'
        jpg.write_bytes(png.read_bytes())
        mismatched = dict(record, file=jpg.name, source=SOURCE, sha256=sha(jpg.read_bytes()))
        try: validate_capture(mismatched, folder)
        except RuntimeError: checks += 1
        else: raise AssertionError('PNG renamed JPEG accepted')
        buffer = io.BytesIO(); Image.new('RGB', (1026, 795), '#343321').save(buffer, format='JPEG')
        raw = buffer.getvalue(); name = 'military_zone-57-NW-a.jpg'; (folder / name).write_bytes(raw)
        large = dict(record, file=name, city='military_zone', mode=1, map_size=57, scene='as_mz_2_57',
                     variant='M2', source=SOURCE, sha256=sha(raw))
        staged = dict(match='offline', scene='as_mz_2_57', mode=1, width=57, disconnected_at_unix=1)
        validate_capture(large, folder, staged); checks += 1
        for key, value in (('match', 'other'), ('scene', 'as_mz_1_57'), ('mode', 0), ('width', 38)):
            try: validate_capture(large, folder, dict(staged, **{key:value}))
            except RuntimeError: checks += 1
            else: raise AssertionError('Unrelated hosted match accepted: ' + key)
        records = [dict(city=city, mode=mode, client=client, side=side,
            file=f'{city}-{size}-{client}-{side}.jpg', sha256=sha(f'{city}-{mode}-{client}-{side}'.encode()))
            for city, mode, size in CASES for client, side in [('a', s) for s in SIDES] + [('b', 'initial')]]
        validate_capture_set(records); checks += 1
        for invalid in (records[:-1], records + [records[0]], [records[0]]*25,
                        [dict(r, mode=0) for r in records]):
            try: validate_capture_set(invalid)
            except RuntimeError: checks += 1
            else: raise AssertionError('Incomplete/duplicate capture set accepted')
        validate_capture_set(records[:2], complete=False); checks += 1
        start = dict(graphical_accounts=['owna', 'ownb'], disconnected_at_unix=1, width=57, height=57)
        clients = []
        for pid, account in ((10, 'owna'), (20, 'ownb')):
            client = {k:True for k in ('connected', 'authenticated', 'worldStartSent', 'charactersLoaded')}
            client.update({k:0 for k in ('authChallengeStatus', 'loginStatus', 'serverLoginStatus',
                'gameAuth1Status', 'gameAuth2Status', 'characterSelectStatus')})
            client.update(fault=None, runtime_errors=[], selectedCharacter=dict(name=account),
                selectedServer=dict(host='185.184.42.88', port=28513), pid=pid,
                camera=dict(pid=pid, read_only=True, available=True, field_width=57, field_height=57,
                            updates=1, runtime_errors=[]))
            clients.append(client)
        status = dict(event='graphical_status', observed_at_unix=2, clients=clients)
        cleanup = dict(native_pids=[10, 20])
        validate_status(status, start, cleanup); checks += 1
        for field, value in (('connected', False), ('gameAuth2Status', 1), ('runtime_errors', ['fault']), ('pid', 30)):
            invalid = copy.deepcopy(status); invalid['clients'][1][field] = value
            try: validate_status(invalid, start, cleanup)
            except RuntimeError: checks += 1
            else: raise AssertionError('Invalid native status accepted: ' + field)
        invalid = copy.deepcopy(status); invalid['clients'][1]['camera']['field_width'] = 38
        try: validate_status(invalid, start, cleanup)
        except RuntimeError: checks += 1
        else: raise AssertionError('Wrong native field size accepted')
        roster = ['owna', 'ownb', 'ownc', 'ownd']
        staged_cleanup = dict(match='owned', ground_sha256='a'*64)
        valid_cleanup = dict(match='owned', checkpoint_cleared=True, online=0,
            explicit_forfeit_accounts=roster, replay_ground_hashes=['a'*64]*4,
            preservation=dict(integrity='ok', existing_account_rows_preserved=dict(accounts=177)))
        validate_cleanup(valid_cleanup, staged_cleanup, roster); checks += 1
        partial = dict(valid_cleanup, explicit_forfeit_accounts=['ownc', 'ownd'], replay_ground_hashes=['a'*64]*2)
        validate_cleanup(partial, staged_cleanup, roster); checks += 1
        for field, value in (('explicit_forfeit_accounts', ['foreign']),
                ('explicit_forfeit_accounts', ['owna', 'owna']), ('replay_ground_hashes', ['a'*64]*2),
                ('checkpoint_cleared', False), ('online', 1)):
            try: validate_cleanup(dict(valid_cleanup, **{field:value}), staged_cleanup, roster)
            except RuntimeError: checks += 1
            else: raise AssertionError('Invalid mode1 cleanup accepted: ' + field)
        cleared = dict(valid_cleanup, explicit_forfeit_accounts=[], replay_ground_hashes=[], already_cleared=True)
        validate_cleanup(cleared, staged_cleanup, roster); checks += 1
        fixture = type('OfflineFixture', (), dict(prefix='qs1234abcd', names=roster, host='185.184.42.88'))()
        reports, resources = {}, []
        for city, mode, size in CASES:
            key = case_key(city, mode); scope = roster[:2 if mode == 0 else 4]
            scene = f'as_{CITIES[city][0]}_1_{size}'
            published = dict(path='base/maps/' + scene + '.s', sha256='b'*64, size=34)
            resources.append(published)
            staged = dict(action='start', passed=True, city=city, mode=mode, accounts=scope,
                accounts_created=0, client_version=VERSION, host=fixture.host, participants=len(scope), bots=0,
                width=size, height=size, graphical_accounts=roster[:2], disconnected_additional_accounts=scope[2:],
                owned_roster_verified=True, checkpoint_preserved=True, scene=scene, variant='1',
                brushes=[{'reservation':10, 'denver':3, 'new_york':2, 'military_zone':1}[city]],
                published_resource=dict(published, sides=[1,2,3,4], corners=[1,2,3,4]),
                match=key, ground_sha256='a'*64, disconnected_at_unix=1)
            ended = dict(valid_cleanup, action='cleanup', passed=True, city=city, mode=mode,
                match=key, accounts=scope, accounts_created=0, native_pids=[10,20],
                explicit_forfeit_accounts=scope, replay_ground_hashes=['a'*64]*len(scope))
            native_status = copy.deepcopy(status)
            for c in native_status['clients']:
                c['camera'].update(field_width=size, field_height=size)
            reports[f'{fixture.prefix}-{key}.json'] = staged
            reports[f'{fixture.prefix}-{key}-cleanup.json'] = ended
            reports[f'{key}-native-status.json'] = native_status
        class OfflineEvidence:
            def read(self, path, **kwargs):
                return copy.deepcopy(reports[Path(path).name])
        manifest = dict(schema=1, version=VERSION, files=resources)
        validate_matches(OfflineEvidence(), fixture, manifest); checks += 1
        report_name = fixture.prefix + '-military_zone-mode1.json'
        original_stage = reports[report_name]
        for field, value in (('participants',2), ('accounts',roster[:2]),
                             ('disconnected_additional_accounts',[])):
            reports[report_name] = dict(original_stage, **{field:value})
            try: validate_matches(OfflineEvidence(), fixture, manifest)
            except RuntimeError: checks += 1
            else: raise AssertionError('Incomplete mode1 owned roster accepted: ' + field)
        reports[report_name] = original_stage
        source = readonly_health_source(); compile(source, '<readonly-boundary-final-health>', 'exec'); checks += 1
        require('Hosted database table-count drift' not in source and 'def atomic_manifest' not in source
                and 'def main' in source and '?mode=ro' in source and "NEW='2026.10.07.3'" in source,
                'Read-only health source differs'); checks += 1
        original = publication.transport.REMOTE
        try:
            publication.transport.REMOTE = original.replace('Hosted database table-count drift', 'changed guard')
            try: readonly_health_source()
            except RuntimeError: checks += 1
            else: raise AssertionError('Changed remote boundary accepted')
        finally: publication.transport.REMOTE = original
        try:
            publication.transport.REMOTE = original.replace('def health(g,manifest_sha):',
                "def health(g,manifest_sha):\n Path('/tmp/forbidden').write_bytes(b'x')")
            try: readonly_health_source()
            except RuntimeError: checks += 1
            else: raise AssertionError('Injected health mutation accepted')
        finally: publication.transport.REMOTE = original
        gallery = render_gallery([])
        require('0/25' in gallery and gallery.count('Кадр ожидается') == 25
                and '57×57' in gallery and 'Финальная проверка ещё не завершена' in gallery,
                'Partial gallery falsely claims completion'); checks += 1
    report = dict(passed=True, offline_self_test='passed', checks=checks, server_contacted=False,
        clients_started=0, accounts_created=0, hosted_mutations=0)
    publication.save(OUT / 'finalizer-self-test.json', report)
    print(json.dumps(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--tests-report', type=Path, default=OUT / 'local-tests.json')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--gallery-only', action='store_true', help='Render available local original images; no hosted checks')
    args = parser.parse_args()
    require(not (args.self_test and args.gallery_only), 'Choose one offline action')
    if args.self_test:
        self_test()
    elif args.gallery_only:
        capture_path = SHOTS / 'captures.json'
        records = capture_records(json.loads(capture_path.read_bytes())) if capture_path.is_file() else []
        validate_capture_set(records, complete=False)
        for record in records:
            validate_capture(record, SHOTS)
        SHOTS.mkdir(parents=True, exist_ok=True)
        (SHOTS / 'review.html').write_text(render_gallery(records), encoding='utf-8')
        print(json.dumps(dict(local_gallery=True, captures=len(records), server_contacted=False, final_verified=False)))
    else:
        require(args.fixture is not None, '--fixture is required for final verification')
        main(args.fixture, args.tests_report)
