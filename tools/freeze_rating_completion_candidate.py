"""Pin a reviewable public rating overlay; retain earlier proof artifacts."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/gameplay-followup/stage4-ratings'
BASE=ROOT/'reports/gameplay-followup/stage1-interfaces/public-regression'
STAGE9=ROOT/'reports/gameplay-completion/stage9-interfaces-revision2'
NAMES=('tio/rating_completion.py','config/rating_completion.json','server/team_ranked.py',
       'server/ranked_arena.py','server/team_arena.py','tio/battle_rewards.py','tio/team_scene.py','tools/survival_scene.py')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('name',choices=('validation1','validation2','validation3','validation4','final'))
    args=parser.parse_args();target=FOLDER/args.name
    if target.exists():raise ValueError('Preserve previous frozen rating evidence')
    base=json.loads((BASE/'snapshot.json').read_text(encoding='utf-8'))['source_sha256']
    published=json.loads((STAGE9/'candidate-manifest.json').read_text(encoding='utf-8'))['files']
    target.mkdir();files={};delivery={}
    for name,entry in published.items():
        source=STAGE9/entry['source'];raw=source.read_bytes()
        if sha(raw)!=entry['sha256']:raise ValueError('Published stage9 source changed')
        destination=target/'runtime'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        files[name]=dict(source='runtime/'+name,before=base.get(name),sha256=sha(raw))
    for name in NAMES:
        raw=(FOLDER/'runtime'/name).read_bytes()
        if name.endswith('.py'):compile(raw,name,'exec')
        elif name.endswith('.json'):json.loads(raw)
        prior=published[name]['sha256'] if name in published else base.get(name)
        if sha(raw)==prior:raise ValueError('Unchanged scoped rating file: '+name)
        destination=target/'runtime'/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
        files[name]=dict(source='runtime/'+name,before=base.get(name),sha256=sha(raw))
        delivery[name]=dict(source='runtime/'+name,before=prior,sha256=sha(raw))
    for file,entries in (('candidate-manifest.json',files),('delivery-manifest.json',delivery)):
        (target/file).write_text(json.dumps(dict(version=1,utc=datetime.now(timezone.utc).isoformat(),
            files=entries,source='Immutable hosted public .5 plus published stage9 revision2',
            hosted_changes=False),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(folder=str(target),net_files=len(delivery),overlay_files=len(files))))


if __name__=='__main__':main()
