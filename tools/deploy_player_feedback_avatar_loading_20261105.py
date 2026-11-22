"""Validate/deploy portrait replay after native scene load acknowledgements."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-avatar-loading'
    deployer.BASELINE = 'phase8-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/avatar-loading'
    deployer.FILES = ('tio/avatars.py', 'tio/battle_item_visuals.py',
                      'tools/loopback_exchange.py', 'server/team_arena.py',
                      'server/battle_reconnect.py')
    deployer.MODULES = [
        'test_player_feedback_avatar_loading_20261105',
        'test_player_feedback_avatar_sync_20261105', 'test_avatars',
        'test_battle_item_visuals', 'test_shared_team_arena',
        'test_battle_core.ReconnectTests',
        'test_shooting_range.AdmissionTests.test_daily_token_does_not_accumulate_and_survives_restart',
        'test_shooting_range.AdmissionTests.test_parallel_free_entries_charge_only_once',
        'test_shooting_range.RangeTests.test_prepare_failure_keeps_funds_and_lobby',
        'test_shooting_range.RangeTests.test_native_payment_mapping_and_nonhuman_target_health',
        'test_shooting_range.RangeTests.test_real_shot_persists_ammo_and_skill_without_xp_or_rank_rewards',
        'test_shooting_range.RangeTests.test_destroying_all_targets_keeps_sight_safe_for_native_client_and_reload',
        'test_shooting_range.RangeTests.test_targets_never_take_turns_and_exit_has_no_penalty',
        'test_player_feedback_range_exit_20261104',
        'test_player_feedback_followup_20261104',
        'test_player_feedback_dog_fog_20261105',
    ]
    deployer.main()
