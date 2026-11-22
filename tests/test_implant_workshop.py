from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import sqlite3
import struct
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from xml.etree import ElementTree as ET
import zlib

import test_multi_account
from server.implant_service import catalogue_updates
from tio.ability_learning import AbilityLearning
from tio.implant_crafting import craft
from tio.implant_recipes import available_pairs
from tio.implants import SLOTS, policy, variant
from tio.owned_pets import OwnedPetStore
from tio.protocol.abilities import AbilityEntry
from tio.protocol.character_select import decode_character_list
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.shared_config import MAX_COMPRESSED_SIZE, decode_shared_config_data


ROOT = Path(__file__).resolve().parents[1]


def workshop_pet(owner: int) -> bytes:
    fixture = json.loads((ROOT / 'evidence/owned_pet_trial.json').read_text(encoding='utf-8'))
    pet = decode_pet_info(bytes.fromhex(fixture['packet_hex']), human_equipment=True)
    fields = {**pet.fields, '0x8c43eb': owner, '0x8c4aef': 7, '0x8c44a6': 0}
    return encode_pet_info(replace(pet, fields=fields))


def implant(identity: int, template: int, slot: int = 0, resource: int = 825) -> ItemRecord:
    return ItemRecord(identity, template, bytes(2), 1, int(bool(slot)), slot, (resource,) * 3,
                      bytes((5, 0, 0, 0)), None, bytes((5, 0, 0)))


def workshop_inventories(fighters: int) -> list[bytes]:
    rules = policy()
    templates = [variant(family, int(effect)) for family in rules['combo']['families']
                 for effect in rules['extra']['effects']]
    rng = Random(42)
    return [encode_item_list(owner, tuple(implant(owner * 100 + index, template)
                                          for index, template in enumerate(rng.sample(templates, 18), 1)))
            for owner in range(1, fighters + 1)]


