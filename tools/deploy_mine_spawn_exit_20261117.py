"""Publish mine entry movement fixes with guarded, data-preserving deployment."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployment

deployment.WORK = ROOT / 'work/mine-spawn-exit-20261117'
deployment.OUT = ROOT / 'reports/mine-spawn-exit-20261117'
deployment.SCOPE = 'mine-spawn-exit-20261117'
deployment.TEMPLATE = deployment.TEMPLATE.replace('20261018', '20261117')
deployment.FILES = ('server/team_arena.py', 'server/mine_arena.py')
deployment.MODULES = ['test_mine_spawn_exit', 'test_shared_mine_arena',
                      'test_shared_mining_state', 'test_gameplay_feedback_20261117']

if __name__ == '__main__':
    deployment.main()
