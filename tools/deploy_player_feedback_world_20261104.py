"""Validate and deploy live population, presence refresh and mining standings."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-world'
    deployer.BASELINE = 'phase3-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/world'
    deployer.OUT.mkdir(exist_ok=True)
    deployer.FILES = ('server/team_arena.py', 'server/presence.py',
                      'server/world_runtime.py', 'tio/world_completion.py',
                      'tio/crystal_market.py', 'tio/mining_service.py',
                      'tio/protocol/mining.py')
    deployer.MODULES = [
        'test_player_feedback_presence_20261104',
        'test_player_feedback_mining_rating_20261104',
        'test_presence', 'test_mining_rating_menu', 'test_mine_claims_and_tax',
        'test_crystal_quote_history', 'test_shared_survival_groups',
        'test_world_completion.WorldCompletionTests.test_top100_reads_every_offline_account_not_recent_or_online_and_stable_tie',
        'test_world_completion.WorldCompletionTests.test_all_manual_sorts_and_valid_character_aliases',
        'test_world_completion.WorldCompletionTests.test_dismissed_rating_xp_rank_removed_wager_wins_excluded',
        'test_world_completion.WorldCompletionTests.test_rating_bonus_adapter_uses_earned_backend_and_empty_schema_read_only',
        'test_player_feedback_followup_20261104',
    ]
    deployer.main()
