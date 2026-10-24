"""Scoped, guarded server release based on this task's fresh hosted snapshot."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
WORK=ROOT/'work/scope-square-20261019';OUT=ROOT/'reports/scope-square-20261019'
FILES=('tio/sniper_scope.py','tio/recon_geometry.py','tio/battle_item_effects.py','tio/battle_item_visuals.py','tio/protocol/battle_item_visuals.py')

def candidate_bytes(name):
    if name!='tio/battle_item_effects.py':return (ROOT/name).read_bytes()
    raw=(WORK/'baseline'/name).read_bytes()
    old=b"        if ((target.x-x)**2 + (target.y-y)**2 <= recon['radius']**2"
    new=b"        from .recon_geometry import contains\n        if (contains(recon, target.x, target.y)"
    assert raw.count(old)==1
    return raw.replace(old,new)

def main(mode):
    candidate=WORK/'candidate';review={}
    for name in FILES:
        dest=candidate/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(candidate_bytes(name))
        review[name]=dict(before=hashlib.sha256((WORK/'baseline'/name).read_bytes()).hexdigest() if (WORK/'baseline'/name).exists() else None,after=hashlib.sha256(dest.read_bytes()).hexdigest())
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2))
    d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','scope-square').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    # run() scopes its deployer under the historical name. Change both ends.
    original=d.run
    source=__import__('inspect').getsource(original).replace("'awp-scope'","'scope-square'")
    # Its single-quoted source literal contains escaped quotes.
    source=source.replace("awp-scope","scope-square")
    source=source.replace("'test_sniper_scope','test_weapon_effects','test_skills_fixture'", "'test_sniper_scope','test_ability_status','test_weapon_effects','test_skills_fixture'")
    exec(compile(source,'scoped-scope-square-run','exec'),d.__dict__)
    d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
