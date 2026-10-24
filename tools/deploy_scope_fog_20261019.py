"""Scoped, guarded server release based on this task's fresh hosted snapshot."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
WORK=ROOT/'work/scope-fog-20261019';OUT=ROOT/'reports/scope-fog-20261019'
FILES=('tio/sniper_scope.py','tio/protocol/ability_status.py','server/battle_events.py')

def main(mode):
    candidate=WORK/'candidate';review={}
    for name in FILES:
        dest=candidate/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
        review[name]=dict(before=hashlib.sha256((WORK/'baseline'/name).read_bytes()).hexdigest(),after=hashlib.sha256(dest.read_bytes()).hexdigest())
    (OUT/'server-review.json').write_text(json.dumps(review,indent=2))
    d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','scope-fog').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    # run() scopes its deployer under the historical name. Change both ends.
    original=d.run
    source=__import__('inspect').getsource(original).replace("'awp-scope'","'scope-fog'")
    # Its single-quoted source literal contains escaped quotes.
    source=source.replace("awp-scope","scope-fog")
    source=source.replace("'test_sniper_scope','test_weapon_effects','test_skills_fixture'", "'test_sniper_scope','test_ability_status','test_weapon_effects','test_skills_fixture'")
    exec(compile(source,'scoped-scope-fog-run','exec'),d.__dict__)
    d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
