"""Freeze read-only rating adapters on pinned public gameplay/city sources."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings/portal'
BASE=ROOT/'reports/gameplay-followup/stage1-interfaces/public-regression'
LAYERS=(ROOT/'reports/gameplay-completion/stage9-interfaces-revision2',
        ROOT/'reports/gameplay-completion/stage9-city',
        ROOT/'reports/gameplay-followup/stage4-ratings/final')
NET=('server/ratings_public.py','server/city_http.py','server/bank_gateway.py')
WEB=('src/lib/ratings-contract.ts','src/lib/ratings-gateway.ts','src/lib/ratings-api.ts',
     'src/app/api/ratings/status/route.ts','src/components/ratings-board.tsx','src/app/[locale]/ratings/page.tsx')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('name',choices=('validation1','validation2','final'))
    args=parser.parse_args();target=FOLDER/args.name
    if target.exists():raise ValueError('Preserve frozen ratings portal evidence')
    base=json.loads((BASE/'snapshot.json').read_text(encoding='utf-8'))['source_sha256']
    sources={};published={}
    for layer in LAYERS:
        filename='delivery-manifest.json' if layer.name=='final' else 'candidate-manifest.json'
        manifest=json.loads((layer/filename).read_text(encoding='utf-8'))
        for name,entry in manifest['files'].items():
            raw=(layer/entry['source']).read_bytes()
            if sha(raw)!=entry['sha256']:raise ValueError('Frozen public source changed: '+name)
            sources[name]=raw
            if layer.name=='stage9-city':published[name]=sha(raw)
    target.mkdir();delivery={}
    for name in NET:
        source=ROOT/name if name=='server/ratings_public.py' else FOLDER/'runtime'/name
        raw=source.read_bytes();compile(raw,name,'exec');sources[name]=raw
        delivery[name]=dict(source='runtime/'+name,before=published.get(name),sha256=sha(raw))
    entries={}
    for name,raw in sources.items():
        destination=target/'runtime'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        entries[name]=dict(source='runtime/'+name,before=base.get(name),sha256=sha(raw))
    web={}
    for name in WEB:
        raw=(ROOT/'web'/name).read_bytes();destination=target/'web'/name
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        web['web/'+name]=dict(source='web/'+name,before=None,sha256=sha(raw))
    for name in ('test_ratings_public.py',):
        destination=target/'tests'/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/'tests'/name,destination)
    destination=target/'web/tests/ratings.test.ts';destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(ROOT/'web/tests/ratings.test.ts',destination)
    metadata=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),
        source='Actual hosted public .5 snapshot plus published stage9 revision2, city and frozen stage4 ratings',
        hosted_changes=False,shared_existing_runtime_modified=False)
    for filename,files in (('candidate-manifest.json',entries),('delivery-manifest.json',delivery),('web-manifest.json',web)):
        (target/filename).write_text(json.dumps(dict(**metadata,files=files),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(target),overlay_files=len(entries),net_files=len(delivery),web_files=len(web))))


if __name__=='__main__':main()
