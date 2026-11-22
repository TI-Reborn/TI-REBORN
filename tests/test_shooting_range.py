from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tio.shooting_range import AdmissionRejected,AdmissionStore,ShootingRangeService,CREATE_REQUEST,POLICY
from tio.wallets import WalletStore
from tio.locations import LocationStore,SHOOTING_RANGE,center,town_at
from tio.arena_service import ArenaService
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from tio.protocol.pet_info import decode_pet_info
from tio.weapon_proficiency import SAVED,number

ROOT=Path(__file__).resolve().parents[1]


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'test.db';self.now=[864000]
        self.store=AdmissionStore(self.path,clock=lambda:self.now[0])

    def test_daily_token_does_not_accumulate_and_survives_restart(self):
        self.assertEqual(self.store.assets('alice').slug,1)
        self.store.pay('alice',0,'one');self.store.pay('alice',0,'one')
        self.assertEqual(self.store.assets('alice').slug,0)
        with self.assertRaises(ValueError):self.store.pay('alice',0,'two')
        restored=AdmissionStore(self.path,clock=lambda:self.now[0])
        self.assertEqual(restored.assets('alice').slug,0)
        self.now[0]+=10*86400
        self.assertEqual(restored.assets('alice').slug,1)
        restored.pay('alice',0,'two')
        self.assertEqual(restored.assets('alice').slug,0)

    def test_payment_limits_atomicity_and_all_four_modes(self):
        fund_wallet(self.path, 'alice', credits=100_000, gold=10_000)
        self.assertEqual(self.store.quote('alice'), (bytes((1, 0, 1, 1)), 1000, 15_000))
        with self.assertRaises(AdmissionRejected):
            self.store.pay('alice', 1, 'no-token')
        for tariff in (2, 3):
            for number in range(4):
                self.store.pay('alice', tariff, f'{tariff}-{number}')
            self.store.pay('alice', tariff, f'{tariff}-3')
            with self.assertRaisesRegex(AdmissionRejected, 'дневной лимит'):
                self.store.pay('alice', tariff, f'{tariff}-fifth')
            self.assertEqual(self.store.quote('alice')[0][tariff], 0)
        assets = self.store.assets('alice')
        self.assertEqual((assets.credits, assets.gold), (36_000, 10_000))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT payment,price,COUNT(*) FROM range_visits GROUP BY payment,price').fetchall(),
                             [(2, 1000, 4), (3, 15_000, 4)])
            db.execute("UPDATE range_accounts SET golden=1 WHERE account='alice'")
        self.store.pay('alice', 0, 'daily')
        self.store.pay('alice', 1, 'golden')
        restored = AdmissionStore(self.path, clock=lambda: self.now[0])
        self.assertEqual(restored.quote('alice')[0], bytes(4))
        self.now[0] += 86400
        self.assertEqual(restored.quote('alice')[0], bytes((1, 0, 1, 1)))
        for tariff in (2, 3):
            restored.pay('alice', tariff, f'{tariff}-tomorrow')

    def test_additional_tariff_requires_credits_and_counts_only_successful_entries(self):
        fund_wallet(self.path, 'alice', credits=14_999, gold=50_000)
        self.assertEqual(self.store.quote('alice')[0][3], 0)
        with self.assertRaisesRegex(AdmissionRejected, 'недостаточно средств'):
            self.store.pay('alice', 3, 'poor')
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM range_visits').fetchone(), (0,))
            db.execute("UPDATE wallets SET credits=15000 WHERE account='alice'")
        self.assertEqual(self.store.quote('alice')[0][3], 1)
        self.store.pay('alice', 3, 'exact')
        assets = self.store.assets('alice')
        self.assertEqual((assets.credits, assets.gold), (0, 50_000))

    def test_concurrent_additional_entries_share_the_last_daily_slot(self):
        from concurrent.futures import ThreadPoolExecutor

        fund_wallet(self.path, 'alice', credits=100_000, gold=0)
        for number in range(3):
            self.store.pay('alice', 3, str(number))

        def buy(visit):
            try:
                self.store.pay('alice', 3, visit)
            except AdmissionRejected as error:
                self.assertIn('дневной лимит', str(error))
                return False
            return True

        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(sum(pool.map(buy, ('a', 'b'))), 1)
        self.assertEqual(self.store.assets('alice').credits, 40_000)

    def test_parallel_free_entries_charge_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        def attempt(i):
            try:self.store.pay('alice',0,str(i));return True
            except ValueError:return False
        with ThreadPoolExecutor(2) as pool:self.assertEqual(sum(pool.map(attempt,range(2))),1)


