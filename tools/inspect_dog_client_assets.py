"""Compare published dog resources with the installed client; read only."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/encounter-movement-20261017/client'
SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']


def main():
    OUT.mkdir(exist_ok=True)
    raw=subprocess.run(SSH+['cat /var/www/tio-client/updates/manifest.json'],capture_output=True,check=True).stdout
    (OUT/'previous-manifest.json').write_bytes(raw)
    manifest=json.loads(raw)
    selected=[r for r in manifest['files'] if 'dog' in r['path'].lower() or r['path'] in ('base/mobs.udf','base/animation.xml','base/shared config/items.xml')]
    result=[]
    for row in selected:
        local=Path.home()/'AppData/Local/TIO-Online'/row['path']
        original=Path('C:/Program Files (x86)/TIOnline')/row['path']
        def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        result.append(dict(path=row['path'],published=row['sha256'],installed=sha(local),original=sha(original)))
        if row['path'] in ('base/mobs.udf','base/animation.xml','base/shared config/items.xml'):
            blob=subprocess.run(SSH+['cat /var/www/tio-client/updates/blobs/'+row['sha256']],capture_output=True,check=True).stdout
            assert hashlib.sha256(blob).hexdigest()==row['sha256']
            (OUT/Path(row['path']).name).write_bytes(blob)
    report=dict(version=manifest['version'],manifest_sha256=hashlib.sha256(raw).hexdigest(),files=result)
    (OUT/'inspection.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(version=manifest['version'],files=len(result),installed_mismatches=[r['path'] for r in result if r['installed']!=r['published']],changed_from_stock=[r['path'] for r in result if r['published']!=r['original']])))


if __name__=='__main__':main()
