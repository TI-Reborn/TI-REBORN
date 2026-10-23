"""Scoped authoritative TrueSkill update, guarded against active battles."""
import argparse,inspect,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
from tools.prepare_trueskill_bots_20261019 import WORK,OUT,FILES,main as prepare
MODULES=['test_ranked_bots','test_ranked','test_ranked_squads','test_ranked_cancel',
         'test_team_lobbies','test_shared_team_arena','test_team_ranked','test_wall_ranked','test_contest_maps','test_tactical_bot']

def main(mode):
    prepare();d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','trueskill-bots').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    source=inspect.getsource(d.run).replace('awp-scope','trueskill-bots')
    start=source.index("modules=[\n");end=source.index('])',start)+2
    source=source[:start]+'modules='+repr(MODULES)+')'+source[end:]
    exec(compile(source,'scoped-trueskill-bots-run','exec'),d.__dict__);d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
