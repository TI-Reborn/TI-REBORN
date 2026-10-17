from wallet_fixture import fund_wallet
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tio.shooting_range import AdmissionStore,ShootingRangeService,CREATE_REQUEST,POLICY
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
        fund_wallet(self.path, 'alice', credits=10_000, gold=10_000)
        self.assertEqual(self.store.quote('alice')[0],bytes((1,0,1,1)))
        with self.assertRaises(ValueError):self.store.pay('alice',1,'no-token')
        for i in range(4):self.store.pay('alice',2,str(i))
        credits=self.store.assets('alice').credits
        with self.assertRaises(ValueError):self.store.pay('alice',2,'fifth')
        self.assertEqual(self.store.assets('alice').credits,credits)
        self.store.pay('alice',3,'gold');self.store.pay('alice',3,'gold')
        self.assertEqual(self.store.assets('alice').gold,10000-POLICY['gold_price'])
        with self.assertRaises(ValueError):self.store.pay('bob',3,'gold')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE range_accounts SET golden=2 WHERE account='alice'")
            db.execute("UPDATE wallets SET gold=0 WHERE account='alice'")
        self.store.pay('alice',1,'yellow')
        self.assertEqual(self.store.assets('alice').gold_slug,1)
        with self.assertRaises(ValueError):self.store.pay('alice',3,'poor')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM range_visits').fetchone()[0],6)
        self.now[0]+=86400;self.store.pay('alice',2,'tomorrow')

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
        self.assertEqual(settings.mode16_extra[0],bytes((1,0,1,1)))
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

