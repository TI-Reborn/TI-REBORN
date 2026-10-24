"""Read actual hosted resource roots and traverse published scene/TILE references."""
import concurrent.futures, hashlib, json, re, sys, urllib.request, zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
OUT=ROOT/'reports/remaining-textures-20261021'
ASSET=ROOT/'assets/wasteland-materials-v1'
ORIGINAL=ROOT/'work/remaining-textures-20261021/original'
sha=lambda b:hashlib.sha256(b).hexdigest()
code="""
from pathlib import Path
import json,sys
p=Path('/opt/tio-emulator/config')
print(json.dumps({x.name:x.read_text() for x in p.glob('*.json')}))
"""
configs=remote(code,{})
(OUT/'hosted-config-resource-roots.json').write_text(json.dumps(configs,ensure_ascii=False),encoding='utf-8')
m=json.loads((OUT/'manifest-before.json').read_bytes());rows={r['path']:r for r in m['files']}
byname={}
for n in rows:byname.setdefault(Path(n).name.lower(),[]).append(n)

def fetch(name):
    r=rows[name]
    for f in (ORIGINAL/name,ROOT/'work/launcher-required-20261020/native-client'/name,OUT/'reference-source'/name):
        if f.is_file():
            b=f.read_bytes()
            if sha(b)==r['sha256']:return b
    b=urllib.request.urlopen('https://185.184.42.88/updates/blobs/'+r['sha256'],timeout=30).read();assert sha(b)==r['sha256']
    p=OUT/'reference-source'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);return b

text='\n'.join(configs.values()).lower()
roots={n for n in rows if n.endswith('.s') and ('"'+n.removeprefix('base/maps/').lower()+'"' in text or '"'+Path(n).name.lower()+'"' in text)}
roots|={'base/ground.xml','base/objects.xml','base/shared config/items.xml','base/mobs.udf','base/customisation.xml'}&rows.keys()
pending=set(roots);visited=set();edges={}
while pending:
    current=sorted(pending-visited);pending.clear()
    if not current:break
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:data=list(pool.map(fetch,current))
    for name,raw in zip(current,data):
        visited.add(name)
        if raw[:4]==b'\x03ZIP':raw=zlib.decompress(raw[16:])
        value=raw.lower();deps=set()
        for base,candidates in byname.items():
            if not base.endswith(('.s','.t','.png','.tga','.jpg','.bmp')):continue
            if base.encode('ascii',errors='ignore') not in value:continue
            # Native resource lookup uses basenames. Retain all candidates if
            # a name is duplicated; do not silently choose an arbitrary path.
            deps.update(candidates)
        edges[name]=sorted(deps)
        pending.update(n for n in deps if n.endswith(('.s','.t')) and n not in visited)
referenced=set(roots)|{x for values in edges.values() for x in values}
tasks=json.loads((ASSET/'tasks.json').read_text(encoding='utf-8'))
active=[t for t in tasks if t['path'] in referenced]
(OUT/'active-materials.json').write_text(json.dumps(active,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'reference-graph.json').write_text(json.dumps(dict(roots=sorted(roots),visited=sorted(visited),edges=edges,referenced=sorted(referenced)),indent=2))
from collections import Counter
print(json.dumps(dict(scene_roots=len(roots),traversed=len(visited),active_original_materials=len(active),groups=Counter(t['path'].split('/')[1] for t in active))))
