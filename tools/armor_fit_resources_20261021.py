"""Fetch exact published animation dependencies without touching hosted fixtures."""
import concurrent.futures,hashlib,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
OUT=ROOT/'reports/armor-fit-20261021';manifest=json.loads((OUT/'manifest-before.json').read_text(encoding='utf-8'))
rows={r['path']:r for r in manifest['files']}
clips=['human_gun_idle','human_gun_run','woman_gun_idle','woman_run','human_run','dog_idle','dog_run','freakminer_hammer_idle','freakminer_hammer_run']
names=['base/models/anim/'+n+'.adjx' for n in clips if 'base/models/anim/'+n+'.adjx' in rows]
def fetch(name):
 r=rows[name];p=OUT/'source'/name
 raw=p.read_bytes() if p.exists() else urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+r['sha256'],timeout=40).read()
 assert len(raw)==r['size'] and hashlib.sha256(raw).hexdigest()==r['sha256']
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return name
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:print(json.dumps(list(pool.map(fetch,names))))
