from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from tio.enhancement import EnhancementRules, EnhancementStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.enhancement import decode_enhancement_request
from tio.protocol.item_list import ItemRecord, encode_item_list, decode_item_list
from tio.protocol.warehouse import decode_warehouse_list, warehouse_item_from_inventory
from tio.warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]


def request(target=1001, kit=1002):
    return b'\xc8\x2a'+struct.pack('<IB', target, kit is not None)+(struct.pack('<I', kit) if kit is not None else b'')


def item(identity, template, level=0, count=1):
    return ItemRecord(identity, template, bytes(2), count, 0, 0, (300+65*level,)*3,
                      bytes((level, 0, 0, 0)), None, bytes((level, 0, 0)))


class EnhancementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'test.db'
        self.pet = bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        self.rules = EnhancementRules()
        self.store = EnhancementStore(self.path, rules=self.rules, randbelow=lambda n: 0)
        self.seed(item(1001, 301), item(1002, 30))

    def seed(self, *items):
        inv = encode_item_list(1, items)
        OwnedPetStore(self.path).ensure('alice', self.pet, inv, human=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1', (inv, 'alice'))

    def saved(self):
        return OwnedPetStore(self.path).inventory('alice', 1)

    def seed_stock(self, alice_count):
        warehouse = WarehouseStore(self.path)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executemany('INSERT INTO warehouse_items VALUES (?,?,?)', (
                (account, 2000, encode_item_list(0, (item(2000, 30, count=count),)))
                for account, count in (('alice', alice_count), ('bob', 3))))
        return warehouse

    def test_le_roll_boundary_preserves_item_and_spends_one_kit(self):
        for template in (301, 243, 252):
            target = replace(item(1001, template, 10), unknown_words=(151, 500, 950))
            kit = item(1002, 129, count=2)
            for roll, outcome in ((49, 'success'), (50, 'preserved')):
                with self.subTest(template=template, roll=roll):
                    self.seed(target, kit)
                    result = EnhancementStore(self.path, randbelow=lambda n: roll).handle('alice', request())
                    saved, remaining = decode_item_list(self.saved())[1]
                    self.assertEqual((result.outcome, result.chance, remaining.count), (outcome, 50, 1))
                    self.assertEqual(result.level, 11 if roll == 49 else 10)
                    if roll == 50:
                        self.assertEqual(saved, target)
                        self.assertEqual(result.replies[-1], b'\xf0\x9d'+bytes(7))

    def test_le_exclusions_reject_without_consuming_kit(self):
        for template, level in ((314, 0), (315, 0), (316, 0), (301, 25), (301, 27)):
            self.seed(item(1001, template, level), item(1002, 129))
            before = self.saved()
            with self.assertRaises(ValueError):
                self.store.handle('alice', request())
            self.assertEqual(self.saved(), before)

    def test_le_respects_safe_levels_and_requires_explicit_selection(self):
        self.seed(item(1001, 301, 1), item(1002, 129), item(1003, 30))
        self.store.handle('alice', request(kit=None))
        self.assertEqual(decode_item_list(self.saved())[1][1].template_id, 129)
        self.seed(item(1001, 301, 1), item(1002, 129))
        def fail(n): raise AssertionError('Safe attempt must not roll')
        result = EnhancementStore(self.path, randbelow=fail).handle('alice', request())
        self.assertEqual((result.outcome, result.chance, result.level), ('success', 100, 2))

    def test_menu_upgrade_consumes_personal_stock_and_refreshes_client(self):
        self.seed(item(1001, 301))
        warehouse = self.seed_stock(2)

        for remaining in (1, 0):
            result = self.store.handle('alice', request(kit=None))
            self.assertEqual((result.outcome, result.level), ('success', 2 - remaining))
            target, = decode_item_list(self.saved())[1]
            self.assertEqual(target.unknown_bytes_03[0], 2 - remaining)
            stock = next(packet for packet in result.replies if packet[:1] == b'\x6a')
            assets = next(packet for packet in result.replies if packet[:2] == b'\xc8\x39')
            self.assertEqual([kit.count for kit in decode_warehouse_list(stock)[3]], [1] if remaining else [])
            self.assertEqual(decode_asset_count(assets).upgrade_kits, remaining)

        before = self.saved()
        with self.assertRaisesRegex(ValueError, 'Upgrade Kit required'):
            self.store.handle('alice', request(kit=None))
        self.assertEqual(self.saved(), before)
        self.assertEqual(warehouse.items('alice'), ())
        self.assertEqual([kit.count for kit in warehouse.items('bob')], [3])

    def test_menu_upgrade_prefers_stock_to_bag(self):
        warehouse = self.seed_stock(1)
        self.store.handle('alice', request(kit=None))
        self.assertEqual(warehouse.items('alice'), ())
        self.assertEqual(decode_item_list(self.saved())[1][1], item(1002, 30))

    def test_menu_reply_updates_the_dialog_item_before_announcing_success(self):
        self.seed(replace(item(1001, 301, 2), unknown_u8_01=1, location_raw=16))
        self.seed_stock(1)
        result = self.store.handle('alice', request(kit=None))

        # Native InventoryUpdate34 replaces the dialog's copy by instance ID.
        self.assertEqual(result.replies[-2], struct.pack(
            '<BBIBIIIIIBBBIHHH10B', 0x34, 1, 1, 0, 1,
            1001, 301, 1, 2, 0, 0, 1, 16, 495, 495, 495,
            3, 0, 0, 0, 0, 0, 0, 0, 3, 0))
        self.assertEqual(result.replies[-1][:5], b'\xf0\x97\0\0\0')

    def test_menu_upgrade_rolls_back_stock_debit_when_save_fails(self):
        self.seed(item(1001, 301))
        warehouse = self.seed_stock(1)
        before = self.saved(), warehouse.items('alice')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_sequence BEFORE INSERT ON item_sequences BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.Error):
            self.store.handle('alice', request(kit=None))
        self.assertEqual((self.saved(), warehouse.items('alice')), before)

    def test_safe_levels_no_random_consumed_and_persistent(self):
        def fail(n): raise AssertionError('Safe attempt must not roll')
        for level in (0, 1):
            self.seed(item(1001, 301, level), item(1002, 30, count=2))
            result = EnhancementStore(self.path, randbelow=fail).handle('alice', request())
            saved, kit = decode_item_list(self.saved())[1]
            self.assertEqual((result.outcome, result.chance, saved.unknown_bytes_03[0], kit.count), ('success', 100, level+1, 1))
            self.assertEqual(saved.unknown_bytes_02[0], level+1)
            self.assertEqual(saved.unknown_words, (300+65*(level+1),)*3)
            self.assertEqual(result.replies[0], self.saved())
            self.assertEqual(warehouse_item_from_inventory(saved).enhance_level, level+1)

    def test_upgrade_restores_theoretical_durability_after_repairs(self):
        self.seed(replace(item(1001,301),unknown_words=(50,100,300)),item(1002,30))
        self.store.handle('alice',request())
        self.assertEqual(decode_item_list(self.saved())[1][0].unknown_words,(365,365,365))

    def test_chance_boundary_and_ordinary_destruction(self):
        for roll, outcome in ((62, 'success'), (63, 'destroyed'), (99, 'destroyed')):
            self.seed(item(1001, 301, 2), item(1002, 30))
            result = EnhancementStore(self.path, randbelow=lambda n: roll).handle('alice', request())
            self.assertEqual((result.outcome, result.chance), (outcome, 63))
            self.assertEqual(len(decode_item_list(self.saved())[1]), int(outcome == 'success'))
            with self.assertRaises(ValueError): self.store.handle('alice', request())

    def test_se_resets_initial_durability_and_keeps_equipment(self):
        for template in (248, 249, 250, 251, 252, 253, 256, 264, 266):
            self.seed(replace(item(1001, template, 7), unknown_u8_01=1, location_raw=4), item(1002, 30))
            result = EnhancementStore(self.path, randbelow=lambda n: 99).handle('alice', request())
            saved, = decode_item_list(self.saved())[1]
            self.assertEqual(result.outcome, 'reset')
            self.assertEqual((saved.instance_id, saved.equipped, saved.slot, saved.unknown_bytes_03[0], saved.unknown_bytes_02[0]), (1001, 1, 4, 0, 0))
            self.assertEqual(saved.unknown_words, (self.rules.items[template]['durability'],)*3)

    def test_limit_25_rejections_leave_kit_and_item(self):
        self.seed(item(1001, 301, 24), item(1002, 30, count=2))
        self.assertEqual(self.store.handle('alice', request()).level, 25)
        before = self.saved()
        for account, packet, allowed in [('alice', request(), True), ('bob', request(), True),
                ('alice', request(999), True), ('alice', request(kit=None), True), ('alice', request(), False)]:
            with self.assertRaises(ValueError): self.store.handle(account, packet, allow_mutation=allowed)
            self.assertEqual(self.saved(), before)

    def test_malformed_requests_and_wrong_consumables(self):
        for packet in (b'', b'\xc8\x2a', request()+b'\0', request()[:6]+b'\2', request(0), request(kit=0)):
            with self.assertRaises(ValueError): decode_enhancement_request(packet)
        for target, kit in ((14, 30), (317, 30), (301, 19), (30, 30)):
            self.seed(item(1001, target), item(1002, kit))
            before = self.saved()
            with self.assertRaises(ValueError): self.store.handle('alice', request())
            self.assertEqual(self.saved(), before)

    def test_sql_failure_rolls_back_kit_and_item(self):
        before = self.saved()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER reject_sequence BEFORE INSERT ON item_sequences BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        with self.assertRaises(sqlite3.Error): self.store.handle('alice', request())
        self.assertEqual(self.saved(), before)

    def test_same_kit_concurrent_requests_only_one_commits(self):
        def attempt(_):
            try: return self.store.handle('alice', request()).outcome
            except ValueError: return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (0, 1)))
        self.assertCountEqual(results, ['success', 'rejected'])
        self.assertEqual(decode_item_list(self.saved())[1][0].unknown_bytes_03[0], 1)

    def test_real_combat_uses_bonus_before_skill_and_armor(self):
        from test_weapon_proficiency import setup
        from tio.protocol.battle_attack import AttackRequest
        from tio.armor import ArmorCatalog
        field, combat = setup()
        owner, items, unknown = decode_item_list(combat.inventories[1])
        items = (replace(items[0], unknown_bytes_02=b'\5\0\0\0', unknown_bytes_03=b'\5\0\0'), *items[1:])
        combat.inventories[1] = encode_item_list(owner, items, unknown)
        combat.attack(7, AttackRequest(1, 5, 1))
        self.assertEqual(field.actor(2).health, 960)  # +3 cap, distance4: 54 -> 48 -> 40 at skill35.
        armor = ArmorCatalog()
        inv = encode_item_list(1, (replace(item(1, 248, 5), unknown_u8_01=1, location_raw=4),))
        self.assertEqual(armor.defense(inv, human=True), 86)  # 80+2+floor(3*1.5)


if __name__ == '__main__': unittest.main()
