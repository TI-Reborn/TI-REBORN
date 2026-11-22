"""Validate/deploy saved portraits in reserve and ready roster updates."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-avatar-cards'
    deployer.BASELINE = 'phase7-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/avatar-cards'
    deployer.FILES = ('tio/avatars.py', 'tools/loopback_exchange.py',
                      'server/avatar_service.py')
    deployer.MODULES = [
        'test_player_feedback_avatar_sync_20261105', 'test_avatars',
        'test_squad', 'test_player_feedback_range_exit_20261104',
        'test_player_feedback_followup_20261104',
        'test_player_feedback_20261104', 'test_battle_recovery.MinerRecoveryTests',
        'test_player_feedback_dog_fog_20261105',
    ]
    deployer.main()
