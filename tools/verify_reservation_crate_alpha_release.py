"""Read-only verification of the public transparency patch and hosted health."""
from reservation_texture_assets import ROOT, OUT, sha, fetch, remote
from build_visual_asset_catalog import decode
from concurrent.futures import ThreadPoolExecutor
import json
import urllib.request

FIX = ROOT / 'reports/reservation-crate-alpha'


def main():
    endpoint = 'https://185.184.42.88/updates/'
    raw = urllib.request.urlopen(endpoint + 'manifest.json', timeout=30).read()
    assert raw == (FIX / 'client-release/manifest.json').read_bytes()
    manifest = json.loads(raw)
    assert manifest['version'] == '2026.10.06.4'
    previous = {r['path']: r for r in json.loads((FIX / 'previous-manifest.json').read_bytes())['files']}
    records = {r['path']: r for r in manifest['files']}
    proof = json.loads((FIX / 'asset-verification.json').read_text())
    targets = {r['target']: r for r in proof['files']}
    assert set(previous) == set(records)
    assert {n for n in records if records[n] != previous[n]} == set(targets)
    inventory = json.loads((OUT / 'inventory.json').read_text())

    def check(name):
        record = records[name]
        data = urllib.request.urlopen(endpoint + 'blobs/' + record['sha256'], timeout=30).read()
        assert len(data) == record['size'] and sha(data) == record['sha256']
        assert data == (FIX / 'client' / name).read_bytes()
        original, _ = decode(fetch(inventory['textures'][targets[name]['source']]).read_bytes())
        installed, mode = decode(data)
        before = urllib.request.urlopen(endpoint + 'blobs/' + previous[name]['sha256'], timeout=30).read()
        before, _ = decode(before)
        assert installed.size == before.size == original.size
        assert installed.convert('RGB').tobytes() == before.convert('RGB').tobytes()
        assert installed.getchannel('A').tobytes() == original.getchannel('A').tobytes()
        return dict(path=name, sha256=sha(data), codec=mode, original_alpha_exact=True, generated_rgb_unchanged=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        files = list(pool.map(check, sorted(targets)))
    report = dict(passed=True, client_version=manifest['version'], verified_https_blobs=files,
                  other_manifest_records_unchanged=True, manifest_sha=sha(raw), graphical_game_client=False)
    (FIX / 'https-release.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))
    health = remote("""import pathlib,sqlite3,hashlib,json,subprocess
r=pathlib.Path('/opt/tio-emulator')
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
 checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],
 listening=subprocess.check_output(['ss','-Hln','sport = :28512 or sport = :28513'],text=True),
 code={n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in ('tio/map_generation.py','config/reservation_visuals.json')})))""")
    assert health['service'] == 'active' and health['integrity'] == 'ok'
    assert health['listening'] and health['code'] == json.loads((FIX / 'inspection.json').read_text())['code']
    (FIX / 'hosted-health.json').write_text(json.dumps(health, indent=2) + '\n')
    print(json.dumps(health))


if __name__ == '__main__':
    main()
