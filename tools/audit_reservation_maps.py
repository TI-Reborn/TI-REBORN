"""Audit every configured fragment and a reproducible sample of generated maps."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.map_generation import generate_map, reachable_cells, connected


def main():
    policy=json.loads((ROOT/'config/battle_map_profiles.json').read_text())['profiles']['reservation']
    fragments=json.loads((ROOT/'config/arena_fragments.json').read_text())
    pool={name for names in policy['pools'].values() for name in names}
    base=Path(r'C:\Program Files (x86)\TIOnline\base')
    for name in pool:
        fragment=fragments[name]
        assert hashlib.sha256((base/'maps'/name).read_bytes()).hexdigest()==fragment['sha256'],name
        assert not any('tree' in m.lower() or 'village_house' in m.lower() or 'forest' in m.lower() for m in fragment['models']),name
        for model,digest in fragment['door_models_sha256'].items():
            assert hashlib.sha256(next((base/'setting').rglob(model)).read_bytes()).hexdigest()==digest,model
    used=set();elapsed=[];records=[]
    for mode in (0,1,4,7):
        for variant in policy['variants']:
            for seed in range(50):
                started=time.perf_counter()
                scene=generate_map(mode=mode,variant=variant['name'],seed=seed,deployment_size=6)
                elapsed.append(time.perf_counter()-started)
                assert connected(scene.arena,reachable_cells(scene.arena))
                used.update(o['file'] for o in scene.layout['objects'])
                records.append(dict(mode=mode,variant=scene.variant,seed=seed,
                    width=scene.arena.ground.width,height=scene.arena.ground.height,
                    crates=len(scene.arena.containers),doors=len(scene.arena.doors)))
    assert used==pool,sorted(pool-used)
    result=dict(passed=True,sample_count=len(records),configured_fragments=len(pool),
        sampled_fragments=len(used),max_generation_seconds=max(elapsed),
        mean_generation_seconds=sum(elapsed)/len(elapsed),records=records)
    (ROOT/'evidence/reservation-map-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))


if __name__=='__main__':main()
