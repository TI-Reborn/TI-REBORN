"""Validate and deploy native tooltip population without exposing private slots."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import deploy_player_feedback_20261104 as deployer

if __name__ == '__main__':
    deployer.SCOPE = 'player-feedback-tooltips'
    deployer.BASELINE = 'phase4-baseline'
    deployer.OUT = ROOT/'reports/player-feedback-20261104/tooltips'
    deployer.OUT.mkdir(exist_ok=True)
    deployer.FILES = ('server/presence.py', 'server/contracts_service.py',
                      'server/team_arena.py')
    deployer.MODULES = [
        'test_player_feedback_presence_20261104', 'test_presence',
        'test_team_heartbeat',
        'test_contract_world_scene_compat',
        'test_contracts_service.ContractsServiceTests.test_map_tooltip_public_reads_preserve_scene_visibility',
        'test_player_feedback_mining_rating_20261104',
        'test_player_feedback_followup_20261104',
    ]
    deployer.main()
