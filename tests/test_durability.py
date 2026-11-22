from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3,struct,tempfile,unittest
from unittest.mock import patch
from test_combat import item,FixedRandom
from tio.durability import wear,wear_inventory,repair_item,repair_inventory
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.repair import decode_repair
from tio.protocol.battle_attack import AttackRequest
from tio.battle_state import BattleField,BattleActor
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.repair import repair,select_kit
from tio.protocol.item_action import ItemAction,encode_item_action


def gear(identity=100,template=301,words=(50,350,350),slot=0):
    return replace(item(identity,template,equipped=bool(slot)),unknown_words=words,location_raw=slot)


def kit(identity=101,resource=600):return gear(identity,17,(resource,600,600))
def request(owner=1,target=100,selected=False):return (b'\x7e' if selected else b'\xc2\x03')+struct.pack('<II',owner,target)


class DurabilityTests(unittest.TestCase):
    def test_selected_le_kit_preserves_weapon_and_armor_maximum(self):
        le_kit = gear(101, 128, (1000, 1000, 1000))
        weapon = gear(words=(50, 350, 400))
        armor = gear(template=208, words=(50, 1200, 1250))
        for target, expected, remaining in ((weapon, (350, 350, 400), 700),
                                            (armor, (1050, 1200, 1250), 0)):
            with self.subTest(template=target.template_id):
                packet = encode_item_list(1, (target, le_kit))
                with self.assertRaises(ValueError):
                    repair_inventory(packet, target.instance_id)
                updated, audit = repair_inventory(packet, target.instance_id, le_kit.instance_id)
                items = decode_item_list(updated)[1]
                self.assertEqual(items[0].unknown_words, expected)
                self.assertEqual(len(items), 2 if remaining else 1)
                self.assertEqual(items[1].unknown_words[0] if len(items) > 1 else 0, remaining)
                self.assertEqual((audit['spent'], audit['loss']), (1000 - remaining, 0))

    def test_manual_repair_example_and_large_deficit_percent_of_resource(self):
        fixed,left,spent,loss=repair_item(gear(),kit())
        self.assertEqual((fixed.unknown_words,left.unknown_words,spent,loss),((341,341,350),(309,600,600),291,9))
        fixed,left,spent,loss=repair_item(gear(words=(0,10000,10000)),kit(resource=3600))
        self.assertEqual((fixed.unknown_words,left,spent,loss),((3600,9892,10000),None,3600,108))

    def test_small_deficits_and_partial_resource_invariants(self):
        for deficit in range(1,450):
            for resource in (1,17,33,99,600):
                fixed,left,spent,loss=repair_item(gear(words=(500-deficit,500,500)),kit(resource=resource))
                self.assertLessEqual(fixed.unknown_words[0],fixed.unknown_words[1])
                self.assertEqual(fixed.unknown_words[2],500)
                self.assertEqual(resource-(left.unknown_words[0] if left else 0),spent)
                self.assertEqual(fixed.unknown_words[0]-(500-deficit),spent)
                self.assertLessEqual(abs(loss-spent*.03),1)

    def test_break_ordinary_destroyed_se_retained_unequipped_and_repairable(self):
        ordinary=gear(words=(3,300,300),slot=16)
        self.assertIsNone(wear(ordinary,3))
        special=replace(ordinary,unknown_bytes_03=b'\0\0\1')
        broken=wear(special,100)
        self.assertEqual((broken.unknown_words,broken.equipped,broken.slot),((0,300,300),0,0))
        self.assertGreater(repair_item(broken,kit())[0].unknown_words[0],0)
        self.assertEqual(wear(kit(),100),kit())
        self.assertEqual(wear(gear(template=300),100),gear(template=300))

    def test_each_equipped_armor_piece_wears_and_backpack_does_not(self):
        armor=[gear(10,208,(300,300,300),1),gear(11,210,(300,300,300),4),gear(12,220,(300,300,300),8),gear(13,210,(300,300,300))]
        result=decode_item_list(wear_inventory(encode_item_list(1,armor),armor_damage=99))[1]
        self.assertEqual([i.unknown_words[0] for i in result],[261,261,261,300])

    def test_invalid_repair_inputs(self):
        for target in (gear(words=(350,350,350)),gear(template=3),replace(gear(),optional_u32=4),gear(words=(0,0,350))):
            with self.assertRaises(ValueError):repair_item(target,kit())
        for tool in (kit(resource=0),gear(template=30),replace(kit(),unknown_u32_01=2)):
            with self.assertRaises(ValueError):repair_item(gear(),tool)
        for packet in (b'\x7e',request()+b'\0',request(owner=0),b'\xc2\x02'+bytes(8)):
            with self.assertRaises(ValueError):decode_repair(packet)

    def scene(self):
        f=BattleField(8,8,[BattleActor(1,7,1,1,15,100,100),BattleActor(2,8,2,1,15,2,100)],step_cost=1)
        f.combat=c=Combat(f,WeaponCatalog(),rng=FixedRandom())
        c.register(1,encode_item_list(1,(gear(words=(300,300,300),slot=16),item(102,3,50),kit())),human=True)
        c.register(2,encode_item_list(2,(gear(200,210,(300,300,300),4),)),human=True)
        return f,c

    def test_shot_miss_wears_weapon_and_overkill_wears_uncapped_armor(self):
        f,c=self.scene();c.attack(7,AttackRequest(1,2,1))
        w=decode_item_list(c.inventories[1])[1][0]
        self.assertEqual(w.unknown_words[0],300-c.catalog.weapons[301].attack_ap)
        self.assertEqual(f.actor(2).health,0)
        self.assertLess(decode_item_list(c.inventories[2])[1][0].unknown_words[0],299)
        f,c=self.scene();c.rng.randrange=lambda n:99
        old=c.inventories[2];c.attack(7,AttackRequest(1,2,1))
        self.assertEqual(c.inventories[2],old)
        self.assertLess(decode_item_list(c.inventories[1])[1][0].unknown_words[0],300)

    def test_two_account_cas_rolls_back_attacker_ammo_wear_and_hp(self):
        f,c=self.scene()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                for identity,name in ((1,'alice'),(2,'bob')):
                    db.execute('INSERT INTO owned_pets VALUES (?,?,?)',(name,identity,c.inventories[identity]))
                    c.persistence[identity]=(path,name)
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE pet_id=2',(encode_item_list(2,()),))
            old=(dict(c.inventories),dict(f._actors))
            with self.assertRaisesRegex(ValueError,'outside battle'):c.attack(7,AttackRequest(1,2,1))
            self.assertEqual((c.inventories,f._actors),old)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets WHERE pet_id=1').fetchone()[0],old[0][1])

    def test_battle_repair_cost_replay_and_insufficient_ap(self):
        f,c=self.scene();c.inventories[1]=encode_item_list(1,(gear(),kit()))
        c.repair_selections[7]=(1,101)
        f._actors[1]=replace(f.actor(1),action_points=0)
        old=c.inventories[1]
        with self.assertRaises(ValueError):c.repair(7,request(selected=True))
        self.assertEqual(c.inventories[1],old)
        f._actors[1]=replace(f.actor(1),action_points=3)
        packets=c.repair(7,request(selected=True))
        self.assertEqual(f.actor(1).action_points,2)
        self.assertEqual(packets[-1],b'\xf0'+struct.pack('<II',112,0))
        with self.assertRaises(ValueError):c.repair(7,request(selected=True))
        self.assertEqual(f.actor(1).action_points,2)

    def test_city_ownership_transaction_failure_and_reconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'state.db';initial=encode_item_list(1,(gear(),kit()))
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                db.execute('INSERT INTO owned_pets VALUES (?,?,?)',('alice',1,initial))
            with self.assertRaises(ValueError):repair(path,'bob',request())
            with self.assertRaises(ValueError):repair(path,'alice',request(selected=True))
            selection=select_kit(path,'alice',encode_item_action(ItemAction(1,101,255)))
            self.assertEqual(selection,(1,101))
            with patch('tio.repair.record',side_effect=sqlite3.OperationalError('write failed')):
                with self.assertRaises(sqlite3.OperationalError):repair(path,'alice',request(),selection)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets').fetchone()[0],initial)
            with patch('tio.achievements.update'):
                updated,_=repair(path,'alice',request(selected=True),selection)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets').fetchone()[0],updated)
                self.assertEqual(db.execute('SELECT spent,max_loss FROM item_repairs').fetchone(),(291,9))
            with self.assertRaises(ValueError):repair(path,'alice',request())

if __name__=='__main__':unittest.main()
