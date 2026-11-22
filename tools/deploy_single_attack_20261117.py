"""Deploy one-roll attacks with the existing backups and idle-battle guards."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployment

deployment.WORK = ROOT / 'work/single-attack-20261117'
deployment.OUT = ROOT / 'reports/mine-automatic-20261117'
deployment.SCOPE = 'single-attack-20261117'
deployment.TEMPLATE = deployment.TEMPLATE.replace('20261018', '20261117')
deployment.FILES = ('tio/combat_rolls.py',)
deployment.MODULES = [
    'test_mine_automatic_damage', 'test_weapon_enhancement_damage',
    'test_battle_core.RollsTests.test_ammunition_count_does_not_split_attack_damage_or_random_rolls',
    'test_battle_core.RollsTests.test_attack_miss_does_not_roll_damage_or_critical',
    'test_battle_core.RollsTests.test_one_critical_doubles_the_entire_attack',
    'test_shared_mining_state', 'test_weapon_proficiency', 'test_area_fire',
    'test_combat', 'test_weapon_effects', 'test_armor_damage',
]

if __name__ == '__main__':
    deployment.main()
