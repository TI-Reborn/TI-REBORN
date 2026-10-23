"""Scoped server release from freshly inspected hosted baseline; idle guard remains."""
import argparse,hashlib,inspect,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
WORK=ROOT/'work/molotov-fix-20261019';OUT=ROOT/'reports/molotov-fix-20261019'
FILES=('tio/battle_hazards.py','server/battle_events.py')

def main(mode):
    review={}
    for name in FILES:
        dest=WORK/'candidate'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        # Neither baseline file has unrelated local changes before this task.
        dest.write_bytes((ROOT/name).read_bytes())
        review[name]=dict(before=hashlib.sha256((WORK/'baseline'/name).read_bytes()).hexdigest(),after=hashlib.sha256(dest.read_bytes()).hexdigest())
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2))
    d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','molotov-fix').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    source=inspect.getsource(d.run).replace('awp-scope','molotov-fix')
    source=source.replace("'evidence/battle_item_native.json')", "'evidence/battle_item_native.json','evidence/special_items_native.json')")
    source=source.replace("'test_sniper_scope','test_weapon_effects','test_skills_fixture',*item_tests,", "'test_floor_fire','test_special_items','test_shared_special_items','test_battle_crash_recovery',")
    exec(compile(source,'scoped-molotov-run','exec'),d.__dict__);d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
