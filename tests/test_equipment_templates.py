from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.equipment_templates import EquipmentTemplateStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.equipment_templates import Element, Template, decode_request, encode_view
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]


def command(action, identity, pet=1):
    return b'\xc5\x03' + bytes((action,)) + struct.pack('<I', identity) + (struct.pack('<I', pet) if action in (0, 4, 5) else b'')


def save(t, identity=0):
    data = command(1 if identity else 3, identity)
    data += t.name.encode('utf-16le') + b'\0\0' + bytes((t.level, t.npc_type, t.remove_extra))
    for n, e in enumerate(t.elements):
        if n == 7: data += bytes((len(t.elements) - 7,))
        if n in (0, 2, 4, 5, 6):
            data += struct.pack('<Ib', e.object_id, e.setting)
        else:
            data += struct.pack('<IIBb', e.item_id, e.count, e.damage, e.setting)
    if len(t.elements) == 7: data += b'\0'
    return data


class EquipmentTemplateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'templates.db'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.pet = bytes.fromhex(trial['packet_hex'])
        base = decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0]
        self.gun = replace(base, unknown_u8_01=0, location_raw=0)
        self.ammo = replace(self.gun, instance_id=1002, template_id=3, unknown_u32_01=50)
        self.extra = replace(self.gun, instance_id=1003, template_id=9, unknown_u32_01=5)
        self.pets = OwnedPetStore(self.path)
        self.pets.ensure('alice', self.pet, encode_item_list(1, (self.gun, self.ammo, self.extra)), human=True)
        self.store = EquipmentTemplateStore(self.path)
        self.t = Template('Полевой комплект', 1, 0, 1,
                          (Element(object_id=1001), Element(item_id=3, count=20), *[Element() for _ in range(5)]))

    def create(self, t=None):
        replies = self.store.handle('alice', save(t or self.t))
        self.assertEqual(replies[1][:2], b'\xc5\x06')
        return int.from_bytes(replies[1][2:], 'little')

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return tuple((name, tuple(db.execute('SELECT * FROM '+name))) for name in
                         ('owned_pets', 'warehouse_items', 'item_sequences', 'equipment_templates'))

    def test_empty_list_and_native_save_shape(self):
        self.assertEqual(self.store.handle('alice', b'\xc5\x01'), (b'\xc5\x02\0\0',))
        action, identity, owner, t = decode_request(save(self.t))
        self.assertEqual((action, identity, owner, t), (3, 0, 0, self.t))
        for packet in (save(self.t)[:-1], save(self.t)+b'\0', b'\xc5\x01\0', command(9, 1)):
            before = self.state()
            with self.assertRaises(ValueError): self.store.handle('alice', packet)
            self.assertEqual(self.state(), before)

    def test_create_view_unicode_and_restart(self):
        identity = self.create()
        replies = EquipmentTemplateStore(self.path).handle('alice', command(0, identity))
        name = self.t.name.encode('utf-8')
        self.assertEqual(replies[0][2:4], struct.pack('<H', len(name)))
        self.assertEqual(replies[0][4:4+len(name)], name)
        self.assertIn(self.t.name.encode('utf-16le'), self.store.handle('alice', b'\xc5\x01')[0])

    def test_apply_split_deposit_conservation_and_repeat(self):
        identity = self.create()
        reply = self.store.handle('alice', command(4, identity))
        items = decode_item_list(reply[0])[1]
        self.assertEqual([(i.template_id, i.count, i.client_slot) for i in items], [(301, 1, 16), (3, 20, 0)])
        stored = WarehouseStore(self.path).items('alice')
        self.assertEqual([(i.template_id, i.count) for i in stored], [(3, 30), (9, 5)])
        pet = decode_pet_info(reply[-1], human_equipment=True)
        self.assertEqual(pet.fields['0x8c4f74'], identity)
        self.assertEqual(pet.fields['0x8c4f9c'], self.t.name)
        before = self.state()
        self.store.handle('alice', command(4, identity))
        self.assertEqual(self.state(), before)

    def test_take_gear_and_supplies_from_warehouse(self):
        identity = self.create()
        WarehouseStore(self.path, capacity=3000).exchange('alice', 1, deposits=((1001, 1), (1002, 50)))
        self.store.handle('alice', command(4, identity))
        items = decode_item_list(self.pets.inventory('alice', 1))[1]
        self.assertEqual(sum(i.count for i in items if i.template_id == 3), 20)
        self.assertTrue(next(i for i in items if i.instance_id == 1001).equipped)

    def test_remove_extra_off_keeps_leftovers_in_backpack(self):
        identity = self.create(replace(self.t, remove_extra=0))
        self.store.handle('alice', command(4, identity))
        items = decode_item_list(self.pets.inventory('alice', 1))[1]
        self.assertEqual(sum(i.count for i in items if i.template_id == 3), 50)
        self.assertEqual(WarehouseStore(self.path).items('alice'), ())

    def test_update_rename_delete_and_disable(self):
        identity = self.create()
        self.store.handle('alice', command(4, identity))
        self.store.handle('alice', save(replace(self.t, name='Новый'), identity))
        pet = self.pets.list('alice')[0][1]
        self.assertEqual(decode_pet_info(pet, human_equipment=True).fields['0x8c4f9c'], 'Новый')
        inv = self.pets.inventory('alice', 1)
        self.store.handle('alice', command(4, 0))
        self.assertEqual(self.pets.inventory('alice', 1), inv)
        self.store.handle('alice', command(4, identity))
        replies = self.store.handle('alice', command(2, identity))
        self.assertEqual(replies[0], b'\xc5\x04'+struct.pack('<II', 1, 0))
        self.assertIn(b'\xc5\x02\0\0', replies)
        self.assertIn(b'\xc5\x06\0\0\0\0', replies)
        self.assertNotIn('0x8c4f9c', decode_pet_info(self.pets.list('alice')[0][1], human_equipment=True).fields)

    def test_action5_updates_current_from_recipient(self):
        identity = self.create()
        self.store.handle('alice', command(4, identity))
        self.store.handle('alice', command(5, identity))
        self.store.handle('alice', command(4, identity))
        self.assertEqual(sum(i.count for i in decode_item_list(self.pets.inventory('alice', 1))[1] if i.template_id == 3), 20)

    def test_insufficient_ammo_and_foreign_template_rollback(self):
        identity = self.create(replace(self.t, elements=(self.t.elements[0], Element(item_id=3, count=51), *self.t.elements[2:])))
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Недостаточно'): self.store.handle('alice', command(4, identity))
        self.assertEqual(self.state(), before)
        for action in (0, 1, 2, 4, 5):
            with self.assertRaises(ValueError): self.store.handle('bob', save(self.t, identity) if action == 1 else command(action, identity))
        self.assertEqual(self.state(), before)

    def test_type_level_slot_and_busy_rejections(self):
        for t in (replace(self.t, npc_type=1), replace(self.t, level=20)):
            identity = self.create(t)
            before = self.state()
            with self.assertRaises(ValueError): self.store.handle('alice', command(4, identity))
            self.assertEqual(self.state(), before)
        for packet in (save(self.t), command(4, identity), command(2, identity)):
            with self.assertRaises(ValueError): self.store.handle('alice', packet, allow_mutation=False)
        self.assertEqual(self.store.handle('alice', b'\xc5\x01', allow_mutation=False)[0][:2], b'\xc5\x02')
        with self.assertRaises(ValueError): self.create(replace(self.t, elements=(Element(), *self.t.elements[1:4], Element(object_id=1001), *self.t.elements[5:])))

    def test_capacity_failure_rolls_back_all(self):
        identity = self.create()
        before = self.state()
        self.store.capacity = 1
        with self.assertRaisesRegex(ValueError, 'места'): self.store.handle('alice', command(4, identity))
        self.assertEqual(self.state(), before)

    def test_sql_failure_rolls_back_all(self):
        identity = self.create()
        before = self.state()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.handle('alice', command(4, identity))
        self.assertEqual(self.state(), before)

    def test_rental_and_upgrade_metadata_preserved(self):
        identity = self.create()
        gun = replace(self.gun, unknown_bytes_02=b'\0\0\0\1', optional_u32=2000000000, unknown_bytes_03=b'\x02\0\0')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=?', (encode_item_list(1, (gun, self.ammo, self.extra)),))
        self.store.handle('alice', command(4, identity))
        after = next(i for i in decode_item_list(self.pets.inventory('alice', 1))[1] if i.instance_id == gun.instance_id)
        self.assertEqual(replace(after, unknown_u8_01=0, location_raw=0), gun)

    def test_wire_route_now_answers_list(self):
        from tools.audit_unanswered_requests import replay
        self.assertEqual(replay('c501'), ['c5020000'])

    def test_transport_create_apply_and_view(self):
        import contextlib, io
        from tools.loopback_exchange import LoopbackExchange
        from tools.audit_unanswered_requests import Wire
        from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame
        self.pets.ensure('probe_user',self.pet,encode_item_list(1,(self.gun,self.ammo,self.extra)),human=True)
        exchange = LoopbackExchange(self.path.parent/'events.json', database=self.path,
                                   open_town_probe=True, owned_pet_probe=True, observation_seconds=0)
        exchange.probe_character_id=1
        exchange.probe_character_name=b'ProbeNew'
        wire=Wire(b'\xc5\x01')
        cipher=InitialCipher('C2S')
        wire.frames=iter([encode_initial_frame(p,cipher) for p in
                         (save(self.t),command(4,1),command(0,1),b'\xc5\x01')]+[b''])
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exchange.observe_game(wire,InitialFrameReader(InitialCipher('C2S')),InitialCipher('S2C'))
        finally:
            exchange.stop();exchange.finish()
        self.assertFalse(any(p.startswith('f0') for p in wire.replies),wire.replies)
        self.assertEqual(sum(p.startswith('c508') for p in wire.replies),2)
        items=decode_item_list(self.pets.inventory('probe_user',1))[1]
        self.assertEqual([(i.template_id,i.count,i.client_slot) for i in items],[(301,1,16),(3,20,0)])

    def test_dog_and_miner_gear_profiles(self):
        from tio.protocol.pet_info import SCHEMAS, PetInfo
        for resource, human, kind, template in ((3, False, 1, 255), (6, True, 6, 258)):
            fields = dict(decode_pet_info(self.pet, human_equipment=True).fields)
            fields.update({'0x8c446f':resource, '0x8c4aef':5})
            fields = {k:fields.get(k, 0) for k,_,_ in SCHEMAS[(human, bool(fields['0x6d0203']), bool(fields['0x8c4565']))]}
            pet = encode_pet_info(PetInfo(human,fields))
            armor = replace(self.gun, template_id=template)
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE owned_pets SET human=?,pet_packet=?,inventory_packet=? WHERE account=?',
                           (int(human), pet, encode_item_list(1, (armor,)), 'alice'))
            t = Template('Броня', 5, kind, 1, (*[Element() for _ in range(5)], Element(object_id=1001), Element()))
            identity = self.create(t)
            reply = self.store.handle('alice', command(4,identity))
            self.assertEqual(decode_item_list(reply[0])[1][0].client_slot, 4)
            self.assertEqual(decode_pet_info(reply[-1], human_equipment=human).fields['0x8c4f74'], identity)

    def test_does_not_take_gear_from_another_mercenary(self):
        identity = self.create()
        pet = decode_pet_info(self.pet, human_equipment=True)
        other = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c43eb':2}))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=?', (encode_item_list(1, (self.ammo,self.extra)),))
        self.pets.ensure('alice', other, encode_item_list(2, (self.gun,)), human=True)
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'другого бойца'): self.store.handle('alice', command(4,identity))
        self.assertEqual(self.state(), before)

    def test_service_options_are_preserved_and_never_fake_repairs(self):
        t = replace(self.t,elements=(replace(self.t.elements[0],setting=2), *self.t.elements[1:]))
        identity = self.create(t)
        with closing(sqlite3.connect(self.path)) as db, db:
            gun = replace(self.gun, unknown_words=(1,100,100))
            db.execute('UPDATE owned_pets SET inventory_packet=?', (encode_item_list(1,(gun,self.ammo,self.extra)),))
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Ремонт'): self.store.handle('alice', command(4,identity))
        self.assertEqual(self.state(), before)


if __name__ == '__main__': unittest.main()
