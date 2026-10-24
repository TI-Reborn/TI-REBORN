"""Verify both public manifests and every new personal-GUI blob over trusted TLS."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,time
from urllib.request import Request,urlopen
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/personal-gui-all-20261020'
proof=json.loads((OUT/'asset-proof.json').read_text())
candidate=json.loads((OUT/'release/client-release/manifest.json').read_bytes())

def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'TIO-launcher-self-update-verification',
                                             'Cache-Control':'no-cache'}),timeout=35) as response:
                assert response.status==200
                return response.read()
        except Exception:
            if attempt==2:raise
            time.sleep(.5)

manifests=[]
for origin in ('https://ti-reborn.com','https://185.184.42.88'):
    raw=fetch(origin+'/updates/manifest.json');manifest=json.loads(raw)
    assert manifest['version']==candidate['version'] and manifest['files']==candidate['files']
    manifests.append({'origin':origin,'sha256':hashlib.sha256(raw).hexdigest(),'version':manifest['version']})

def verify(row):
    raw=fetch('https://ti-reborn.com/updates/blobs/'+row['sha256'])
    assert len(raw)==row['size'] and hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
    return {k:row[k] for k in ('path','sha256','size')}

with ThreadPoolExecutor(max_workers=6) as executor:rows=list(executor.map(verify,proof['files']))
(OUT/'public-assets-verified.json').write_text(json.dumps({'passed':True,'trusted_https':True,
    'manifests':manifests,'verified_blobs':len(rows),'files':rows},indent=2)+'\n',encoding='utf-8')
print(json.dumps({'passed':True,'public_origins':2,'verified_blobs':len(rows)}))
