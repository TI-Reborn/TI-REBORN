"""Scoped list fix; preserve actual hosted gameplay files and saved accounts."""
import argparse,inspect,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import deploy_awp_scope_20261019 as d
from tools.prepare_wager_list_fix_20261019 import WORK,OUT,FILES,main as prepare
MODULES=['test_wager_list_removal','test_wagers','test_shared_wager_arena','test_pool_listing_performance','test_shared_team_arena','test_detroit_wager_maps']

def main(mode):
    prepare();d.WORK=WORK;d.OUT=OUT;d.FILES=FILES
    d.REMOTE=d.REMOTE.replace('awp-scope','wager-list-fix').replace(" exec(compile(request['deployer']", " sys.argv.append('--maintenance-restart')\n exec(compile(request['deployer']")
    source=inspect.getsource(d.run).replace('awp-scope','wager-list-fix')
    start=source.index('modules=[\n');end=source.index('])',start)+2
    source=source[:start]+'modules='+repr(MODULES)+')'+source[end:]
    exec(compile(source,'scoped-wager-list-fix','exec'),d.__dict__);d.run(mode)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));main(p.parse_args().mode)
