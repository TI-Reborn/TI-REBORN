from wallet_fixture import fund_wallet
import json, sqlite3, tempfile, unittest
from unittest.mock import patch
from contextlib import closing
from pathlib import Path
from tio.abilities import AbilityCatalog, AbilityLevel
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.wallets import WalletStore
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.matchmaking import SurvivalQueue
from tio.protocol.battle_soldier import decode_battle_soldier
from tools.survival_scene import prepare_survival

ROOT = Path(__file__).resolve().parents[1]


class SurvivalSceneTests(unittest.TestCase):
    @patch('tio.ranks.time.time', return_value=1700000000)
    def test_full_squad_bot_and_no_database_mutation(self,clock):
        # Rank activity refreshes a deadline; crossing a wall-clock second
        # must not make this unrelated inventory-preservation test flaky.
        source = json.loads((ROOT/'config/abilities.json').read_text())
        catalog = AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
        template = bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state.db'
            fund_wallet(path, 'alice', credits=10_000, gold=10_000)
            hire = HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template)
            hire.hire('alice',1); hire.hire('alice',3); hire.hire('alice',2)
            rows = OwnedPetStore(path).list('alice')
            ids = [r[0] for r in rows]
            from tio.shop import ShopStore
            from tio.protocol.shop_purchase import ShopPurchase
            from tio.protocol.item_list import decode_item_list
            shop=ShopStore(path,hire.catalogs)
            # Real purchases: ammunition packs and a grenade must survive entry.
            for template in (3,317):
                offer=next(o for o in shop.catalogs.items[0] if o.item_id==template)
                shop.purchase('alice',ShopPurchase(ids[0],0,offer.unknown_u32_01,2))
            squad = SquadStore(path)
            for slot, actor in enumerate(reversed(ids),1): squad.assign('alice',actor,slot)
            ticket = SurvivalQueue().join(42,OwnedPetStore(path).list('alice'))
            with closing(sqlite3.connect(path)) as db: before = '\n'.join(db.iterdump())
            # Keep this LOS/movement regression on its deliberate fixed geometry.
            from tio.arena_map import load_arena_map
            scene = prepare_survival(path,'alice',ticket,catalog,
                                     arena_map=load_arena_map(ROOT/'config/arena_map.json'))
            inventories={decode_item_list(p)[0]:p for p in scene.packets if p[:1]==b'\x30'}
            saved={i:inv for i,pet,inv in OwnedPetStore(path).list('alice')}
            self.assertEqual(inventories,saved)
            bought=decode_item_list(inventories[ids[0]])[1]
            self.assertEqual(sum(i.count for i in bought if i.template_id==3),100)
            self.assertEqual(sum(i.count for i in bought if i.template_id==317),2)
            for i,p in inventories.items():
                actor_index=next(n for n,q in enumerate(scene.packets) if q[:1]==b'\x3b' and int.from_bytes(q[1:5],'little')==i)
                self.assertLess(actor_index,scene.packets.index(p))
                self.assertLess(scene.packets.index(p),len(scene.packets)-1)
            self.assertEqual(scene.actor_ids,tuple(reversed(ids)))
            self.assertEqual(len(scene.field.actor_ids(42)),3)
            self.assertEqual(len(scene.field.actor_ids(scene.bot_owner)),3)
            decoded = []
            for packet in scene.packets:
                if packet[:1] != b'\x3b': continue
                # Resource is after actor and owner IDs in this recovered layout.
                for human in (True,False):
                    try: actor = decode_battle_soldier(packet,human_equipment=human)
                    except ValueError: continue
                    decoded.append(actor); break
                else: self.fail('Undecodable scene actor')
            self.assertEqual(len(decoded),6)
            for actor in decoded:
                state = scene.field.actor(actor.soldier_id)
                self.assertEqual(state.sight_radius,9 if actor.human_equipment else 12)
                self.assertEqual(state.action_points,15 if actor.human_equipment else 17)
                self.assertEqual(actor.fields['0x8c571d'],state.action_points)
                self.assertEqual(actor.fields['0x8c5694'],state.action_points)
                self.assertTrue(state.weapons)
                self.assertTrue(all(w.attack_ap>0 for w in state.weapons))
                if not actor.human_equipment:self.assertEqual(state.weapons[0].template_id,333)
                self.assertEqual(actor.fields['0x8c567f'],state.sight_radius)
                self.assertEqual((actor.owner_id,actor.fields['0x8c519b'],actor.fields['0x8c51af']), (state.owner_id,state.x,state.y))
            self.assertEqual(len({(a.fields['0x8c519b'],a.fields['0x8c51af']) for a in decoded}),6)
            from dataclasses import replace
            for actor in decoded:
                state=scene.field.actor(actor.soldier_id)
                scene.field._actors[state.actor_id]=replace(state,action_points=state.action_points-1)
                snapshot=decode_battle_soldier(scene.visibility.snapshot(state.actor_id),human_equipment=actor.human_equipment)
                self.assertEqual(snapshot.fields['0x8c571d'],state.action_points-1)
                self.assertEqual(snapshot.fields['0x8c5694'],state.action_points)
                scene.field._actors[state.actor_id]=state
            from tio.arena_service import ArenaService
            from tio.training_bot import play_turn
            from tio.protocol.battle_turn import encode_end_turn
            arena = ArenaService()
            room, packets = arena.start_survival(42,b'Alice',scene)
            self.assertEqual(room.members,(42,scene.bot_owner))
            self.assertEqual(arena.inventory_packets(42,(*ids,*scene.field.actor_ids(scene.bot_owner),999)),tuple(saved[i] for i in ids))
            self.assertEqual(arena.inventory_packets(42,scene.field.actor_ids(scene.bot_owner)),())
            self.assertIsNone(arena.inventory_packets(999,ids))
            self.assertEqual(packets[-1],b'\x41')
            with self.assertRaises(ValueError): arena.begin_turn(42,scene.actor_ids,40)
            arena.member_loaded(42,b'\x36')
            arena.begin_turn_packets(42,scene.actor_ids,40)
            for i in scene.actor_ids:
                self.assertEqual(scene.field.actor(i).action_points,15 if scene.field.combat.human[i] else 17)
            arena.end_turn(42,encode_end_turn(scene.actor_ids[0]))
            bot_packets = play_turn(arena,room.room_id,scene.bot_owner)
            self.assertGreaterEqual(sum(p[:1]==b'\x3d' for p in bot_packets),3)
            self.assertNotIn(b'\x38',bot_packets)
            arena.begin_turn_packets(42,scene.actor_ids,40)
            self.assertEqual(arena._turns[room.room_id][0],42)
            from tio.visibility import VisibilityView
            from tio.protocol.battle_remove import decode_battle_remove
            from dataclasses import replace
            # Restore the opposed spawn positions for this independent LOS case;
            # the bot can now use its whole AP budget and cross the future wall.
            for actor in decoded:
                current=scene.field.actor(actor.soldier_id)
                scene.field._actors[actor.soldier_id]=replace(current,x=actor.position[0],y=actor.position[1])
            view=VisibilityView(scene.field,42,scene.visibility.templates)
            initial=view.refresh()
            self.assertEqual(len(initial),6)
            # Place a solid barrier between the squads. The client must receive
            # removals followed by anonymous off-map alive/dead models.
            scene.field.blocked=frozenset({(16,y) for y in range(32)})
            hidden=view.refresh()
            self.assertEqual({decode_battle_remove(p) for p in hidden if p[0]==0x43},set(scene.field.actor_ids(scene.bot_owner)))
            for packet in hidden:
                if packet[0]==0x3b:
                    model=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                    self.assertEqual(model.position,(255,255))
                    self.assertEqual(model.fields['0x8c57bb'],1)
            self.assertEqual(view.refresh(),())
            # Hidden enemies are neither chased by the bot nor sent to the
            # observer as movement/AP/skill updates during its turn.
            arena.end_turn(42,encode_end_turn(scene.actor_ids[0]))
            positions={i:scene.field.actor(i).x for i in scene.field.actor_ids(scene.bot_owner)}
            self.assertEqual(play_turn(arena,room.room_id,scene.bot_owner,view=view),())
            self.assertEqual({i:scene.field.actor(i).x for i in positions},positions)
            enemy=scene.field.actor_ids(scene.bot_owner)[0]
            old=scene.field.actor(enemy)
            scene.field._actors[enemy]=replace(old,x=22,y=16,health=77,action_points=19)
            self.assertEqual(view.refresh(),())
            scene.field.blocked=frozenset()
            shown=view.refresh()
            self.assertEqual(len(shown),3)
            fresh=view.templates[enemy]
            packet=next(p for p in shown if int.from_bytes(p[1:5],'little')==enemy)
            actor=decode_battle_soldier(packet,human_equipment=fresh.human_equipment)
            self.assertEqual((actor.position,actor.fields['0x8c57bb'],actor.fields['0x8c571d']),((22,16),77,19))
            with closing(sqlite3.connect(path)) as db: self.assertEqual('\n'.join(db.iterdump()),before)
            with self.assertRaises(ValueError): prepare_survival(path,'other',ticket,catalog)
            squad.assign('alice',ids[0],0)
            with self.assertRaises(ValueError): prepare_survival(path,'alice',ticket,catalog)
