"""Freeze reviewed world sources while retaining explicit public-only overrides."""
import hashlib
import json
from pathlib import Path
import shutil
from tools.deploy_gameplay_completion import ROOT,validate,source_path

FOLDER=ROOT/'reports/gameplay-completion/stage8-world'
FILES=('config/world_completion.json','config/world_completion_maps.json','config/territories.json','config/clan_benefits.json',
 'tio/cities.py','tio/locations.py','tio/world_completion.py','tio/protocol/player_top100.py','tio/map_generation.py',
 'tio/team_scene.py','tio/combat.py','tio/reward_policy.py','tio/battle_rewards.py','tio/clan_benefits.py','tio/territories.py',
 'server/world_runtime.py','server/training_arena.py','server/multi.py','server/team_arena.py','server/presence.py',
 'server/battle_journal.py','server/assault_arena.py','server/wager_arena.py','server/alliance_service.py',
 'tools/loopback_exchange.py','tools/moderate_prison.py','evidence/zones_diagnostic.xml')
SCOPED={'tio/map_generation.py','tio/battle_rewards.py','server/multi.py','server/team_arena.py','server/presence.py',
        'tools/loopback_exchange.py','evidence/zones_diagnostic.xml'}

def main():
    target=FOLDER/'runtime-files.json'
    if target.exists():raise ValueError('Preserve the already frozen runtime package')
    overrides=json.loads((FOLDER/'candidate-overrides.json').read_text())
    hashes={}
    for name in sorted(FILES):
        candidate=FOLDER/'runtime'/name
        if name in SCOPED:
            if not candidate.is_file():raise ValueError('Missing reviewed public override: '+name)
        else:
            candidate.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,candidate)
        raw=candidate.read_bytes();validate(name,raw)
        hashes[name]=hashlib.sha256(raw).hexdigest()
        overrides[name]='runtime/'+name
    for forbidden in ('contracts','pve_contracts','battle_snapshot','battle_map_profiles'):
        if any(forbidden in name for name in FILES):raise ValueError('Local-only work entered the package')
    (FOLDER/'candidate-overrides.json').write_text(json.dumps(overrides,indent=2)+'\n')
    with target.open('x') as output:json.dump(sorted(FILES),output,indent=2)
    with (FOLDER/'frozen-sources.json').open('x') as output:json.dump(hashes,output,indent=2)
    for name,digest in hashes.items():
        if hashlib.sha256(source_path(FOLDER,name).read_bytes()).hexdigest()!=digest:raise ValueError('Frozen source changed')
    print(json.dumps(dict(files=len(FILES),all_sources_frozen=True,local_contracts_included=False)))

if __name__=='__main__':main()
