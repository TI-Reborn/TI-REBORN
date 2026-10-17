"""Bind release .2 to completed native GUI captures and fresh read-only health.

Run only after all four owned graphical matches have been cleaned up. This
helper never creates accounts, starts clients/matches, publishes, or changes
hosted data. --self-test is entirely offline; --gallery-only reads local JPEGs.
"""
import argparse
import ast
import copy
import hashlib
import html
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_arena_fog as publication
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

OUT = ROOT/'reports/arena-surroundings-fog'
SHOTS = OUT/'screenshots'
QA = ROOT/'reports/arena-surroundings-implementation/client-qa'
VERSION = '2026.10.07.2'
SOURCE = '@oai/sky get_window_state original JPEG'
CITIES = {'reservation': ('rv', 'R', 'Reservation'),
          'denver': ('de', 'D', 'Denver'),
          'new_york': ('ny', 'N', 'New York'),
          'military_zone': ('mz', 'M', 'Military Zone')}
SIDES = ('NW', 'NE', 'SW', 'SE')
require = publication.require
sha = lambda raw: hashlib.sha256(raw).hexdigest()


class Evidence:
    def __init__(self):
        self.hashes = {}

    def raw(self, path):
        path = Path(path)
        require(not path.is_symlink(), 'Evidence cannot be a symbolic link')
        path = path.resolve()
        require(path.is_relative_to(ROOT.resolve()),
                'Evidence must be a regular workspace file')
        require(not path.is_relative_to(ROOT/'reports/arena-surroundings/private'),
                'Private credentials cannot become public evidence')
        raw = path.read_bytes()
        self.hashes[path.relative_to(ROOT).as_posix()] = sha(raw)
        return raw

    def read(self, path, *, passed=True):
        value = json.loads(self.raw(path))
        require(not passed or value.get('passed') is True,
                'Incomplete evidence: '+Path(path).name)
        return value


def timestamp(value):
    require(isinstance(value, str), 'Capture time must be ISO8601 text')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'Capture time needs a timezone')
    require(parsed.timestamp() <= datetime.now(timezone.utc).timestamp()+30,
            'Capture time lies in the future')
    return parsed.timestamp()


def capture_records(value):
    if isinstance(value, dict):
        value = value.get('records', value.get('captures'))
    require(isinstance(value, list), 'captures.json needs a list or records list')
    return value


def validate_capture(record, folder, match=None):
    from PIL import Image
    city = record.get('city')
    require(city in CITIES, 'Unexpected capture city')
    require((record.get('client') == 'a' and record.get('side') in SIDES) or
            (record.get('client') == 'b' and record.get('side') == 'initial'),
            'A needs four sides; B needs an initial view')
    name = record.get('file', '')
    require(re.fullmatch(r'[A-Za-z0-9_-]+\.(jpg|jpeg)', name, re.IGNORECASE),
            'Capture filename must be a local JPEG basename')
    require(record.get('version') == VERSION and record.get('source') == SOURCE
            and type(record.get('map_size')) is int and record['map_size'] == 38,
            'Capture release/source/field differs')
    require(re.fullmatch(r'[0-9a-f]{64}', record.get('sha256', '')),
            'Capture SHA256 is missing')
    prefix, letter, _ = CITIES[city]
    scene = re.fullmatch('as_'+prefix+r'_([1-3])_38', record.get('scene', ''))
    require(scene is not None, 'Capture has another city/size scene')
    variant = str(record.get('variant'))
    require(variant in (scene[1], letter+scene[1]), 'Capture variant differs')
    captured = timestamp(record.get('captured_at', record.get('time')))
    if match is not None:
        require(record.get('match_id') == match['match'] and
                record['scene'] == match['scene'], 'Capture differs from real hosted match')
        require(captured >= match['disconnected_at_unix']-1,
                'Capture predates native reconnect staging')
    path = (Path(folder)/name).resolve()
    require(path.parent == Path(folder).resolve() and not path.is_symlink(),
            'Capture path escapes the screenshots folder')
    raw = path.read_bytes()
    require(sha(raw) == record['sha256'], 'Original JPEG SHA differs: '+name)
    with Image.open(io.BytesIO(raw)) as image:
        require(image.format == 'JPEG' and image.size == (record.get('width'), record.get('height')),
                'JPEG format/dimensions differ: '+name)
        require(1024 <= image.width <= 1200 and 768 <= image.height <= 900,
                'Capture must contain the full 1024x768 native window')
        image.verify()
    return path, raw


