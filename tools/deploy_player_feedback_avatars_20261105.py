"""Validate/deploy portrait synchronization and fog model retention."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-avatars'
    deployer.BASELINE = 'phase6-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/avatars'
    deployer.FILES = ('server/avatar_service.py', 'tools/loopback_exchange.py',
                      'tio/visibility.py', 'tio/battle_recovery.py')
    deployer.MODULES = [
        'test_player_feedback_avatar_sync_20261105',
        'test_player_feedback_dog_fog_20261105', 'test_avatars',
        'test_player_feedback_range_exit_20261104',
        'test_player_feedback_followup_20261104',
        'test_player_feedback_20261104', 'test_battle_events',
        'test_visibility', 'test_visibility_range_cost', 'test_training_bot',
        'test_shared_mining_state', 'test_battle_finish',
        'test_battle_recovery.MinerRecoveryTests',
    ]
    deployer.main()
