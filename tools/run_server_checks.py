"""Portable server baseline; never invokes hosted verification or deployment."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
MODULES = (
    'test_server_deployment',
    # Deliberately scoped smoke checks, not the entire legacy suite.
    # Known legacy failures/hangs are recorded in docs/VALIDATION.md.
    'test_multi_account.MultiAccountTests.test_bad_password_duplicate_login_and_reconnect_do_not_affect_other_player',
    'test_multi_account.MultiAccountTests.test_city_weapon_swap_tcp_persists_and_is_account_isolated',
    'test_multi_account.MultiAccountTests.test_private_bank_commands_shared_securities_replay_and_no_peer_broadcast',
    'test_survival_multiplayer_queue',
    'test_player_trade',
    'test_rating_visibility',
    'test_wallets',
    'test_settlement_health',
    'test_server_performance',
    'test_pool_listing_performance',
    'test_read_projection_performance',
    'test_idle_write_performance',
    'test_ability_protocol',
    'test_shared_mine_arena.SharedMineArenaTests.test_skill_bar_request_lists_own_battle_skills_and_slash_is_usable',
)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