def validate_capture_set(records):
    expected = {(city, 'a', side) for city in CITIES for side in SIDES} | {
        (city, 'b', 'initial') for city in CITIES}
    actual = {(r['city'], r['client'], r['side']) for r in records}
    require(len(records) == 20 and actual == expected,
            'Exactly16 A-side captures and4 B-initial captures are required')
    require(len({r['file'].lower() for r in records}) == 20 and
            len({r['sha256'] for r in records}) == 20,
            'Each capture needs its own original JPEG bytes')


def validate_status(status, start, cleanup):
    clients = status.get('clients', [])
    require(status.get('event') == 'graphical_status' and len(clients) == 2,
            'Actual status of both native clients is required')
    observed = status.get('observed_at_unix')
    require(type(observed) in (int, float) and observed >= start['disconnected_at_unix']-1,
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
        require(client.get('fault') is None and client.get('runtime_errors') == [] and
                client.get('selectedCharacter', {}).get('name') == account,
                'Native fault/account/runtime error differs')
        require(client.get('selectedServer', {}).get('host') == '185.184.42.88' and
                client['selectedServer'].get('port') == 28513, 'Native client used another host')
        camera = client.get('camera', {})
        pid = client.get('pid')
        require(type(pid) is int and pid > 0 and camera.get('pid') == pid and
                camera.get('read_only') is True and camera.get('available') is True and
                camera.get('field_width') == camera.get('field_height') == 38 and
                camera.get('updates', 0) > 0 and camera.get('runtime_errors') == [],
                'Native camera/status field is incomplete')
        pids.append(pid)
    require(len(set(pids)) == 2 and pids == cleanup.get('native_pids'),
            'Observed native PIDs differ from the two owned cleanup PIDs')


def validate_matches(evidence, fixture, manifest):
    records = publication.prep.records(manifest)
    matches = {}
    for city, (prefix, _, _) in CITIES.items():
        stem = fixture.prefix+'-'+city
        start = evidence.read(OUT/'client-qa/matches'/f'{stem}.json')
        cleanup = evidence.read(OUT/'client-qa/matches'/f'{stem}-cleanup.json')
        for report, action in ((start, 'start'), (cleanup, 'cleanup')):
            require(report.get('action') == action and report.get('city') == city and
                    report.get('mode') == 0 and report.get('accounts') == fixture.names[:2] and
                    report.get('accounts_created') == 0, 'Owned city match scope differs')
        require(start.get('client_version') == VERSION and start.get('host') == fixture.host and
                start.get('participants') == 2 and start.get('bots') == 0 and
                start.get('width') == start.get('height') == 38 and
                start.get('graphical_accounts') == fixture.names[:2] and
                start.get('owned_roster_verified') is True and
                start.get('checkpoint_preserved') is True, 'Real native match staging is incomplete')
        require(re.fullmatch('as_'+prefix+r'_[1-3]_38', start.get('scene', '')) and
                str(start.get('variant')) == start['scene'].split('_')[2], 'City match scene differs')
        brushes = set(start.get('brushes', []))
        require(bool(brushes) and (brushes <= {10, 11} if city == 'reservation' else
                brushes == {{'denver': 3, 'new_york': 2, 'military_zone': 1}[city]}),
                'City match terrain brush differs')
        resource = start.get('published_resource', {})
        path = 'base/maps/'+start['scene']+'.s'
        require(resource.get('path') == path and resource.get('sha256') == records[path]['sha256']
                and len(resource.get('sides', [])) == len(resource.get('corners', [])) == 4,
                'Hosted scene differs from the .2 manifest or four-sided resource proof')
        require(cleanup.get('match') == start['match'] and cleanup.get('checkpoint_cleared') is True
                and cleanup.get('online') == 0 and
                cleanup.get('explicit_forfeit_accounts') == fixture.names[:2] and
                cleanup.get('replay_ground_hashes') == [start['ground_sha256']]*2,
                'Owned match cleanup/shared encoded ground proof failed')
        require(cleanup.get('preservation', {}).get('integrity') == 'ok' and
                cleanup['preservation'].get('existing_account_rows_preserved', {}).get('accounts', 0) > 0,
                'Original-account preservation evidence is incomplete')
        status = evidence.read(OUT/'client-qa'/f'{city}-native-status.json', passed=False)
        validate_status(status, start, cleanup)
        matches[city] = start
    require(len({m['match'] for m in matches.values()}) == 4, 'Cities cannot share one staged match')
    return matches


def validate_copies(evidence, manifest, guard):
    records = publication.prep.records(manifest)
    prepared = evidence.read(QA/'prepared-copies.json', passed=False)
    require(prepared.get('client_version') == VERSION and
            prepared.get('manifest_sha256') == guard['new_manifest_sha256'] and
            prepared.get('personal_files_copied') == prepared.get('accounts_created') == 0,
            'Dedicated native copies were not prepared from release .2')
    for letter in ('a', 'b'):
        folder = QA/('game-'+letter)
        require((folder/'.tio-owned-qa').is_file(), 'Dedicated QA copy ownership marker is missing')
        proof = evidence.read(folder/'qa-client-provenance.json', passed=False)
        require(Path(proof.get('game_root', '')).resolve() == folder.resolve() and
                proof.get('manifest_version') == VERSION and
                proof.get('manifest_sha256') == guard['new_manifest_sha256'] and
                proof.get('manifest_files') == 6218 and proof.get('non_config_files_verified') == 6216,
                'Actual native copy provenance is incomplete')
        pins = {name:records[name]['sha256'] for name in ('ti.exe', 'silver.dll', 'orange.dll')}
        require(proof.get('native_pins') == pins, 'Original native binary pins differ')
        for name, digest in pins.items():
            require(sha(evidence.raw(folder/name)) == digest, 'On-disk native binary changed')
        for path, replacement in guard['replacements'].items():
            require(sha((folder/path).read_bytes()) == replacement['after']['sha256'],
                    'Native copy has an obsolete or modified fog TILE')


def readonly_health_source():
    # Retain the publisher's exact service/source/config/launcher/PID guards.
    # End before the first mutation helper; owned QA settlement legitimately
    # changes rows/counts, while fixture.preservation checks original players.
    marker = '\ndef atomic_manifest('
    require(publication.REMOTE.count(marker) == 1, 'Publisher read-only boundary changed')
    source = publication.REMOTE.split(marker, 1)[0]
    equality = (" check(state['accounts']==b['database']['accounts'] and state['table_counts']==b['database']['table_counts'],\n"
                "       'Hosted database table-count drift')\n")
    require(source.count(equality) == 1, 'Publisher database count guard changed')
    source = source.replace(equality, '')
    source += '''
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
    require(not any(isinstance(node, ast.Attribute) and node.attr in forbidden and
                    not (node.attr == 'replace' and isinstance(node.value, ast.Name)
                         and node.value.id == 'name')  # SQL identifier string escaping.
                    for node in ast.walk(tree)), 'Final health includes a mutation endpoint')
    return source


def fresh_health(guard):
    original = publication.REMOTE
    try:
        publication.REMOTE = readonly_health_source()
        return publication.remote('final-health', guard)
    finally:
        publication.REMOTE = original


def render_gallery(records, *, complete=False):
    indexed = {(r['city'], r['client'], r['side']): r for r in records}
    sections = []
    for city, (_, _, title) in CITIES.items():
        cards = []
        for client, side in [('a', s) for s in SIDES]+[('b', 'initial')]:
            record = indexed.get((city, client, side))
            label = f'Клиент{client.upper()} · {side}'
            if record:
                name = quote(record['file'])
                cards.append('<figure><a href="'+name+'"><img loading="lazy" src="'+name+
                    '" alt="'+html.escape(title+' '+label)+'"></a><figcaption>'+label+
                    '<br>'+html.escape(record['scene'])+' ·38×38<br><small>'+html.escape(
                    record.get('captured_at', record.get('time', '')))+'<br>Матч '+html.escape(
                    record['match_id'])+'<br>SHA256 '+html.escape(record['sha256'])+'</small></figcaption></figure>')
            else:
                cards.append('<figure class="pending"><p>Кадр ожидается</p><figcaption>'+label+'</figcaption></figure>')
        sections.append('<section id="'+city+'"><h2>'+title+'</h2><div class="grid">'+''.join(cards)+'</div></section>')
    status = ('Проверены20 оригинальных JPEG, их SHA и связь с четырьмя настоящими матчами.' if complete else
              f'Сбор оригинальных кадров продолжается: {len(records)}/20. Финальная проверка ещё не завершена.')
    return '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Постоянный туман окружения ·2026.10.07.2</title><style>
body{margin:0;background:#151812;color:#e9eddf;font:16px/1.5 system-ui,sans-serif}main{max-width:1500px;margin:auto;padding:28px}
h1{font-size:28px}h2{margin-top:36px}a{color:#c8ddb2}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
figure{margin:0;background:#22281d;border:1px solid #4a5740;border-radius:8px;overflow:hidden}img{display:block;width:100%;height:auto}
figcaption{padding:14px}small{display:block;overflow-wrap:anywhere;color:#b9c3ac;font-size:12px}.pending{min-height:160px;padding:20px}
.note{max-width:1050px;color:#c2cbb7}nav{display:flex;flex-wrap:wrap;gap:20px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
</style><main><h1>Неиграбельное окружение в постоянном тумане</h1><p>Версия2026.10.07.2 · RGB177/177/177 · исходная прозрачность255</p><p>'''+status+'''</p>
<p class="note">Это исходные JPEG настоящих окон клиента, полученные через @oai/sky get_window_state. Нажмите на кадр для открытия оригинала.
На каждом городе показаны четыре стороны клиентаA и дополнительный кадр клиентаB. Проверяется один вариант каждого города, поле38×38.
Скриншоты не заменяют проверки всех24 сцен и native RGB. Границы из отдельной галереи предложений пока не интегрированы.</p>
<nav><a href="#reservation">Reservation</a><a href="#denver">Denver</a><a href="#new_york">New York</a><a href="#military_zone">Military Zone</a>
<a href="captures.json">Метаданные кадров</a></nav>'''+''.join(sections)+'</main></html>\n'


def main(fixture_path):
    evidence = Evidence()
    release, guard, old_raw, new_raw = publication.load_bundle()  # Offline exact three-byte verification.
    deployment = evidence.read(OUT/'deployment.json')
    require(deployment.get('version') == VERSION and deployment.get('previous_version') == '2026.10.07.1'
            and deployment.get('patch_zip_sha256') == release['patch_zip_sha256'] and
            deployment.get('changed_records') == 552 and deployment.get('unchanged_records') == 5666,
            'Completed deployed .2 release differs from its reviewed bundle')
    require(all(deployment.get(k) is False for k in ('database_uploaded', 'database_replaced',
                'code_uploaded', 'configuration_changed', 'service_restarted')) and
            all(deployment.get(k) is True for k in ('pid_unchanged', 'all_hosted_table_rows_preserved',
                'launcher_executable_and_download_metadata_preserved', 'public_https_passed', 'postflight_passed')),
            'Client-only preservation or actual publication proof failed')
    for name in ('release-verification.json', 'guard.json', 'overlay-verification.json'):
        evidence.read(OUT/name, passed=name != 'guard.json')
    proofs = {'proofs/fog-proof.json': ROOT/'assets/arena-surroundings-v2/fog-proof.json',
              'proofs/native-fog-tint.json': OUT/'native-fog-tint.json',
              'proofs/local-tests.json': OUT/'local-tests.json',
              'proofs/native-v1.json': ROOT/'reports/arena-surroundings-implementation/native.json',
              'proofs/native-full-audit.json': ROOT/'reports/arena-surroundings-implementation/native-permanent-outside-fog-audit.json',
              'proofs/original-asset-proof.json': ROOT/'reports/arena-surroundings-implementation/asset-proof.json'}
    for packaged, path in proofs.items():
        require(sha(evidence.raw(path)) == guard['proof_files'][packaged], 'Frozen proof file changed')
    tests = evidence.read(OUT/'local-tests.json')
    native = evidence.read(OUT/'native-fog-tint.json', passed=False)
    publication.prep.validate_native_proof(native, guard['native_v1_proof_sha256'])
    coverage = evidence.read(OUT/'coverage-audit.json', passed=False)
    require(coverage.get('audit_completed') is True and
            coverage.get('coverage', {}).get('city_profiles') == 4 and
            coverage['coverage'].get('city_variants') == 12 and coverage['coverage'].get('city_outside_sets') == 24,
            'All-map coverage audit is incomplete')
    https = evidence.read(OUT/'https-release.json')
    require(https.get('client_version') == VERSION and https.get('actual_https') is True and
            https.get('manifest_sha256') == guard['new_manifest_sha256'] and
            https.get('verified_tinted_tiles') == 552, 'Actual public fog release proof differs')
    require(sha(evidence.raw(OUT/'client-release/manifest.json')) == guard['new_manifest_sha256'],
            'Local release manifest changed')
    manifest = json.loads(new_raw)
    fixture = FreshSurroundingsQA.load_private(fixture_path)
    require(fixture.host == '185.184.42.88', 'Only the established hosted QA fixture is supported')
    matches = validate_matches(evidence, fixture, manifest)
    validate_copies(evidence, manifest, guard)
    captures = capture_records(evidence.read(SHOTS/'captures.json', passed=False))
    validate_capture_set(captures)
    for record in captures:
        path, _ = validate_capture(record, SHOTS, matches[record['city']])
        evidence.raw(path)
    # No player mutation can occur in either of these final remote operations.
    actual = publication.get(publication.ORIGIN+'manifest.json')
    require(actual == new_raw, 'Fresh public HTTPS manifest changed')
    health = fresh_health(guard)
    preservation = fixture.preservation()
    require(preservation.get('integrity') == 'ok' and
            preservation.get('existing_account_rows_preserved', {}).get('accounts', 0) > 0,
            'Fresh original-account preservation failed')
    gallery = render_gallery(captures, complete=True)
    (SHOTS/'review.html').write_text(gallery, encoding='utf-8')
    gallery_proof = dict(schema='arena-surroundings-fog-original-captures/v1', passed=True,
        version=VERSION, originals=20, a_side_captures=16, b_initial_captures=4,
        source=SOURCE, captures_sha256=sha((SHOTS/'captures.json').read_bytes()),
        review_html_sha256=sha((SHOTS/'review.html').read_bytes()),
        checks=dict(jpeg_bytes_and_dimensions=True, four_cities_four_a_sides=True,
                    two_actual_authenticated_native_clients_per_city=True,
                    owned_pid_match=True, staged_scene_and_variant=True, all_matches_cleaned_up=True),
        visual_review_automatically_claimed=False,
        limitation='Automated provenance/structure checks cannot assess pixel aesthetics or independently prove a capture source.')
    publication.save(SHOTS/'gallery-verification.json', gallery_proof)
    evidence.raw(SHOTS/'review.html');evidence.raw(SHOTS/'gallery-verification.json')
    report = dict(schema='arena-surroundings-fog-completion/v1', passed=True,
        verified_at_utc=datetime.now(timezone.utc).isoformat(), version=VERSION,
        manifest_sha256=guard['new_manifest_sha256'], tinted_tiles=552, scenes=24,
        city_variants=12, native_tcolor_hex='00b1b1b1', native_vertex_argb='ffb1b1b1', alpha=255,
        changed_raw_offsets=[52, 53, 54], local_tests=tests['tests_run'],
        graphical_matches=4, actual_native_clients_per_match=2, bots=0,
        screenshots=20, four_side_screenshots=16, second_client_screenshots=4,
        graphical_scope='Four cities, one random variant each, mode0,38x38;16 A-side views plus4 B initial views.',
        map_family_scope='All24 existing city scenes permanently tinted; other combat families retain original opaque exterior. No new quest/mine/range surroundings.',
        border_proposals_integrated=False, all_native_binary_bytes_unchanged=True,
        remote_backup=deployment['backup'], database_uploaded=False, code_uploaded=False,
        service_restarted=False, health=health, preservation=preservation,
        evidence_sha256=evidence.hashes,
        limitations=['57x57 and all12 variants have asset/native proof; new GUI captures sample four38x38 variants.',
                     'The native RGB multiplier is independent of gameplay visibility. It matches primary fog center intensity rather than reproducing soft fog edges.'])
    publication.save(OUT/'completion.json', report)
    print(json.dumps(dict(passed=True, version=VERSION, screenshots=20, graphical_matches=4,
                         service=health['service'], established_connections=health['established_connections'],
                         original_accounts_preserved=True)))
    return report


def self_test():
    from PIL import Image
    checks = 0
    with tempfile.TemporaryDirectory(prefix='tio-fog-final-offline-') as local:
        folder = Path(local)
        buffer = io.BytesIO();Image.new('RGB', (1026, 795), '#252b20').save(buffer, format='JPEG')
        raw = buffer.getvalue();(folder/'test.jpg').write_bytes(raw)
        record = dict(file='test.jpg', city='denver', side='NW', client='a', version=VERSION,
            match_id='offline', scene='as_de_1_38', variant='D1', map_size=38, source=SOURCE,
            sha256=sha(raw), width=1026, height=795, captured_at='2026-10-07T00:00:00Z')
        validate_capture(record, folder);checks += 1
        bad_values = {'file':'../test.jpg', 'city':'reservation', 'version':'2026.10.07.1',
                      'source':'imagegen', 'client':'b', 'map_size':57, 'sha256':'0'*64,
                      'width':1024, 'variant':'D2', 'captured_at':'2026-10-07T00:00:00'}
        for key, value in bad_values.items():
            invalid = dict(record, **{key:value})
            try:validate_capture(invalid, folder)
            except (RuntimeError, ValueError):checks += 1
            else:raise AssertionError('Bad capture accepted: '+key)
        records = [dict(city=city,client=client,side=side,file=f'{city}-{client}-{side}.jpg',sha256=sha(f'{city}-{client}-{side}'.encode()))
                   for city in CITIES for client,side in [('a',s) for s in SIDES]+[('b','initial')]]
        validate_capture_set(records);checks += 1
        for invalid in (records[:-1], records+[records[0]], [records[0]]*20):
            try:validate_capture_set(invalid)
            except RuntimeError:checks += 1
            else:raise AssertionError('Incomplete/duplicate capture set accepted')
        start = dict(graphical_accounts=['owna','ownb'], disconnected_at_unix=1)
        clients = []
        for pid, account in ((10,'owna'), (20,'ownb')):
            client = {k:True for k in ('connected','authenticated','worldStartSent','charactersLoaded')}
            client.update({k:0 for k in ('authChallengeStatus','loginStatus','serverLoginStatus',
                            'gameAuth1Status','gameAuth2Status','characterSelectStatus')})
            client.update(fault=None, runtime_errors=[], selectedCharacter=dict(name=account),
                selectedServer=dict(host='185.184.42.88',port=28513), pid=pid,
                camera=dict(pid=pid,read_only=True,available=True,field_width=38,field_height=38,
                            updates=1,runtime_errors=[]))
            clients.append(client)
        status = dict(event='graphical_status',observed_at_unix=2,clients=clients)
        cleanup = dict(native_pids=[10,20])
        validate_status(status,start,cleanup);checks += 1
        for field, value in (('connected',False),('gameAuth2Status',1),('runtime_errors',['fault']),('pid',30)):
            invalid = copy.deepcopy(status);invalid['clients'][1][field] = value
            try:validate_status(invalid,start,cleanup)
            except RuntimeError:checks += 1
            else:raise AssertionError('Invalid native status accepted: '+field)
        source = readonly_health_source();compile(source, '<readonly-fog-final-health>', 'exec');checks += 1
        require('Hosted database table-count drift' not in source and 'def atomic_manifest' not in source
                and 'def main' in source and "mode=ro" in source, 'Read-only health source differs');checks += 1
        original = publication.REMOTE
        try:
            publication.REMOTE = original.replace('Hosted database table-count drift', 'changed guard')
            try:readonly_health_source()
            except RuntimeError:checks += 1
            else:raise AssertionError('Changed remote boundary accepted')
        finally:publication.REMOTE = original
        gallery = render_gallery([record])
        require('<img loading="lazy" src="test.jpg"' in gallery and '1/20' in gallery and
                'Финальная проверка ещё не завершена' in gallery, 'Partial gallery falsely claims completion');checks += 1
    print(json.dumps(dict(offline_self_test='passed', checks=checks, server_contacted=False,
                         clients_started=0, accounts_created=0)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--gallery-only', action='store_true', help='Render partial local original-JPEG gallery; no hosted checks')
    args = parser.parse_args()
    require(not (args.self_test and args.gallery_only), 'Choose one offline action')
    if args.self_test:
        self_test()
    elif args.gallery_only:
        records = capture_records(json.loads((SHOTS/'captures.json').read_bytes()))
        for record in records:validate_capture(record, SHOTS)
        SHOTS.mkdir(parents=True, exist_ok=True)
        (SHOTS/'review.html').write_text(render_gallery(records), encoding='utf-8')
        print(json.dumps(dict(local_gallery=True, captures=len(records), server_contacted=False, final_verified=False)))
    else:
        require(args.fixture is not None, '--fixture is required for final verification')
        main(args.fixture)
