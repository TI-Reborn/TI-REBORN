from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.equipment import EquipmentStore, EquipmentRejected, equip_primary_weapon, swap_city_weapons
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import decode_item_list, encode_item_list

ROOT = Path(__file__).resolve().parents[1]


class EquipmentTests(unittest.TestCase):
    def test_catalog_gun_and_grenade_can_be_equipped(self):
        for template in (303,317):
            owner,items,unknown=decode_item_list(self.inventory)
            inventory=encode_item_list(owner,(replace(items[0],template_id=template),),unknown)
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(inventory,'alice',owner))
            reply=equip_primary_weapon(self.path,'alice',encode_item_action(ItemAction(owner,items[0].instance_id,4)))
            equipped=decode_item_list(reply)[1][0]
            self.assertEqual((equipped.template_id,equipped.equipped,equipped.client_slot),(template,1,16))

    def test_untargeted_weapon_toggles_and_explicit_target_does_not(self):
        packet = encode_item_action(ItemAction(1,1001,255))
        equip_primary_weapon(self.path,'alice',packet)
        self.assertEqual(equip_primary_weapon(self.path,'alice',packet),self.inventory)
        explicit = encode_item_action(ItemAction(1,1001,4))
        result = equip_primary_weapon(self.path,'alice',explicit)
        self.assertEqual(equip_primary_weapon(self.path,'alice',explicit),result)

    def test_primary_request_and_unsupported_target(self):
        for option in (255, 4):
            result = equip_primary_weapon(self.path, 'alice', encode_item_action(ItemAction(1,1001,option)))
            self.assertEqual(decode_item_list(result)[1][0].slot, 16)
        result=equip_primary_weapon(self.path, 'alice', encode_item_action(ItemAction(1,1001,7)))
        self.assertEqual(decode_item_list(result)[1][0].slot,128)
        with self.assertRaises(EquipmentRejected):
            equip_primary_weapon(self.path, 'alice', encode_item_action(ItemAction(1,1001,6)))
        self.assertEqual(self.pets.inventory('alice',1), result)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'equipment.sqlite3'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        owner, items, unknown = decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))
        self.inventory = encode_item_list(owner, items+(replace(items[0], instance_id=1002),), unknown)
        self.pets = OwnedPetStore(self.path)
        self.pets.ensure('alice', self.pet, self.inventory, human=True)
        # Test policy only: this is not evidence of Beretta slot compatibility.
        self.store = EquipmentStore(self.path, {301: (0x10, 0x80)})

    def test_replace_unequip_and_reopen(self):
        self.store.assign('alice', 1, 1001, 0x10)
        result = self.store.assign('alice', 1, 1002, 0x10)
        items = decode_item_list(result)[1]
        self.assertEqual([(i.equipped, i.slot) for i in items], [(0, 0), (1, 0x10)])
        self.assertEqual(self.pets.ensure('alice', self.pet, self.inventory, human=True)[1], result)
        self.assertEqual(self.store.assign('alice', 1, 1002, None), self.inventory)

    def test_move_preserves_other_fields_and_is_idempotent(self):
        first = self.store.assign('alice', 1, 1001, 0x10)
        self.assertEqual(self.store.assign('alice', 1, 1001, 0x10), first)
        result = self.store.assign('alice', 1, 1001, 0x80)
        item = decode_item_list(result)[1][0]
        original = decode_item_list(self.inventory)[1][0]
        self.assertEqual(replace(item, unknown_u8_01=0, location_raw=0), original)

    def test_rejections_do_not_change_snapshot(self):
        for account, pet, item, slot in [('bob',1,1001,16),('alice',2,1001,16),
                                        ('alice',1,999,16),('alice',1,1001,1),('alice',1,1001,3)]:
            with self.assertRaises(EquipmentRejected):
                self.store.assign(account,pet,item,slot)
        self.assertEqual(self.pets.inventory('alice',1),self.inventory)

    def test_database_failure_rolls_back(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_equipment BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.assign('alice',1,1001,16)
        self.assertEqual(self.pets.inventory('alice',1),self.inventory)

    def test_city_swap_one_or_two_weapons_both_directions_preserves_records(self):
        packet=b'\x6d'+(1).to_bytes(4,'little')
        for slots in ((16,0),(128,0),(16,128),(0,0)):
            with self.subTest(slots=slots):
                for instance,slot in zip((1001,1002),slots):
                    self.store.assign('alice',1,instance,slot or None)
                before=self.pets.inventory('alice',1)
                result=swap_city_weapons(self.path,'alice',packet)
                expected=tuple(replace(i,location_raw={16:128,128:16}.get(i.slot,i.slot))
                               for i in decode_item_list(before)[1])
                self.assertEqual(decode_item_list(result)[1],expected)
                self.assertEqual(self.pets.inventory('alice',1),result)
                self.assertEqual(swap_city_weapons(self.path,'alice',packet),before)

    def test_city_swap_rejects_foreign_pet_and_bad_packets_without_changes(self):
        for account,packet in (('bob',b'\x6d\x01\0\0\0'),('alice',b'\x6d\x02\0\0\0'),
                               ('alice',b'\x6d\x01'),('alice',b'\x6d\x01\0\0\0\0')):
            with self.assertRaises(ValueError):swap_city_weapons(self.path,account,packet)
            self.assertEqual(self.pets.inventory('alice',1),self.inventory)
