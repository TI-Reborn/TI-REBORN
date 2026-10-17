from wallet_fixture import fund_wallet
import tempfile,sqlite3,unittest
from pathlib import Path
from types import SimpleNamespace
from contextlib import closing
from dataclasses import replace
from tio.arena_service import ArenaService
from tio.battle_state import BattleActor,BattleField
from tio.protocol.battle_ground import BattleGround,encode_battle_ground
from tio.wallets import WalletStore
from tio.battle_rewards import settle


class BattleFinishTests(unittest.TestCase):
    def test_last_kill_stops_turn_and_pays_once(self):
        from tio.combat import Combat
        from tio.weapons import WeaponCatalog
        from tio.protocol.item_list import encode_item_list
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';wallet=WalletStore(path);fund_wallet(wallet.path, 'alice', credits=10_000, gold=10_000)
            arena=ArenaService();scene=self.scene(100,1)
            scene.field._actors[2]=replace(scene.field.actor(2),x=2,y=1)
            scene.field.combat=Combat(scene.field,WeaponCatalog(),rng=SimpleNamespace(randrange=lambda n:0,randint=lambda a,b:a))
            scene.field.combat.register(1,encode_item_list(1,()),human=False)
            room,_=arena.start_survival(7,b'Alice',scene)
            arena.member_loaded(7,b'\x36');arena.begin_turn_packets(7,(1,),40)
            attack=encode_attack_request(AttackRequest(1,2,1))
            self.assertEqual(arena.attack(7,attack)[0][0],0x4b)
            self.assertNotIn(room.room_id,arena._turns)
            with self.assertRaises(ValueError):arena.attack(7,attack)
            result=arena.finish_training(7,path,'alice')[-1]
            import struct
            self.assertEqual(struct.unpack_from('<6I',result,4),(1,0,1,0,0,0))
            self.assertEqual(wallet.ensure('alice').credits,10000)

    def scene(self,own_hp,enemy_hp):
        field=BattleField(8,8,[BattleActor(1,7,1,1,15,own_hp,100),BattleActor(2,8,4,4,15,enemy_hp,100)],step_cost=1)
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        return SimpleNamespace(field=field,packets=(ground,b'\x41'),actor_ids=(1,),bot_owner=8)

    def test_victory_defeat_draw_cleanup_and_repeat(self):
        for own,enemy,result,credits in ((100,0,1,10000),(0,100,0,10000),(0,0,2,10000)):
            with self.subTest(result=result),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'state.db';wallet=WalletStore(path);fund_wallet(wallet.path, 'alice', credits=10_000, gold=10_000)
                arena=ArenaService();scene=self.scene(own,enemy)
                room,_=arena.start_survival(7,b'Alice',scene)
                match_id=arena._match_ids[room.room_id]
                replies=arena.finish_training(7,path,'alice')
                self.assertEqual(replies[-1][0],0x4c)
                self.assertEqual(replies[-1][3],result)
                self.assertFalse(any(p[:1]==b'\xf0' for p in replies))
                self.assertEqual(wallet.ensure('alice').credits,credits)
                self.assertFalse(arena.rooms.snapshot());self.assertFalse(arena._fields)
                self.assertFalse(arena._turns);self.assertFalse(arena._last_turn)
                self.assertEqual(arena.finish_training(7,path,'alice'),())
                self.assertEqual(settle(path,'alice',match_id,result).credits,credits)
                transition=arena.finish_results(7,b'\x2a\x01')
                self.assertEqual(int.from_bytes(transition[0][1:5],'little'),449)
                self.assertEqual(int.from_bytes(transition[1][-4:],'little'),3)
                self.assertEqual(arena.finish_results(7,b'\x2a\x01'),transition)
                self.assertIsNone(arena.finish_results(999,b'\x2a\x01'))
                self.assertEqual(wallet.ensure('alice').credits,credits)
                with self.assertRaises(ValueError):arena.finish_results(7,b'\x2a')
                with self.assertRaises(ValueError):settle(path,'alice',match_id,(result+1)%3)
                # A finished room must not prevent another arena entry.
                arena.start_survival(7,b'Alice',self.scene(100,100))
                self.assertIsNone(arena.finish_results(7,b'\x2a\x01'))

    def test_living_opponents_do_not_end_and_failed_reward_retries(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';wallet=WalletStore(path);fund_wallet(wallet.path, 'alice', credits=10_000, gold=10_000)
            arena=ArenaService();scene=self.scene(100,100)
            room,_=arena.start_survival(7,b'Alice',scene)
            self.assertEqual(arena.finish_training(7,path,'alice'),())
            scene.field._actors[2]=replace(scene.field.actor(2),health=0)
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('UPDATE wallets SET credits=4294967295')
            from unittest.mock import patch
            with patch('tio.battle_rewards.settle',side_effect=ValueError('temporary settlement failure')):
                with self.assertRaises(ValueError):arena.finish_training(7,path,'alice')
            self.assertTrue(arena.rooms.snapshot())
            with closing(sqlite3.connect(path)) as db,db:db.execute('UPDATE wallets SET credits=0')
            arena.finish_training(7,path,'alice')
            self.assertEqual(wallet.ensure('alice').credits,0)