class WorkshopTests(unittest.TestCase):
    def test_native_discard_removes_only_the_owners_installed_implant(self):
        game = test_multi_account.MultiAccountTests()
        game.setUp()
        self.addCleanup(game.doCleanups)
        game.start()
        store = OwnedPetStore(game.config.database)
        installed = implant(1001, 6101, SLOTS[0])
        loose = implant(1002, 6102)
        extractor = ItemRecord(1003, 6123, bytes(2), 1, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
        for owner in ('alice', 'bob'):
            store.ensure(owner, workshop_pet(1), encode_item_list(1, (installed, loose, extractor)), human=True)
        alice = game.handoff(game.begin('alice'))
        game.enter(alice, 'Alice')
        bob = game.handoff(game.begin('bob'))
        game.enter(bob, 'Bob')

        def discard(pet_id, identity, count=1):
            alice.send(b'\x32' + struct.pack('<III', pet_id, identity, count))
            game.ping(alice)

        before = store.inventory('alice', 1)
        peer_before = store.inventory('bob', 1)
        for args in ((2, 1001), (1, 1001, 2), (1, 1002), (1, 1003)):
            discard(*args)
            self.assertEqual(store.inventory('alice', 1), before)
        discard(1, 1001)
        after = store.inventory('alice', 1)
        self.assertEqual([i.instance_id for i in decode_item_list(after)[1]], [1002, 1003])
        discard(1, 1001)
        self.assertEqual(store.inventory('alice', 1), after)
        self.assertEqual(store.inventory('bob', 1), peer_before)
        game.ping(bob)

    def test_craft_projects_power_without_saving_the_client_flag(self):
        request = b'\xc1\x10' + struct.pack('<II', 1001, 1002)
        for roll, expected in ((0, 521), (99, 448)):
            with self.subTest(outcome=expected), TemporaryDirectory() as directory:
                path = Path(directory) / 'workshop.sqlite3'
                items = (implant(1001, variant(6103, 2), SLOTS[1]), implant(1002, 6105),
                         implant(1003, 6100, SLOTS[0]), implant(1004, 6120, resource=3600))
                store = OwnedPetStore(path)
                store.ensure('alice', workshop_pet(1), encode_item_list(1, items), human=True)
                AbilityLearning.from_workspace(path, ROOT).state.replace(
                    'alice', 1, (AbilityEntry(35, 4, 0, 0),), expected_revision=0)
                inventory, _, outcome = craft(path, 'alice', request, allow_mutation=True,
                                               randbelow=lambda _: roll)
                self.assertEqual(int.from_bytes(outcome[1:5], 'little'), expected)
                projected = [item for item in decode_item_list(inventory)[1] if item.equipped]
                saved = [item for item in decode_item_list(store.inventory('alice', 1))[1] if item.equipped]
                self.assertEqual(len(projected), 2 if expected == 521 else 1)
                self.assertEqual([i.unknown_bytes_02[1] for i in projected], [1] * len(projected))
                self.assertEqual([i.unknown_bytes_02[1] for i in saved], [0] * len(projected))

    def test_large_workshop_catalogue_delivers_every_recipe_on_login(self):
        game = test_multi_account.MultiAccountTests()
        game.setUp()
        self.addCleanup(game.doCleanups)
        game.start()
        bob = game.handoff(game.begin('bob'))
        game.enter(bob, 'Bob')

        inventories = workshop_inventories(15)
        with closing(sqlite3.connect(game.config.database)) as db, db:
            db.executemany('INSERT INTO owned_pets VALUES (?, ?, 1, ?, ?)',
                           [('alice', owner, workshop_pet(owner), packet)
                            for owner, packet in enumerate(inventories, 1)])

        alice = game.handoff(game.begin('alice'))
        alice.send(b'\x0c0.21:63\0\0')
        self.assertEqual(alice.receive(), b'\x0d\0')
        self.assertTrue(alice.receive().startswith(b'\xb9\x01'))
        alice.send(b'\xb9\x02items\0')
        data = decode_shared_config_data(alice.receive())
        root = ET.fromstring(zlib.decompress(data.compressed_bytes))
        aliases = {tuple(sorted(map(int, value.get('val').split(','))))
                   for item in root if int(item.get('id')) >= policy()['combo']['alias_start']
                   for value in item.findall("value[@key='parentIds']")}
        self.assertEqual(aliases, set(available_pairs(inventories)))
        alice.send(b'\xb9\x04')
        for name in (b'skills', b'zones', b'customization', b'premiumaccount', b'services'):
            self.assertTrue(alice.receive().startswith(b'\xb9\x01'))
            alice.send(b'\xb9\x02' + name + b'\0')
            self.assertTrue(alice.receive().startswith(b'\xb9\x03'))
            alice.send(b'\xb9\x04')
        self.assertEqual([r.name_bytes for r in decode_character_list(alice.receive())], [b'Alice'])
        game.ping(bob)

    def test_oversized_legacy_catalogue_sends_bounded_refresh_once(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'workshop.sqlite3'
            OwnedPetStore(path)
            inventories = workshop_inventories(24)
            with closing(sqlite3.connect(path)) as db, db:
                db.executemany('INSERT INTO owned_pets VALUES (?, ?, 1, ?, ?)',
                               [('alice', owner, workshop_pet(owner), inventory)
                                for owner, inventory in enumerate(inventories, 1)])
            session = SimpleNamespace(database=path, account='alice', interface='original')
            packet, = catalogue_updates(session)
            data = decode_shared_config_data(packet)
            self.assertLessEqual(len(data.compressed_bytes), MAX_COMPRESSED_SIZE)
            xml = zlib.decompress(data.compressed_bytes)
            self.assertEqual(len(xml), data.decompressed_size)
            root = ET.fromstring(xml)
            self.assertIsNotNone(root.find("item[@id='6600']/value[@key='parentIds'][@val='6100,6101']"))
            requested = available_pairs(inventories)
            aliases = sum(int(item.get('id')) >= policy()['combo']['alias_start'] for item in root)
            self.assertLess(0, aliases)
            self.assertLess(aliases, len(requested))
            self.assertEqual(catalogue_updates(session), ())
