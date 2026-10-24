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
    'test_ranked',
    'test_ranked_squads',
    'test_ranked_bots',
    'test_ranked_party',
    'test_ranked_party_rules',
    'test_ranked_party_refactor',
    'test_ranked_cancel',
    'test_training_arena',
    'test_training_group_list',
    'test_training_on_demand',
    'test_clan_icon_upload',
    'test_clan_crest_projections',
    'test_premium_credits_policy',
    'test_warehouse_resources',
    'test_repair_warehouse_regression',
    'test_area_fire',
    'test_friends',
    'test_launch_admission',
    'test_repair_from_warehouse',
    'test_sniper_scope',
    'test_wager_list_removal',
    'test_battle_doors',
    'test_battle_events',
    'test_battle_item_visuals',
    'test_floor_fire',
    'test_shared_special_items',
    'test_skills_fixture',
    'test_weapon_effects',
    'test_ranked_loadout',
    'test_shared_mine_arena.SharedMineArenaTests.test_skill_bar_request_lists_own_battle_skills_and_slash_is_usable',
    'test_premium_effects',
    'test_mine_warehouses',
    'test_shared_warehouse',
    'test_warehouse_latency',
    'test_warehouse_errors',
    'test_city_inventory',
    'test_city_inventory_wait',
    'test_sc_shop_locations',
    'test_credits_only',
    'test_sc_clear_cart',
    'test_sc_ready_pricing',
    'test_gameplay_audit',
    'test_character_deletion',
    'test_mine_turn_repeats',
    'test_shooting_range_turn_repeats',
    'test_armor_equipment',
    'test_enhancement',
    'test_map_speed',
    'test_pve_contracts',
    'test_contracts_service',
    'test_contracts_ui',
    'test_contracts_combat',
    'test_contracts_local_tcp',
)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