class RangeTests(unittest.TestCase):
    def setUp(self):
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        from tio.squad import SquadStore
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'test.db';self.now=[100.0]
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        HireStore(self.path,CityCatalogs(ROOT/'config/city_catalogs.json'),template).hire('alice',1)
        self.identity=OwnedPetStore(self.path).list('alice')[0][0]
        SquadStore(self.path).assign('alice',self.identity,1)
        def item(i,t,n,e=False):return ItemRecord(i,t,bytes(2),n,int(e),16 if e else 0,(300,300,300),bytes(4),None,bytes(3))
        inventory=encode_item_list(self.identity,(item(500,301,1,True),item(501,3,40)))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',(inventory,))
        self.locations=LocationStore(self.path,clock=lambda:self.now[0])
        self.arena=ArenaService(clock=lambda:self.now[0])
        self.service=ShootingRangeService(self.path,self.arena,self.locations,clock=lambda:self.now[0])
        with closing(sqlite3.connect(self.path)) as db,db:
            self.locations._save(db,'alice',SHOOTING_RANGE,*center(SHOOTING_RANGE))

    def start(self,payment=0):
        self.service.handle('alice',42,b'Alice',CREATE_REQUEST)
        (self.room,self.scene),packets=self.service.handle('alice',42,b'Alice',bytes((0x2e,payment)))
        self.field=self.scene.field
        self.assertEqual(packets[-1],b'\x41')
        self.arena.member_loaded(42,b'\x36')
        self.arena.begin_turn_packets(42,self.scene.actor_ids,60)

    def test_native_lobby_malformed_remote_and_repeat_requests(self):
        from tio.protocol.arena import decode_battle_settings_body,decode_room_start
        self.assertEqual(decode_room_start(b'\x2e\2',mode=16),2)
        _,packets=self.service.handle('alice',42,b'Alice',CREATE_REQUEST)
        settings=decode_battle_settings_body(packets[0][1:])
        self.assertEqual((settings.mode,settings.players_count),(16,1))
        self.assertEqual(settings.mode16_extra,(bytes((1,0,1,0)),1000,15000))
        with self.assertRaises(ValueError):self.service.handle('alice',42,b'Alice',CREATE_REQUEST+b'\0')
        with self.assertRaises(ValueError):self.service.handle('alice',42,b'Alice',CREATE_REQUEST,searching=True)
        with self.assertRaises(ValueError):self.service.handle('alice',42,b'Alice',b'\x2e\4')
        self.start()
        self.assertEqual(self.service.handle('alice',42,b'Alice',b'\x2e\0'),(None,()))
        self.assertEqual(self.service.admission.assets('alice').slug,0)

    def test_prepare_failure_keeps_funds_and_lobby(self):
        self.service.handle('alice',42,b'Alice',CREATE_REQUEST)
        with patch('tools.shooting_range_scene.prepare_range',side_effect=ValueError('bad map')):
            with self.assertRaises(ValueError):self.service.handle('alice',42,b'Alice',b'\x2e\0')
        self.assertEqual(self.service.admission.assets('alice').slug,1)
        self.assertFalse(self.arena._loading)
        with closing(sqlite3.connect(self.path)) as db,db:self.locations._save(db,'alice',3,*center(3))
        with self.assertRaises(ValueError):self.service.handle('alice',42,b'Alice',b'\x2e\0')

    def test_native_payment_mapping_and_nonhuman_target_health(self):
        self.start(payment=1)
        self.assertEqual(self.service.admission.assets('alice').credits,8900)
        self.assertEqual(self.service.admission.assets('alice').gold,10000)
        from tio.protocol.battle_soldier import decode_battle_soldier
        target=min(self.field.practice.targets)
        self.assertEqual(self.scene.visibility.templates[target].human_equipment,'target')
        packets=[p for p in self.scene.packets if p[0]==0x3b and int.from_bytes(p[1:5],'little')==target]
        fields=decode_battle_soldier(packets[0],human_equipment='target').fields
        self.assertEqual((fields['0x8c566a'],fields['0x8c57bb']),(200,200))

    def test_native_fourth_payment_starts_battle_for_15000_credits(self):
        from tio.protocol.arena import decode_battle_settings_body

        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET credits=15000 WHERE account='alice'")
        _, packets = self.service.handle('alice', 42, b'Alice', CREATE_REQUEST)
        settings = decode_battle_settings_body(packets[0][1:])
        self.assertEqual(settings.mode16_extra, (bytes((1, 0, 1, 1)), 1000, 15_000))
        self.start(payment=2)
        self.assertEqual(self.service.handle('alice', 42, b'Alice', b'\x2e\2'), (None, ()))
        assets = self.service.admission.assets('alice')
        self.assertEqual((assets.credits, assets.gold, assets.slug), (0, 10_000, 1))

    def test_real_shot_persists_ammo_and_skill_without_xp_or_rank_rewards(self):
        self.start();combat=self.field.combat
        class Fixed:
            def randrange(self,n):return 0
            def randint(self,a,b):return a
        combat.rng=Fixed()
        target=self.field.actor(min(self.field.practice.targets))
        # Move to an unobstructed point on the original central range lane.
        self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=20,y=26)
        self.scene.visibility.refresh()
        before=OwnedPetStore(self.path).list('alice')[0][1:]
        replies=self.arena.attack(42,encode_attack_request(AttackRequest(self.identity,target.x,target.y)),view=self.scene.visibility)
        after=OwnedPetStore(self.path).list('alice')[0][1:]
        f1=decode_pet_info(before[0],human_equipment=True).fields
        f2=decode_pet_info(after[0],human_equipment=True).fields
        self.assertGreater(number(f2[SAVED[1]]),number(f1[SAVED[1]]))
        self.assertLess(decode_item_list(after[1])[1][1].count,40)
        self.assertFalse(combat.rank_kills)
        self.assertLess(self.field.actor(target.actor_id).health,target.health)
        money=WalletStore(self.path).ensure('alice')
        self.now[0]+=POLICY['session_seconds']+1
        result=self.arena.finish_training(42,self.path,'alice')
        self.assertEqual(result[-1][0],0x4c)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,money.credits)
        self.assertFalse(self.arena.finish_training(42,self.path,'alice'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='battle_rewards'").fetchone())
        self.assertIn(SHOOTING_RANGE.to_bytes(4,'little'),self.arena.finish_results(42,b'\x2a\1')[1])

    def test_weapon_attacks_keep_remaining_ap_in_the_same_turn(self):
        from tio.protocol.action_points import encode_action_points
        from tio.protocol.battle_attack import decode_attack_result

        request = self.start_with_worn_weapon()
        initial_ap = self.field.actor(self.identity).action_points
        turn = self.arena._turns[self.room.room_id]
        weapon = self.field.combat.catalog.weapons[301]
        for remaining_ap in (initial_ap,) * (initial_ap // weapon.attack_ap + 1) + (0,):
            with self.subTest(remaining_ap=remaining_ap):
                self.field._actors[self.identity] = replace(
                    self.field.actor(self.identity), action_points=remaining_ap)
                replies = self.arena.attack(42, request, view=self.scene.visibility)
                result = decode_attack_result(next(packet for packet in replies if packet[:1] == b'\x4b'))
                self.assertEqual(result.weapon_id, 301)
                self.assertIn(encode_action_points(self.identity, remaining_ap), replies)
                self.assertEqual(self.field.actor(self.identity).action_points, remaining_ap)
                self.assertEqual(self.arena._turns[self.room.room_id], turn)

    def test_rifle_still_requires_ap_outside_practice(self):
        request = self.start_with_worn_weapon()
        del self.field.practice
        self.field._actors[self.identity] = replace(
            self.field.actor(self.identity), action_points=0)
        with self.assertRaisesRegex(ValueError, 'Insufficient action points'):
            self.arena.attack(42, request, view=self.scene.visibility)

    def test_groza_active_ability_still_requires_ap_in_practice(self):
        from tio.protocol.ability_cast import AbilityCast, encode_ability_cast
        from test_combat import item

        inventory = encode_item_list(self.identity, (item(500, 339, equipped=True), item(501, 340)))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=?', (inventory,))
        self.start()
        self.field._actors[self.identity] = replace(
            self.field.actor(self.identity), action_points=0)
        request = encode_ability_cast(AbilityCast(27, self.identity, 0, 20, 25))
        with self.assertRaisesRegex(ValueError, 'Insufficient action points'):
            self.arena.cast_ability(42, request, view=self.scene.visibility)

    def test_smoke_grenade_and_land_mine_can_be_used_at_zero_ap(self):
        from tio.protocol.action_points import encode_action_points
        from test_combat import item

        self.start()
        combat = self.field.combat
        zero_ap = encode_action_points(self.identity, 0)
        self.field._actors[self.identity] = replace(
            self.field.actor(self.identity), action_points=0)
        for template in (318, 321):
            with self.subTest(template=template):
                inventory = encode_item_list(self.identity, (item(502, template, equipped=True),))
                with closing(sqlite3.connect(self.path)) as db, db:
                    db.execute('UPDATE owned_pets SET inventory_packet=?', (inventory,))
                combat.register(self.identity, inventory, human=True)
                request = encode_attack_request(AttackRequest(self.identity, 22, 31))
                replies = self.arena.attack(42, request, view=self.scene.visibility)
                self.assertIn(zero_ap, replies)
                self.assertFalse(decode_item_list(combat.inventories[self.identity])[1])

    def start_with_worn_weapon(self, *, with_kit=False):
        from test_combat import FixedRandom

        inventory = OwnedPetStore(self.path).list('alice')[0][2]
        _, (weapon, ammo), flag = decode_item_list(inventory)
        items = [replace(weapon, unknown_words=(1, 300, 300)), ammo]
        if with_kit:
            items.append(replace(weapon, instance_id=502, template_id=17, unknown_u8_01=0,
                                 location_raw=0, unknown_words=(600, 600, 600)))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=?', (encode_item_list(self.identity, items, flag),))
        self.start()
        self.field.combat.rng = FixedRandom()
        target = self.field.actor(min(self.field.practice.targets))
        self.field._actors[self.identity] = replace(self.field.actor(self.identity), x=20, y=26)
        self.scene.visibility.refresh()
        return encode_attack_request(AttackRequest(self.identity, target.x, target.y))

    def test_weapon_fires_at_zero_then_disappears_after_results(self):
        from random import Random
        from tio import battle_snapshot
        from tio.protocol.battle_attack import decode_attack_result

        request = self.start_with_worn_weapon()
        for shot in range(2):
            replies = self.arena.attack(42, request, view=self.scene.visibility)
            result = decode_attack_result(next(packet for packet in replies if packet[0] == 0x4b))
            self.assertEqual(result.weapon_id, 301)
            _, items, _ = decode_item_list(self.field.combat.inventories[self.identity])
            weapon = next(i for i in items if i.instance_id == 500)
            self.assertEqual((weapon.unknown_words[0], weapon.equipped), (0, 1))
            visible = decode_item_list(next(packet for packet in replies if packet[0] == 0x30))[1]
            self.assertEqual(next(i.unknown_words[0] for i in visible if i.instance_id == 500), 1)
            if shot == 0:
                self.field.combat.rng = Random(0)
                clock = lambda: self.now[0]
                snapshot = battle_snapshot.dumps(self.arena, clock=clock, wall=clock)
                self.arena, _ = battle_snapshot.loads(snapshot, clock=clock, wall=clock)
                self.field = self.arena._fields[self.room.room_id]
                self.scene = replace(self.scene, visibility=self.field.result_view)

        self.now[0] = self.field.practice.deadline
        self.assertEqual(self.arena.finish_training(42, self.path, 'alice')[-1][0], 0x4c)
        self.arena.finish_results(42, b'\x2a\1')
        saved = decode_item_list(OwnedPetStore(self.path).list('alice')[0][2])[1]
        self.assertNotIn(500, {i.instance_id for i in saved})
        self.assertLess(next(i.count for i in saved if i.instance_id == 501), 40)

    def test_repaired_zero_durability_weapon_survives_exit(self):
        from struct import pack

        request = self.start_with_worn_weapon(with_kit=True)
        self.arena.attack(42, request, view=self.scene.visibility)
        self.arena.repair(42, b'\xc2\x03' + pack('<II', self.identity, 500))
        self.arena.disconnect(42)
        saved = decode_item_list(OwnedPetStore(self.path).list('alice')[0][2])[1]
        self.assertGreater(next(i.unknown_words[0] for i in saved if i.instance_id == 500), 0)

    def test_destroying_all_targets_keeps_sight_safe_for_native_client_and_reload(self):
        from test_combat import FixedRandom
        from tio.protocol.battle_soldier import decode_battle_soldier
        self.start();self.field.combat.rng=FixedRandom()
        for target_id in sorted(self.field.practice.targets):
            target=self.field.actor(target_id)
            self.field._actors[target_id]=replace(target,health=1)
            self.field._actors[self.identity]=replace(self.field.actor(self.identity),x=target.x,y=target.y+1)
            self.field.prepare_turn(42,(self.identity,))
            self.field.combat.attack(42,AttackRequest(self.identity,target.x,target.y),view=self.scene.visibility)
            self.assertLessEqual(self.field.actor(self.identity).sight_radius,15)
        self.assertEqual(self.field.actor(self.identity).sight_radius,15)
        packet=self.scene.visibility.snapshot(self.identity)
        self.assertEqual(decode_battle_soldier(packet,human_equipment=True).fields['0x8c567f'],15)

    def test_targets_never_take_turns_and_exit_has_no_penalty(self):
        self.start()
        self.arena.end_turn(42,b'\x3a'+self.identity.to_bytes(4,'little'))
        self.assertEqual(self.arena.next_turn_owner(self.room.room_id),42)
        raw=OwnedPetStore(self.path).list('alice')[0][1:]
        self.arena.disconnect(42)
        self.assertEqual(OwnedPetStore(self.path).list('alice')[0][1:],raw)
        self.assertEqual(self.service.admission.assets('alice').slug,0)

    def test_world_entries_and_client_catalog_agree(self):
        import xml.etree.ElementTree as ET
        from tio.locations import TOWNS
        tree=ET.parse(ROOT/'evidence/zones_diagnostic.xml')
        for identity,point in ((13,(-170,-274)),(16,(265,-160)),(17,(-12,-255))):
            self.assertEqual(center(identity),point)
            self.assertEqual(town_at(*point),identity)
            node=tree.find(f"town[@id='{identity}']")
            self.assertEqual(tuple(int(node.find(f"value[@key='{key}']").get('val')) for key in ('x1','y1','x2','y2')),TOWNS[identity])


if __name__=='__main__':unittest.main()

