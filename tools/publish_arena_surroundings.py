"""Explicitly upload the prepared release, verify a hosted candidate and deploy.

Default invocation is a dry plan. --execute is required for remote mutations.
"""
from arena_surroundings_deployment import *
import argparse
from concurrent.futures import ThreadPoolExecutor
import urllib.request


def remote_script(name, report_name):
    result = subprocess.run(SSH + ['python3 /root/' + name], capture_output=True,
                            text=True, encoding='utf-8', check=False)
    (OUT / (report_name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Hosted ' + report_name + ' failed; see saved log')
    data = json.loads(result.stdout.strip().splitlines()[-1])
    write_json(OUT / (report_name + '.json'), data)
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Upload, run isolated candidate checks and perform guarded deployment')
    args = parser.parse_args(argv)
    verification = json.loads((OUT / 'release-verification.json').read_text(encoding='utf-8'))
    if verification.get('passed') is not True or verification['version'] != NEW_VERSION:
        raise RuntimeError('A completed prepared release is required')
    if sha((OUT / 'patch.tar.gz').read_bytes()) != verification['patch_sha256'] or \
       sha((OUT / 'tests.tar.gz').read_bytes()) != verification['tests_archive_sha256']:
        raise RuntimeError('Prepared archive hashes changed')
    uploads = (
        (OUT / 'patch.tar.gz', 'tio-arena-surroundings-patch.tar.gz'),
        (OUT / 'tests.tar.gz', 'tio-arena-surroundings-tests.tar.gz'),
        (ROOT / 'tools/verify_arena_surroundings_candidate_remote.py', 'verify_arena_surroundings_candidate_remote.py'),
        (ROOT / 'tools/deploy_arena_surroundings_remote.py', 'deploy_arena_surroundings_remote.py'),
    )
    plan = dict(execute=args.execute, host=HOST, version=NEW_VERSION,
                uploads=[dict(local=str(path), remote='/root/' + name, sha256=sha(path.read_bytes())) for path, name in uploads],
                candidate_patterns=TEST_PATTERNS, database_uploaded=False,
                new_client_files=verification['new_client_files'])
    write_json(OUT / 'publication-plan.json', plan)
    if not args.execute:
        print(json.dumps(plan))
        return
    for path, name in uploads:
        subprocess.run(SCP + [str(path), 'root@' + HOST + ':/root/' + name], check=True)
    actual_uploads = remote_read(r'''
from pathlib import Path
import hashlib,json,sys
names=json.load(sys.stdin)
print(json.dumps({name:hashlib.sha256((Path('/root')/name).read_bytes()).hexdigest() for name in names}))
''', [name for _, name in uploads])
    expected_uploads = {name: sha(path.read_bytes()) for path, name in uploads}
    if actual_uploads != expected_uploads:
        raise RuntimeError('Uploaded archive/tool hash mismatch')
    candidate = remote_script('verify_arena_surroundings_candidate_remote.py', 'hosted-candidate')
    if candidate.get('passed') is not True:
        raise RuntimeError('Hosted candidate did not pass')
    deployment = remote_script('deploy_arena_surroundings_remote.py', 'deployment')
    with urllib.request.urlopen(URL + 'manifest.json', timeout=45) as response:
        manifest = response.read()
    if manifest != (OUT / 'client-release/manifest.json').read_bytes():
        raise RuntimeError('Published HTTPS manifest differs from the prepared release')
    old = json.loads((OUT / 'previous-client-manifest.json').read_bytes())
    before = {record['path']: record for record in old['files']}
    after = {record['path']: record for record in json.loads(manifest)['files']}
    if not all(after.get(name) == record for name, record in before.items()):
        raise RuntimeError('An old record changed in the published manifest')
    records = [record for name, record in after.items() if name not in before]
    def check(record):
        with urllib.request.urlopen(URL + 'blobs/' + record['sha256'], timeout=45) as response:
            raw = response.read()
        if len(raw) != record['size'] or sha(raw) != record['sha256']:
            raise RuntimeError('Published HTTPS blob differs: ' + record['path'])
        return dict(path=record['path'], sha256=record['sha256'], size=len(raw))
    with ThreadPoolExecutor(max_workers=6) as workers:
        files = list(workers.map(check, records))
    https = dict(passed=True, version=NEW_VERSION, manifest_sha256=sha(manifest),
                 verified_new_files=len(files), previous_client_records_preserved=len(before), files=files)
    write_json(OUT / 'https-release.json', https)
    health = remote_read(r'''
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys
names=json.load(sys.stdin)
listeners=subprocess.check_output(['ss','-Hltn','( sport = :28512 or sport = :28513 )'],text=True)
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as database:
 result=dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
  integrity=database.execute('PRAGMA integrity_check').fetchone()[0],accounts=database.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
  checkpoints=database.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=database.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],
  gameplay_listeners=len(listeners.strip().splitlines()),
  files={name:hashlib.sha256((Path('/opt/tio-emulator')/name).read_bytes()).hexdigest() for name in names})
print(json.dumps(result))
''', SERVER_FILES)
    if health['service'] != 'active' or health['integrity'] != 'ok' or health['gameplay_listeners'] != 2:
        raise RuntimeError('Hosted post-deployment health did not pass')
    guard = json.loads((OUT / 'guard.json').read_text(encoding='utf-8'))
    if health['files'] != {name: entry['after'] for name, entry in guard['server_files'].items()}:
        raise RuntimeError('Hosted source hashes differ after deployment')
    write_json(OUT / 'hosted-health.json', health)
    print(json.dumps(dict(deployment=deployment, https_verified_new_files=len(files), health=health,
                          graphical_game_client_validation=False)))


if __name__ == '__main__':
    main()
