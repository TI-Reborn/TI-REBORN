"""Validate/deploy the follow-up against its fresh hosted baseline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-followup'
    deployer.BASELINE = 'phase2-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/followup'
    deployer.OUT.mkdir(exist_ok=True)
    deployer.FILES = ('tio/shooting_range.py', 'tio/weapon_effects.py',
                      'tools/encounter_scene.py', 'tools/shooting_range_scene.py',
                      'server/battle_journal.py', 'tools/loopback_exchange.py',
                      'tio/enhancement.py', 'tio/protocol/clan_ratings.py')
    deployer.MODULES = ['test_player_feedback_followup_20261104',
                        'test_player_feedback_20261104', 'test_miner_abilities',
                        'test_training_bot', 'test_snapshot_fast_types', 'test_enhancement',
                        'test_clan_warfare_protocol', 'test_alliance_service.AllianceServiceTests.test_native_ratings_queries_while_busy_are_read_only_and_echo_actual_page_selector',
                        'test_shooting_range.AdmissionTests.test_daily_token_does_not_accumulate_and_survives_restart',
                        'test_shooting_range.AdmissionTests.test_parallel_free_entries_charge_only_once',
                        'test_shooting_range.RangeTests.test_prepare_failure_keeps_funds_and_lobby',
                        'test_shooting_range.RangeTests.test_native_payment_mapping_and_nonhuman_target_health',
                        'test_shooting_range.RangeTests.test_real_shot_persists_ammo_and_skill_without_xp_or_rank_rewards',
                        'test_shooting_range.RangeTests.test_destroying_all_targets_keeps_sight_safe_for_native_client_and_reload',
                        'test_shooting_range.RangeTests.test_targets_never_take_turns_and_exit_has_no_penalty']
    deployer.main()
