"""Authoritative shared-account supplies, delayed damage and save recovery."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import random
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio import battle_snapshot
from tio.arena_service import ArenaService
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.protocol.battle_attack import AttackRequest,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_mines import MineDeploy,MineDeployed,encode_mine_deploy,decode_mine_deploy,encode_mine_deployed,decode_mine_deployed
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.known_mines import decode_known_mines
from test_combat import item,FixedRandom

ROOT=Path(__file__).resolve().parents[1]


class SpecialItemsTests(unittest.TestCase):
    def prepare(self,weapon=321,*,teams=None):
        self.field=BattleField(14,10,[BattleActor(1,7,2,2,40,200,200),
            BattleActor(2,8,6,2,40,200,200),BattleActor(3,9,12,8,40,200,200)],step_cost=1,teams=teams)
        self.combat=Combat(self.field,WeaponCatalog(),rng=FixedRandom());self.field.combat=self.combat
        self.combat.register(1,encode_item_list(1,(item(100,weapon,equipped=weapon not in (321,325)),)),human=True)
        self.combat.register(2,encode_item_list(2,()),human=True)
        self.combat.register(3,encode_item_list(3,()),human=True)
        self.arena=ArenaService(clock=lambda:10)
        self.arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8,9)),))
        self.arena._fields[1]=self.field;self.arena._turns={1:(7,{1},20)}
        return self.field,self.combat

    def plant(self,template=321):
        self.prepare(template)
        return self.arena.mine_action(7,encode_mine_deploy(MineDeploy(1,100,3,2)))

    def move_enemy(self):
        self.arena._turns={1:(8,{2},20)}
        return self.arena.move(8,encode_move_request(BattleMove(2,((5,2),(4,2),(3,2),(3,3)))))

    def test_native_codec_cases_and_strict_lengths(self):
        evidence=ROOT/'evidence/special_items_native.json'
        if not evidence.exists():self.fail('Native ABI proof must be run before acceptance')
        rows=json.loads(evidence.read_text(encoding='utf-8'))
        for r in rows['deployment_requests']:
            value=MineDeploy(**r['fields']);packet=bytes.fromhex(r['packet_hex'])
            self.assertEqual(encode_mine_deploy(value),packet);self.assertEqual(decode_mine_deploy(packet),value)
        for r in rows['deployment_results']:
            value=MineDeployed(**r['fields']);packet=bytes.fromhex(r['packet_hex'])
            self.assertEqual(encode_mine_deployed(value),packet);self.assertEqual(decode_mine_deployed(packet),value)
        for encode,decode,value in ((encode_mine_deploy,decode_mine_deploy,MineDeploy(1,100,3,2)),
                                    (encode_mine_deployed,decode_mine_deployed,MineDeployed(1,3,2,321))):
            for packet in (encode(value)[:-1],encode(value)+b'\0'):
                with self.assertRaises(ValueError):decode(packet)

    def test_deployment_spends_once_and_rejects_replayed_instance(self):
        replies=self.plant()
        self.assertEqual(decode_mine_deployed(replies[0]),MineDeployed(1,3,2,321,1))
        self.assertEqual((self.field.actor(1).action_points,len(self.combat.mines)),(32,1))
        self.assertFalse(decode_item_list(self.combat.inventories[1])[1])
        before=(dict(self.field._actors),dict(self.combat.mines))
        with self.assertRaises(ValueError):self.arena.mine_action(7,encode_mine_deploy(MineDeploy(1,100,2,3)))
        self.assertEqual((dict(self.field._actors),dict(self.combat.mines)),before)

    def test_deployment_rejects_foreign_turn_owned_id_and_invalid_cells_atomically(self):
        for turn,request in (((8,{1},20),MineDeploy(1,100,3,2)),((7,{2},20),MineDeploy(1,100,3,2)),
            ((7,{1},10),MineDeploy(1,100,3,2)),((7,{1},20),MineDeploy(2,100,5,2)),
            ((7,{1},20),MineDeploy(1,100,2,2)),((7,{1},20),MineDeploy(1,100,6,2)),
            ((7,{1},20),MineDeploy(1,100,14,2))):
            self.prepare();self.arena._turns={1:turn};before=(dict(self.field._actors),dict(self.combat.inventories))
            with self.assertRaises(ValueError):self.arena.mine_action(7,encode_mine_deploy(request))
            self.assertEqual((self.field._actors,self.combat.inventories),before);self.assertFalse(self.combat.mines)

    def test_hidden_mine_stops_full_path_explodes_once_and_hits_both_sides(self):
        self.plant();replies=self.move_enemy()
        self.assertEqual(decode_battle_move(replies[0]).path,((5,2),(4,2),(3,2)))
        self.assertEqual((self.field.actor(2).x,self.field.actor(2).y,self.field.actor(2).action_points),(3,2,37))
        self.assertEqual({h.actor_id for h in decode_attack_result(replies[1]).hits},{1,2})
        self.assertEqual((self.field.actor(1).health,self.field.actor(2).health),(120,120))
        self.assertEqual(self.combat.statistics[7]['damage_dealt'],80)
        before=(dict(self.field._actors),dict(self.combat.statistics));self.assertEqual(self.combat.after_move(2),())
        self.assertEqual((self.field._actors,self.combat.statistics),before);self.assertFalse(self.combat.mines)

    def test_mine_disclosure_only_planting_coalition(self):
        self.prepare(teams={7:0,8:1,9:0});self.arena.mine_action(7,encode_mine_deploy(MineDeploy(1,100,3,2)))
        for owner,count in ((7,1),(8,0),(9,1)):
            self.assertEqual(len(decode_known_mines(self.combat.hazard_packets(owner)[0])),count)

    def test_mine_and_rng_restore_without_resupply_or_damage_replay(self):
        self.plant();self.combat.rng=random.Random(124)
        text=battle_snapshot.dumps(self.field,clock=lambda:10,wall=lambda:1000)
        restored,_=battle_snapshot.loads(text,clock=lambda:20,wall=lambda:1010)
        self.assertIs(restored.combat.field,restored);self.assertEqual(restored.combat.mines,self.combat.mines)
        self.field=restored;self.combat=restored.combat;self.arena._fields[1]=restored
        self.assertEqual(len(self.move_enemy()),2)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertFalse(restored.combat.mines);self.assertEqual(restored.combat.after_move(2),())
        self.assertFalse(decode_item_list(restored.combat.inventories[1])[1])

    def test_two_account_inventory_cas_and_stale_deploy_are_atomic(self):
        self.prepare()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shared.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                db.executemany('INSERT INTO owned_pets VALUES (?,?,?)',[('alice',1,self.combat.inventories[1]),
                    ('bob',1,encode_item_list(1,()))])
            self.combat.persistence[1]=(path,'alice');self.combat.persistence[2]=(path,'bob');self.combat.storage_ids[2]=1
            self.arena.mine_action(7,encode_mine_deploy(MineDeploy(1,100,3,2)))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='alice'").fetchone()[0],self.combat.inventories[1])
                self.assertEqual(db.execute("SELECT inventory_packet FROM owned_pets WHERE account='bob'").fetchone()[0],encode_item_list(1,()))
            self.prepare()
            self.combat.persistence[1]=(path,'alice');before=(dict(self.field._actors),dict(self.combat.inventories))
            with self.assertRaisesRegex(ValueError,'outside battle'):self.arena.mine_action(7,encode_mine_deploy(MineDeploy(1,100,3,2)))
            self.assertEqual((self.field._actors,self.combat.inventories),before);self.assertFalse(self.combat.mines)

    def test_movement_inventory_failure_rolls_back_position_and_keeps_mine(self):
        self.plant();before=dict(self.field._actors)
        with patch.object(self.combat,'_persist_batch',side_effect=sqlite3.OperationalError('Injected write failure')):
            with self.assertRaises(sqlite3.OperationalError):self.move_enemy()
        self.assertEqual(self.field._actors,before);self.assertEqual(len(self.combat.mines),1)

    def test_molotov_spends_throwable_and_floor_fire_ticks_once_and_restores(self):
        self.prepare(319);replies=self.combat.attack(7,AttackRequest(1,6,2))
        self.assertEqual(decode_attack_result(replies[0]).weapon_id,319)
        self.assertFalse(decode_item_list(self.combat.inventories[1])[1])
        self.assertFalse(self.combat.burns)
        self.assertEqual(len(self.combat.item_effects['fires']),1)
        old=self.field.actor(2).health
        self.assertEqual(self.combat.turn_effects(8,(2,)),())
        self.field.prepare_turn(8,(2,));self.combat.turn_effects(8,(2,))
        self.assertEqual(self.field.actor(2).health,old-10);self.assertEqual(self.combat.turn_effects(8,(2,)),())
        self.combat.rng=random.Random(7);restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertEqual(len(restored.combat.item_effects['fires']),1)
        self.assertEqual(restored.combat.turn_effects(8,(2,)),())
        for _ in range(2):restored.prepare_turn(8,(2,));restored.combat.turn_effects(8,(2,))
        self.assertFalse(restored.combat.item_effects['fires']);self.assertEqual(restored.actor(2).health,old-20)

    def test_flamethrower_uses_native_durability_reservoir_and_no_infinite_burn(self):
        self.prepare(324);self.combat.attack(7,AttackRequest(1,6,2))
        self.assertEqual(self.field.actor(1).action_points,31)
        weapon=decode_item_list(self.combat.inventories[1])[1][0];self.assertEqual(weapon.unknown_words[0],291)
        self.assertEqual(self.combat.burns[2].remaining,2)
        self.combat.inventories[1]=encode_item_list(1,(replace(weapon,unknown_words=(8,300,300)),))
        before=(dict(self.field._actors),dict(self.combat.inventories))
        with self.assertRaisesRegex(ValueError,'топлива'):self.combat.attack(7,AttackRequest(1,6,2))
        self.assertEqual((self.field._actors,self.combat.inventories),before)
        self.combat.inventories[1]=encode_item_list(1,(replace(weapon,unknown_words=(0,300,300)),))
        before=(dict(self.field._actors),dict(self.combat.inventories))
        with self.assertRaisesRegex(ValueError,'оружие'):self.combat.attack(7,AttackRequest(1,6,2))
        self.assertEqual((self.field._actors,self.combat.inventories),before)

    def test_grenade_launcher_spends_frag_ammo_and_keeps_launcher(self):
        self.prepare(323);self.combat.register(1,encode_item_list(1,(item(100,323,equipped=True),item(101,317))),human=True)
        replies=self.combat.attack(7,AttackRequest(1,6,2));self.assertEqual(decode_attack_result(replies[0]).weapon_id,323)
        self.assertEqual([i.template_id for i in decode_item_list(self.combat.inventories[1])[1]],[323])
        self.assertEqual(self.field.actor(1).action_points,31)

    def test_legacy_combat_snapshot_gets_empty_hazard_state(self):
        self.prepare();self.combat.rng=random.Random(0)
        for key in ('mines','burns','mine_sequence','hazard_damage'):delattr(self.combat,key)
        restored,_=battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertEqual((restored.combat.mines,restored.combat.burns,restored.combat.mine_sequence),({},{},1))
        self.assertEqual(restored.combat.hazard_damage,{})

    def test_new_items_are_purchasable_without_free_server_supplies(self):
        from tio.city_catalogs import CityCatalogs
        from tio.shop import ShopStore
        from tio.protocol.shop_purchase import ShopPurchase
        import test_shared_team_arena as fixture
        case=fixture.SharedTeamTests();case.setUp();self.addCleanup(case.doCleanups)
        catalogs=CityCatalogs(ROOT/'config/city_catalogs.json');shop=ShopStore(case.path,catalogs)
        with closing(sqlite3.connect(case.path)) as db,db:db.execute("UPDATE wallets SET credits=10000 WHERE account='alice'")
        for template in (319,321,323,324,325):
            offer=next(o for o in catalogs.items[0] if o.item_id==template)
            result=shop.purchase('alice',ShopPurchase(1,0,offer.unknown_u32_01,1))
            self.assertEqual(result.charged_credits,offer.unknown_u32_03)
        self.assertTrue({319,321,323,324,325}.issubset({i.template_id for i in decode_item_list(result.inventory)[1]}))


if __name__=='__main__':unittest.main()
