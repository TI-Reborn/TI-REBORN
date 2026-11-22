"""Scoped gameplay deployment using the existing backup and idle guards."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployment

deployment.WORK = ROOT / 'work/gameplay-20261117'
deployment.OUT = ROOT / 'reports/gameplay-20261117'
deployment.SCOPE = 'gameplay-feedback-20261117'
deployment.TEMPLATE = deployment.TEMPLATE.replace('20261018', '20261117')
deployment.FILES = (
    'config/mining.json', 'config/weapon_catalog.json', 'config/shop_completion.json',
    'tio/mining.py', 'tio/crystal_market.py', 'tio/bank_economy.py', 'tio/clans.py',
    'server/mine_arena.py', 'server/team_arena.py', 'tools/import_weapon_catalog.py',
)
deployment.MODULES = [
    'test_gameplay_feedback_20261117', 'test_clan_item_marks', 'test_mining',
    'test_crystal_quote_history', 'test_crystal_quotes_consistency',
    'test_shared_mining_state', 'test_shared_mine_arena', 'test_native_item_marks',
    'test_battle_exchange', 'test_warehouse_transfer',
]

if __name__ == '__main__':
    deployment.main()
