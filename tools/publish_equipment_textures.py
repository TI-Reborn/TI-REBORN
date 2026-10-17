"""Publish the verified asset-only release and verify every public HTTPS blob."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json,subprocess,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.equipment_texture_assets import OUT,SSH,URL,remote,sha


def main():
    proof=json.loads((OUT/'asset-verification.json').read_text())
    release=json.loads((OUT/'release-verification.json').read_text())
    assert proof['passed'] and release['changed_files']==145
    scp=['scp','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10']
    for local,name in ((OUT/'patch.tar.gz','tio-equipment-textures-patch.tar.gz'),
                       (ROOT/'tools/deploy_equipment_textures_remote.py','deploy_equipment_textures_remote.py')):
        subprocess.run(scp+[str(local),'root@185.184.42.88:/root/'+name],check=True)
    result=subprocess.run(SSH+['python3 /root/deploy_equipment_textures_remote.py'],capture_output=True,text=True,encoding='utf-8')
    (OUT/'deployment.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    deployment=json.loads(result.stdout.strip().splitlines()[-1])
    (OUT/'deployment.json').write_text(json.dumps(deployment,indent=2)+'\n')
    with urllib.request.urlopen(URL+'manifest.json',timeout=45) as response:manifest=response.read()
    assert manifest==(OUT/'client-release/manifest.json').read_bytes()
    before={r['path']:r for r in json.loads((OUT/'previous-client-manifest.json').read_bytes())['files']}
    changed=[r for r in json.loads(manifest)['files'] if before[r['path']]!=r]
    def check(record):
        with urllib.request.urlopen(URL+'blobs/'+record['sha256'],timeout=45) as response:raw=response.read()
        assert len(raw)==record['size'] and sha(raw)==record['sha256'],record['path']
        return dict(path=record['path'],sha256=sha(raw),size=len(raw))
    with ThreadPoolExecutor(max_workers=8) as pool:files=list(pool.map(check,changed))
    https=dict(passed=True,version=release['version'],manifest_sha256=sha(manifest),verified_files=len(files),files=files)
    (OUT/'https-release.json').write_text(json.dumps(https,indent=2)+'\n')
    health=remote("""import pathlib,json,sqlite3,subprocess
d=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
print(json.dumps(dict(service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip(),integrity=d.execute('PRAGMA integrity_check').fetchone()[0],accounts=d.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],checkpoints=d.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],pending=d.execute('SELECT COUNT(*) FROM battle_settlement_jobs').fetchone()[0],listeners=subprocess.check_output(['ss','-ltnp'],text=True))))""")
    assert health['service']=='active' and health['integrity']=='ok'
    (OUT/'hosted-health.json').write_text(json.dumps(health,indent=2)+'\n')
    print(json.dumps(dict(deployment=deployment,https_verified_files=len(files),health=health)))


if __name__=='__main__':main()
