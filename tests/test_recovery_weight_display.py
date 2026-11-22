"""Native health/profile refreshes must end with authoritative weight values."""
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest

import test_multi_account as fixtures
from tio.db_transaction import transaction
from tio.battle_recovery import save_wounds
from tio.owned_pets import OwnedPetStore
from tio.protocol.health import encode_health
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.weight import city_profile_weight_update, city_weight_update, encode_weight


class RecoveryWeightTcpTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.MultiAccountTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        root = Path(__file__).resolve().parents[1]
        raw = bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        pet = decode_pet_info(raw, human_equipment=True)
        raw = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4b6d': 0}))
        for name, count in (('alice', 57), ('bob', 13)):
            ammo = ItemRecord(500, 3, bytes(2), count, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
            OwnedPetStore(self.case.config.database).ensure(
                name, raw, encode_item_list(1, (ammo,)), human=True)
            other = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c43eb': 2,
                                                        '0x8c44a6': 2}))
            OwnedPetStore(self.case.config.database).ensure(
                name, other, encode_item_list(2, ()), human=True)
        self.case.start()
        self.peers = {}
        self.now = [1000.]
        for name in ('alice', 'bob'):
            peer = self.case.handoff(self.case.begin(name))
            self.case.enter(peer, name.title())
            session = self.case.server.multi.active_accounts[name]
            session.recovery.clock = lambda: self.now[0]
            with transaction(self.case.config.database) as db:
                save_wounds(db, name, {1: 50})
            session.recovery.refresh(name)
            self.case.exchange_inventory_requests(peer, [])
            self.peers[name] = peer

    def recovery_packets(self, name, hp):
        rows = []
        for _ in range(8):
            rows.extend(self.case.exchange_inventory_requests(self.peers[name], []))
            if encode_health(1, hp) in rows:
                return rows
        self.fail('Missing passive recovery update')

    def test_healing_keeps_both_accounts_weight_stable_for_three_ticks(self):
        for hp in (51, 52, 53):
            self.now[0] += 10
            for name, weight in (('alice', 57), ('bob', 13)):
                replies = self.recovery_packets(name, hp)
                self.assertFalse(any(p[:1] == b'\x66' for p in replies))
                self.assertTrue(all(p == encode_weight(1, weight) for p in replies
                                    if p[:13] == encode_weight(1, weight)[:13]))

    def test_healing_after_inventory_change_uses_new_weight(self):
        with transaction(self.case.config.database) as db:
            ammo = ItemRecord(500, 3, bytes(2), 21, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1, (ammo,)), 'alice'))
        self.now[0] += 10
        replies = self.recovery_packets('alice', 51)
        self.assertFalse(any(p[:1] == b'\x66' for p in replies))
        # Inventory reads report the new weight independently of the HP tick.
        read = self.case.exchange_inventory_requests(self.peers['alice'], [b'\x2f\x01\0\x01\0\0\0'])
        self.assertIn(encode_weight(1, 21), (*replies, *read))


class CityProfileWeightTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'players.db'
        root = Path(__file__).resolve().parents[1]
        self.pet = bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        ammo = ItemRecord(500, 3, bytes(2), 70000, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
        for name, items in (('alice', (ammo,)), ('bob', ())):
            OwnedPetStore(self.path).ensure(name, self.pet, encode_item_list(1, items), human=True)

    def test_absolute_update_preserves_weight_above_petinfo_word_limit(self):
        self.assertEqual(city_profile_weight_update(self.path, 'alice', self.pet),
                         encode_weight(1, 70000))

    def test_same_pet_id_in_other_account_has_its_own_weight(self):
        self.assertEqual(city_profile_weight_update(self.path, 'bob', self.pet),
                         encode_weight(1, 0))

    def test_unknown_pet_does_not_fabricate_a_zero_weight_update(self):
        foreign = self.pet[:1]+(999).to_bytes(4, 'little')+self.pet[5:]
        self.assertIsNone(city_profile_weight_update(self.path, 'alice', foreign))

    def test_repeated_projection_uses_saved_capacity_and_never_writes_stats(self):
        packet = decode_pet_info(self.pet, human_equipment=True)
        projected = encode_pet_info(replace(packet, fields={**packet.fields, '0x8c4b57': 6000}))
        with transaction(self.path) as db:
            before = db.execute('SELECT * FROM owned_pets ORDER BY account,pet_id').fetchall()
            for _ in range(3):
                self.assertEqual(city_profile_weight_update(self.path, 'alice', projected),
                                 encode_weight(1, 70000))
            self.assertEqual(db.execute('SELECT * FROM owned_pets ORDER BY account,pet_id').fetchall(), before)

    def test_empty_squadmate_refresh_cannot_repaint_selected_fighters_weight(self):
        # Native status7 redraws the global city/selection scale even for a
        # nonselected fighter. Status6 has the required selection check.
        pet = decode_pet_info(self.pet, human_equipment=True)
        other = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c43eb': 2,
                                                    '0x8c44a6': 2}))
        empty = encode_item_list(2, ())
        OwnedPetStore(self.path).ensure('alice', other, empty, human=True)
        expected = struct.pack('<BIIIIB', 0x4e, 2, 1, 6, 0, 0)
        self.assertEqual(city_profile_weight_update(self.path, 'alice', other), expected)
        self.assertEqual(city_weight_update(self.path, 'alice', empty), expected)


if __name__ == '__main__':
    unittest.main()
