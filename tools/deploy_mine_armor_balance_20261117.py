"""Deploy approved mine armor with hosted backups and idle battle guards."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployment

deployment.WORK = ROOT / 'work/mine-armor-balance-20261117'
deployment.OUT = ROOT / 'reports/mine-armor-balance-20261117'
deployment.SCOPE = 'mine-armor-balance-20261117'
deployment.TEMPLATE = deployment.TEMPLATE.replace('20261018', '20261117')
deployment.FILES = ('config/mining.json',)
deployment.MODULES = ['test_mine_armor_balance', 'test_mine_automatic_damage',
                      'test_shared_mining_state', 'test_shared_mine_arena',
                      'test_gameplay_feedback_20261117', 'test_mine_spawn_exit']

if __name__ == '__main__':
    deployment.main()
