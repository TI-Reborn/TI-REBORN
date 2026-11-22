"""Validate/deploy the native practice escape transition against hosted code."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-range-exit'
    deployer.BASELINE = 'phase5-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/range-exit'
    deployer.OUT.mkdir(exist_ok=True)
    deployer.FILES = ('tools/loopback_exchange.py',)
    deployer.MODULES = [
        'test_player_feedback_range_exit_20261104',
        'test_player_feedback_followup_20261104',
        'test_player_feedback_20261104', 'test_battle_finish',
        'test_training_bot', 'test_city_session',
        'test_player_feedback_presence_20261104',
    ]
    deployer.main()
