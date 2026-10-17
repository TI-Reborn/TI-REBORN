"""Local-only contract map compatibility, excluded from public hosted rollout."""
import json
from pathlib import Path
import unittest
from tests import test_world_core_integration as fixtures
from tio.map_generation import generate_map
from tio.team_scene import prepare

ROOT=Path(__file__).resolve().parents[1]

class ContractWorldSceneCompatibilityTests(unittest.TestCase):
    setUp=fixtures.WorldSceneCoreTests.setUp

    def test_explicit_contract_map_keeps_local_scene_contract(self):
        data=json.loads((ROOT/'config/contracts_map_profiles.json').read_text(encoding='utf-8'))
        generated=generate_map('contract_camp',seed=7,deployment_size=8,profiles_data=data)
        self.assertEqual(len(generated.arena.player_spawns),8)
        result=prepare(self.seats,0,seed=7,arena_map=generated.arena,selected_ids=True)
        self.assertEqual((result[0].width,result[0].height),(38,38))
        self.assertNotIn('world_policy',result[0].scene_metadata)
