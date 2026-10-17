import json, tempfile, unittest
from pathlib import Path
from tio.arena_map import load_arena_map
from tio.protocol.battle_ground import encode_battle_ground, decode_battle_ground

ROOT=Path(__file__).resolve().parents[1]


class ArenaMapTests(unittest.TestCase):
    def test_ground_metadata_never_enables_persistent_exploration(self):
        from tio.arena_map import build_arena_map
        source=json.loads((ROOT/'config/arena_map.json').read_text())
        fragments=json.loads((ROOT/'config/arena_fragments.json').read_text())
        for ground_id in range(5):
            arena=build_arena_map({**source,'ground_id':ground_id},fragments)
            packet=encode_battle_ground(arena.ground)
            self.assertEqual(packet[1],0)

    def test_wire_dimensions_and_all_spawns(self):
        map=load_arena_map(ROOT/'config/arena_map.json')
        ground=decode_battle_ground(encode_battle_ground(map.ground))
        self.assertEqual((ground.width,ground.height),(32,32))
        self.assertEqual(len(ground.first_layer),1024)
        self.assertEqual(len(set(map.player_spawns+map.bot_spawns)),6)
        self.assertTrue(map.blocked)
        self.assertEqual(len(ground.entries),4)
        self.assertTrue(all(not e.name.endswith(b'.s') for e in ground.entries))

    def test_reject_unsafe_layout_before_scene(self):
        source=json.loads((ROOT/'config/arena_map.json').read_text())
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'map.json'
            (Path(folder)/'arena_fragments.json').write_bytes((ROOT/'config/arena_fragments.json').read_bytes())
            for change in ({'width':0},{'ground_id':5},{'bot_spawns':source['player_spawns']},
                           {'objects':[{'file':'../escape.s','x':1,'y':1,'blocked_width':3,'blocked_height':3}]},
                           {'objects':[{'file':'tree.s','x':12,'y':14,'blocked_width':3,'blocked_height':3}]}):
                p.write_text(json.dumps({**source,**change}))
                with self.assertRaises(ValueError):load_arena_map(p)

    def test_cover_cells_block_whole_move_without_spending_ap(self):
        from tio.battle_state import BattleField,BattleActor
        from tio.protocol.battle_move import BattleMove
        map=load_arena_map(ROOT/'config/arena_map.json')
        self.assertTrue({(17,10),(18,10),(17,11),(18,11)}<=map.blocked)
        self.assertNotIn((16,10),map.blocked)
        field=BattleField(32,32,[BattleActor(1,7,15,10,40)],blocked=map.blocked,step_cost=1)
        before=field.actor(1)
        with self.assertRaises(ValueError):field.move(7,BattleMove(1,((16,10),(17,10))))
        self.assertEqual(field.actor(1),before)
        field.move(7,BattleMove(1,((16,10),)))
        self.assertEqual(field.actor(1).action_points,39)
