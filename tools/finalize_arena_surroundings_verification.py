"""Bind completed release evidence to a fresh read-only hosted health check."""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA

OUT = ROOT / 'reports/arena-surroundings-implementation'
HEALTH = r'''
import hashlib,json,sqlite3,subprocess,sys
from pathlib import Path
payload=json.load(sys.stdin)
connections=subprocess.check_output(['ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'],text=True).splitlines()
manifest=Path('/var/www/tio-client/updates/manifest.json').read_bytes()
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 state=dict(integrity=db.execute('PRAGMA integrity_check').fetchone()[0],
  accounts=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
  checkpoints=db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],
  checkpoint_members=db.execute('SELECT COUNT(*) FROM battle_checkpoint_members').fetchone()[0],
  pending=db.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0])
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 established_connections=len(connections),database=state,client_version=json.loads(manifest)['version'],
 manifest_sha256=hashlib.sha256(manifest).hexdigest(),
 source_sha256={name:hashlib.sha256((Path('/opt/tio-emulator')/name).read_bytes()).hexdigest() for name in payload['files']})))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--network-report', type=Path, required=True)
    args = parser.parse_args()
    evidence = {}

    def read(path, passed=True):
        path = path.resolve()
        assert path.is_relative_to(OUT.resolve())
        raw = path.read_bytes()
        value = json.loads(raw)
        if passed:
            assert value['passed'] is True, str(path)
        evidence[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
        return value

    deployment = read(OUT/'deploy/deployment.json', False)
    network = read(args.network_report)
    assert network['completed'] and len(network['matches']) == 12
    assert {(m['profile'], m['mode']) for m in network['matches']} == {
        (city, mode) for city in ('denver', 'new_york', 'military_zone', 'reservation')
        for mode in (0, 1, 4)}
    assert all(m['bots'] == 0 and m['reconnect_stable'] and m['outside_move']['ap_preserved'] >= 0
               for m in network['matches'])
    local = read(OUT/'deploy/local-tests.json')
    read(OUT/'deploy/https-release.json')
    assets = read(OUT/'final-byte-checks.json')
    read(OUT/'screenshots/gallery-verification.json')
    read(OUT/'client-qa/native-57-verification.json')
    fixture = FreshSurroundingsQA.load_private(args.fixture)
    preservation = fixture.preservation()
    health = fixture.remote(HEALTH, dict(files=list(deployment['server_files'])))
    assert health['service'] == 'active' and health['database']['integrity'] == 'ok'
    assert health['established_connections'] == 0
    assert all(health['database'][key] == 0 for key in ('checkpoints', 'checkpoint_members', 'pending'))
    assert health['client_version'] == deployment['client_version'] == '2026.10.07.1'
    assert health['manifest_sha256'] == deployment['client_manifest_sha256']
    assert health['source_sha256'] == deployment['server_files']
    report = dict(passed=True, verified_at_utc=datetime.now(timezone.utc).isoformat(),
        client_version=health['client_version'], decorative_variants=12, native_scenes=assets['scene_count'],
        local_automated_checks=local['tests_run'], hosted_candidate_checks=deployment['candidate_tests'],
        hosted_protocol_matches=12, participants_per_match=[2, 4, 8], bots=0,
        original_graphical_battle_screenshots=16, graphical_field_sizes=[38, 57],
        graphical_scope='Four randomly selected city variants at38; Military variant1 at57. Other scene coverage is automated.',
        remote_backup=deployment['backup'], database_uploaded=False, health=health,
        existing_account_preservation=preservation, evidence_sha256=evidence)
    (OUT/'completion.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(json.dumps(dict(passed=True, version=report['client_version'], network_matches=12,
        screenshots=16, service=health['service'], existing_account_tables=len(preservation['existing_account_rows_preserved']),
        output=str(OUT/'completion.json'))))


if __name__ == '__main__':
    main()
