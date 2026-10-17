"""Freeze reviewed interface changes over the actual public server snapshot."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'reports/gameplay-followup/stage1-interfaces/public-regression'
FOLDER=ROOT/'reports/gameplay-completion/stage9-interfaces'
FILES=('server/alliance_service.py','server/assault_public.py','server/bank_gateway.py',
       'server/economy_runtime.py','tio/arena_service.py','tio/battle_item_visuals.py',
       'tio/protocol/clan_ratings.py','tio/protocol/night_vision_state.py','tio/team_scene.py')


def main():
    metadata=BASE/'snapshot.json'
    baseline=json.loads(metadata.read_text(encoding='utf-8'))['source_sha256']
    manifest=FOLDER/'candidate-manifest.json'
    if manifest.exists():raise ValueError('Preserve the frozen candidate manifest')
    overrides={};entries={}
    for name,digest in baseline.items():
        raw=(BASE/'snapshot'/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Actual hosted snapshot changed: '+name)
        target=FOLDER/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw);overrides[name]='runtime/'+name
    for name in FILES:
        raw=(ROOT/name).read_bytes();compile(raw,name,'exec')
        digest=hashlib.sha256(raw).hexdigest()
        if digest==baseline.get(name):raise ValueError('Unchanged candidate: '+name)
        target=FOLDER/'runtime'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw);overrides[name]='runtime/'+name
        entries[name]=dict(source='runtime/'+name,before=baseline.get(name),sha256=digest)
    value=dict(version=1,utc=datetime.now(timezone.utc).isoformat(),files=entries,
               public_baseline_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),
               local_private_contracts_included=False,hosted_player_data_uploaded=False)
    manifest.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    (FOLDER/'runtime-files.json').write_text(json.dumps(list(FILES),indent=2)+'\n',encoding='utf-8')
    (FOLDER/'candidate-overrides.json').write_text(json.dumps(overrides,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(frozen_files=len(FILES),public_base_files=len(baseline),
                         manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())))


if __name__=='__main__':main()
