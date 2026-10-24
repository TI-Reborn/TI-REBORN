"""Read published immutable client blobs and prepare a local four-byte fix.

Never publishes, restarts services, changes installed client files or player data.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from deploy.client_repair_warehouse import patch,review
REPORT=ROOT/'reports/repair-warehouse-20261017'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']


def main():
    baseline=REPORT/'client/baseline';candidate=REPORT/'client/candidate'
    baseline.mkdir(parents=True,exist_ok=True);candidate.mkdir(exist_ok=True)
    raw=subprocess.run(SSH+['cat /var/www/tio-client/updates/manifest.json'],capture_output=True,check=True,timeout=30).stdout
    inspection=json.loads((REPORT/'inspection.json').read_text())
    assert hashlib.sha256(raw).hexdigest()==inspection['client_manifest_sha256'],'Client publication changed; reinspect first'
    (baseline/'manifest.json').write_bytes(raw)
    manifest=json.loads(raw);row=next(r for r in manifest['files'] if r['path']=='silver.dll')
    source=subprocess.run(SSH+['cat /var/www/tio-client/updates/blobs/'+row['sha256']],capture_output=True,check=True,timeout=30).stdout
    assert len(source)==row['size'] and hashlib.sha256(source).hexdigest()==row['sha256']
    (baseline/'silver.dll').write_bytes(source)
    result=patch(source);(candidate/'silver.dll').write_bytes(result)
    audit=review(source,result)
    audit.update(client_version=manifest['version'],baseline_manifest_sha256=inspection['client_manifest_sha256'],
                 server_changes=False,player_data_changes=False,published=False,installed=False)
    (REPORT/'client/prepared.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps(audit))


if __name__=='__main__':main()
