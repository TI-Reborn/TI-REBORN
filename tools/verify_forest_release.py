"""Read-only HTTPS release and hosted service/database checks."""
from forest_biomes_assets import *
from concurrent.futures import ThreadPoolExecutor

def main():
    with urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30) as response:raw=response.read()
    expected=(OUT/'client-release/manifest.json').read_bytes();assert raw==expected
    manifest=json.loads(raw);names={p.relative_to(OUT/'client').as_posix() for p in (OUT/'client').rglob('*') if p.is_file()}
    records=[r for r in manifest['files'] if r['path'] in names]
    assert len(records)==80 and manifest['version']=='2026.10.06.2'
    before={r['path']:r for r in json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']}
    assert all(r==before[r['path']] for r in manifest['files'] if r['path'] not in names)
    def check(record):
        with urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+record['sha256'],timeout=30) as response:data=response.read()
        assert len(data)==record['size'] and sha(data)==record['sha256'],record['path']
        return record['path']
    with ThreadPoolExecutor(max_workers=4) as pool:verified=list(pool.map(check,records))
    report=dict(passed=True,client_version=manifest['version'],verified_https_blobs=len(verified),other_published_records_unchanged=True,manifest_sha=sha(raw))
    (OUT/'https-release.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    code="""import json,sqlite3,subprocess
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),
 integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],
 checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],
 listening=subprocess.check_output(['ss','-Hln','sport = :28512 or sport = :28513'],text=True))))"""
    p=subprocess.run(SSH+['python3 -c '+shlex.quote(code)],capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stderr)
    health=json.loads(p.stdout);assert health['service']=='active' and health['integrity']=='ok' and health['pending']==0
    (OUT/'hosted-health.json').write_text(json.dumps(health,indent=2)+'\n');print(json.dumps(health))

if __name__=='__main__':main()
