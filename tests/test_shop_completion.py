"""Accepted transactions against scoped published-source shop candidates."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

from wallet_fixture import fund_wallet
from tio.city_catalogs import CityCatalogs
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.shop_purchase import ShopPurchase
from tio.protocol.shop_sale import ShopSale
from tio.shop_completion import ShopCompletion, CompletedSCShopStore, MONDAY, WEEK

ROOT = Path(__file__).resolve().parents[1]
from tio import shop as candidate
if getattr(candidate, 'ShopCompletion', None) is not ShopCompletion:
    # Locally isolate the published-source candidate; on the host exercise the
    # actually installed runtime instead of quietly testing a report copy.
    spec = importlib.util.spec_from_file_location('tio._completed_shop_test', ROOT/'reports/gameplay-followup/stage2-shops/runtime/tio/shop.py')
    candidate = importlib.util.module_from_spec(spec)
    __import__('sys').modules[spec.name] = candidate
    spec.loader.exec_module(candidate)


def sc_request(action, *fields):
    return bytes((0xb4, action)) + b''.join(struct.pack('<I', value) for value in fields)


class ShopCompletionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'shared.sqlite3'
        self.policy_path = Path(self.folder.name)/'policy.json'
        self.policy = json.loads((ROOT/'config/shop_completion.json').read_text(encoding='utf-8'))
        self.policy['stock']['weapon'] = dict(mode='weekly', capacity=2)
        self.policy['stock']['armor'] = dict(mode='weekly', capacity=2)
        self.policy['stock']['supply'] = dict(mode='threshold', capacity=3, threshold=2, delay_seconds=20)
        self.policy['stock']['le_kit'] = dict(mode='finite', capacity=3000)
        self.write_policy()
        self.now = MONDAY + 100*WEEK + 100
        self.pet = bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for account in ('alice', 'bob'):
            OwnedPetStore(self.path).ensure(account, self.pet, encode_item_list(1, ()), human=True)
            fund_wallet(self.path, account, credits=1000000, gold=1000000)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)', [('alice',), ('bob',)])
        self.catalogs = CityCatalogs(ROOT/'config/city_catalogs.json')
        self.store = candidate.ShopStore(self.path, self.catalogs)
        self.store.completion = self.completion()
        self.sc = CompletedSCShopStore(self.path, policy_path=self.policy_path, clock=lambda: self.now)

    def completion(self):
        return ShopCompletion(self.path, self.catalogs, policy_path=self.policy_path, clock=lambda: self.now)

    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy), encoding='utf-8')

    def offer(self, template):
        return next(o for o in self.catalogs.items[0] if o.item_id == template)

    def buy(self, template, account='alice', quantity=1, **kwargs):
        return self.store.purchase(account, ShopPurchase(1, 0, self.offer(template).unknown_u32_01, quantity), **kwargs)

    def items(self, account='alice'):
        return decode_item_list(OwnedPetStore(self.path).inventory(account, 1))[1]

    def set_items(self, items, account='alice'):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1', (encode_item_list(1, tuple(items)), account))

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {table: db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                    for table in ('wallets', 'owned_pets', 'shop_global_stock', 'shop_receipts', 'sc_cart', 'sc_cart_terms', 'sc_sold', 'sc_receipts', 'item_sequences')}

    def database_snapshot(self):
        # Include all tables/triggers, including achievement and warehouse
        # state, so read-only catalog checks cannot overlook unrelated writes.
        with closing(sqlite3.connect(self.path)) as db:
            return tuple(db.iterdump())

    def locate(self, town, account='alice'):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE character_locations SET town_id=? WHERE account=?', (town, account))

    def premium_buy(self, account='alice', *, identity=None):
        offer = next(o for o in self.catalogs.premium_items if o.item_id == 301)
        packet = (b'\x78' + struct.pack('<IIIII', 1, offer.offer_id, 1, 1, 0)
                  + self.catalogs.price_revision.to_bytes(8, 'little') + bytes(4))
        return self.store.purchase_premium(account, packet, identity=identity)

    def lot(self, template=301, level=10):
        return next(lot for lot, offer in self.sc.offers.items() if (offer.item_id, offer.enhancement) == (template, level))

    def test_weapon_free_box_pack_and_id_sequence_survive_restart_replay(self):
        first = self.buy(301, identity='packet-a')
        self.assertEqual([(i.template_id, i.count, i.instance_id) for i in self.items()], [(301, 1, 1), (3, 50, 2)])
        self.assertEqual(first.charged_credits, 150)
        self.buy(3, identity='packet-b')
        current = self.items()
        self.assertEqual(current[1].count, 100)
        replay = candidate.ShopStore(self.path, self.catalogs).purchase('alice', ShopPurchase(1, 0, self.offer(301).unknown_u32_01, 1), identity='packet-a')
        self.assertEqual(decode_item_list(replay.inventory)[1], current)
        self.assertEqual(replay.assets.credits, 1000000-200)
        self.assertEqual(replay.operation_id, first.operation_id)
        self.buy(327, account='bob')
        self.assertEqual([(i.template_id, i.count) for i in self.items('bob')], [(327, 1)])
        with self.assertRaises(candidate.PurchaseRejected):
            self.buy(301, quantity=2, identity='packet-a')

    def test_global_stock_shared_between_accounts_with_city_partition(self):
        self.buy(301, quantity=2)
        before = self.state()
        with self.assertRaises(candidate.PurchaseRejected): self.buy(301, account='bob')
        self.assertEqual(self.state(), before)
        rows = decode_item_shop(self.store.catalog('bob', 0))[1]
        self.assertNotIn(301, [o.item_id for o in rows])
        self.assertEqual(next(o for o in rows if o.item_id == 3).unknown_u32_02, 50)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE character_locations SET town_id=2 WHERE account='bob'")
        self.buy(301, account='bob')
        self.assertEqual(len(self.items('bob')), 2)

    def test_concurrent_last_stock_has_one_accepted_receipt(self):
        self.buy(301)
        def attempt(account):
            try:
                self.buy(301, account=account, identity='last-one')
                return True
            except candidate.PurchaseRejected: return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, ('alice', 'bob'))), [False, True])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT quantity FROM shop_global_stock WHERE town=3 AND offer_id=?', (self.offer(301).unknown_u32_01,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM shop_receipts WHERE inventory IS NOT NULL').fetchone()[0], 2)

    def test_weekly_and_delayed_threshold_refill_are_persistent_and_read_only(self):
        self.buy(301, quantity=2)
        self.buy(30, quantity=2)
        self.assertEqual(self.items()[2].template_id, 301)
        with closing(sqlite3.connect(self.path)) as db:
            state = db.execute('SELECT quantity,refill_at FROM shop_global_stock WHERE offer_id=?', (self.offer(30).unknown_u32_01,)).fetchone()
        self.assertEqual(state, (1, self.now+20))
        with self.assertRaises(candidate.PurchaseRejected): self.buy(30, account='bob', quantity=2)
        self.now += 20
        before = self.state()
        self.store.catalog('bob', 0)
        self.assertEqual(self.state(), before)
        self.store.completion = self.completion()
        self.buy(30, account='bob', quantity=3)
        self.now = MONDAY + 101*WEEK
        self.buy(301, account='bob')
        with closing(sqlite3.connect(self.path)) as db:
            state = db.execute('SELECT quantity,week FROM shop_global_stock WHERE offer_id=?', (self.offer(301).unknown_u32_01,)).fetchone()
        self.assertEqual(state, (1, self.now))

    def test_capacity_serialization_and_database_failures_rollback_stock_and_charge(self):
        # Each missile is deliberately nonstackable, and the free-box occupies
        # capacity too. A failed purchase must leave no hidden stock mutation.
        gear = ItemRecord(100, 327, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))
        self.set_items(replace(gear, instance_id=n) for n in range(1, 18))
        before = self.state()
        with self.assertRaises(candidate.PurchaseRejected): self.buy(301)
        self.assertEqual(self.state(), before)
        self.set_items(())
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER fail_shop BEFORE UPDATE ON owned_pets BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError): self.buy(301)
        self.assertEqual(self.state(), before)

    def test_worn_enhanced_sale_uses_real_upgrade_and_theoretical_depreciation(self):
        base = ItemRecord(1, 301, bytes(2), 1, 0, 0, (475, 600, 950), bytes((3, 0, 0, 0)), None, bytes((10, 0, 0)))
        self.set_items((base,))
        request = ShopSale(1, 1, 1)
        before = self.state()
        self.assertEqual(self.store.sell('alice', request, quote=True), (150+10*1050)*65//200)
        self.assertEqual(self.state(), before)
        result = self.store.sell('alice', request, identity='sold-real-ten')
        self.assertEqual(result.assets.credits, 1000000+(150+10500)*65//200)
        self.assertEqual(self.items(), ())
        self.assertEqual(self.store.sell('alice', request, identity='sold-real-ten').assets, result.assets)

    def test_used_repairkit_and_ammo_unit_prices(self):
        kit = ItemRecord(1, 17, bytes(2), 1, 0, 0, (300, 600, 600), bytes(4), None, bytes(3))
        ammo = ItemRecord(2, 3, bytes(2), 50, 0, 0, (1,)*3, bytes(4), None, bytes(3))
        self.set_items((kit, ammo))
        self.assertEqual(self.store.sell('alice', ShopSale(1, 1, 1), quote=True), 146)
        self.assertEqual(self.store.sell('alice', ShopSale(1, 2, 20), quote=True), 13)

    def test_sale_marks_rental_unknown_metadata_equip_bad_durability_fail_closed(self):
        base = ItemRecord(1, 301, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))
        invalid = [replace(base, unknown_u8_01=1, location_raw=16),
                   replace(base, unknown_bytes_01=b'\1\0'), replace(base, optional_u32=123),
                   replace(base, unknown_bytes_02=b'\0\0\1\0'), replace(base, unknown_bytes_02=b'\0\0\0\1'),
                   replace(base, unknown_bytes_02=b'\0\1\0\0'), replace(base, unknown_bytes_03=b'\0\1\0'),
                   replace(base, unknown_words=(300, 200, 300)), replace(base, unknown_words=(300, 300, 999))]
        for item in invalid:
            with self.subTest(item=item):
                self.set_items((item,))
                before = self.state()
                with self.assertRaises(ValueError): self.store.sell('alice', ShopSale(1, 1, 1))
                self.assertEqual(self.state(), before)

    def test_city_gate_normal_armor_only_and_documented_level_band(self):
        # An existing original level-required field controls assortment; its
        # absence is level1. No invented weapon-class level requirements.
        self.store.completion.values[301]['level_required'] = '4'
        self.assertNotIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('alice', 0))[1]])
        with self.assertRaises(candidate.PurchaseRejected): self.buy(301)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE character_locations SET town_id=2 WHERE account='alice'")
        self.buy(301)
        for town in (-1, 4, 10, 65535):
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("UPDATE character_locations SET town_id=? WHERE account='alice'", (town,))
            before = self.state()
            with self.assertRaises(candidate.PurchaseRejected): self.buy(327)
            self.assertEqual(self.state(), before)

    def test_miners_town_has_the_documented_full_city_catalogs_without_database_writes(self):
        from tio.locations import town_packets
        from tio.protocol.town_info import decode_town_info
        # Mine's Town is a city with levels 1-20, distinct from Mine 4-6 (13).
        self.assertEqual(decode_town_info(town_packets(9)[0]).unknown_bytes[:2], (1, 20))
        self.assertEqual(self.policy['town_max_level']['9'], 20)
        catalogs = []
        for town in (2, 9):
            self.locate(town)
            before = self.database_snapshot()
            ordinary = tuple(self.store.catalog('alice', category) for category in self.catalogs.items)
            premium = tuple(self.store.catalog('alice', category, gold=True) for category in (0, 1))
            sc, = self.sc.handle('alice', sc_request(4))
            self.assertEqual(self.database_snapshot(), before)
            self.assertTrue(any(decode_item_shop(packet)[1] for packet in ordinary))
            self.assertTrue(all(struct.unpack_from('<I', packet, 14)[0] > 0 for packet in premium))
            self.assertEqual(sc[:2], b'\xb4\x05')
            self.assertGreater(struct.unpack_from('<I', sc, 2)[0], 0)
            catalogs.append((ordinary, premium, sc))
        self.assertEqual(catalogs[0], catalogs[1])
        # The actual level-required metadata, rather than town identity alone,
        # still limits the assortment at the documented upper boundary.
        self.store.completion.values[301]['level_required'] = '20'
        self.assertIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('alice', 0))[1]])
        self.store.completion.values[301]['level_required'] = '21'
        before = self.database_snapshot()
        self.assertNotIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('alice', 0))[1]])
        with self.assertRaises(candidate.PurchaseRejected): self.buy(301)
        self.assertEqual(self.database_snapshot(), before)

    def test_miners_town_native_ordinary_premium_sc_purchases_and_restart_replays(self):
        self.locate(9)
        bob_items = self.items('bob')
        bob_wallet = WalletStore(self.path).ensure('bob')
        ordinary = self.buy(301, identity='miners-ordinary')
        premium = self.premium_buy(identity='miners-premium')
        lot = self.lot()
        sc = self.sc.handle('alice', sc_request(6, lot, 1, 2), identity='miners-sc')
        self.assertEqual((ordinary.charged_credits, ordinary.charged_gold), (150, 0))
        self.assertEqual((premium.charged_credits, premium.charged_gold), (0, 1))
        self.assertEqual(decode_asset_count(sc[1]).credits, 1000000 - 150)
        self.assertEqual(decode_asset_count(sc[1]).gold, 1000000 - 1 - 71)
        weapons = [item for item in self.items() if item.template_id == 301]
        self.assertEqual([item.unknown_bytes_03[0] for item in weapons], [0, 0, 10])
        self.assertEqual(next(item for item in self.items() if item.template_id == 3).count, 150)
        self.assertEqual(len({item.instance_id for item in self.items()}), len(self.items()))
        self.assertEqual(self.items('bob'), bob_items)
        self.assertEqual(WalletStore(self.path).ensure('bob'), bob_wallet)
        self.store = candidate.ShopStore(self.path, self.catalogs)
        self.store.completion = self.completion()
        self.sc = CompletedSCShopStore(self.path, policy_path=self.policy_path, clock=lambda: self.now)
        before = self.database_snapshot()
        replay = self.buy(301, identity='miners-ordinary')
        self.assertEqual(replay.operation_id, ordinary.operation_id)
        self.assertEqual(decode_item_list(replay.inventory)[1], self.items())
        self.premium_buy(identity='miners-premium')
        self.sc.handle('alice', sc_request(6, lot, 1, 2), identity='miners-sc')
        self.assertEqual(self.database_snapshot(), before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT town,currency,quantity FROM shop_global_stock').fetchall(), [(9, 0, 1)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM shop_receipts WHERE inventory IS NOT NULL').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sc_receipts WHERE accepted=1').fetchone()[0], 1)

    def test_miners_town_stock_is_shared_partitioned_and_persistent(self):
        self.locate(9)
        self.locate(9, 'bob')
        self.buy(301, quantity=2)
        before = self.database_snapshot()
        self.assertNotIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('bob', 0))[1]])
        with self.assertRaises(candidate.PurchaseRejected): self.buy(301, account='bob')
        self.assertEqual(self.database_snapshot(), before)
        # Gold stock remains unlimited and a different city's ordinary stock
        # cannot be exhausted by another city's accepted purchases.
        self.premium_buy('bob')
        self.locate(2, 'bob')
        self.buy(301, account='bob')
        self.store = candidate.ShopStore(self.path, self.catalogs)
        self.store.completion = self.completion()
        before = self.database_snapshot()
        self.assertNotIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('alice', 0))[1]])
        self.assertIn(301, [o.item_id for o in decode_item_shop(self.store.catalog('bob', 0))[1]])
        self.assertEqual(self.database_snapshot(), before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT town,currency,quantity FROM shop_global_stock ORDER BY town').fetchall(), [(2, 0, 1), (9, 0, 0)])

    def test_miners_town_insufficient_wallet_is_atomic_for_all_shops(self):
        self.locate(9)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET credits=149,gold=0 WHERE account='alice'")
        for purchase in (lambda: self.buy(301), self.premium_buy,
                         lambda: self.sc.handle('alice', sc_request(6, self.lot(), 1, 2))):
            with self.subTest(purchase=purchase):
                before = self.database_snapshot()
                with self.assertRaises(ValueError): purchase()
                self.assertEqual(self.database_snapshot(), before)

    def test_non_shop_locations_reject_all_catalogs_and_purchases_without_writes(self):
        # Travel, outpost, prison, bases and each actual mine remain unavailable.
        for town in (-1, 0, 1, 4, 10, 11, 12, 13, 14, 15, 16, 17, 65535):
            self.locate(town)
            for operation in (lambda: self.store.catalog('alice', 0),
                              lambda: self.store.catalog('alice', 0, gold=True),
                              lambda: self.sc.handle('alice', sc_request(4)),
                              lambda: self.buy(301), self.premium_buy,
                              lambda: self.sc.handle('alice', sc_request(6, self.lot(), 1, 2))):
                with self.subTest(town=town, operation=operation):
                    before = self.database_snapshot()
                    with self.assertRaisesRegex(ValueError, 'Магазин доступен только в городе'): operation()
                    self.assertEqual(self.database_snapshot(), before)

    def test_premium_weapon_bundle_uses_gold_price_and_shared_capacity(self):
        from tio.protocol.shop_purchase import ShopPurchase
        offer = next(o for o in self.catalogs.premium_items if o.item_id == 301)
        result = self.store.purchase('alice', ShopPurchase(1, 0, offer.offer_id, 1), _gold=True, identity='gold-box')
        self.assertEqual(result.charged_gold, 1)
        self.assertEqual([(i.template_id, i.count) for i in self.items()], [(301, 1), (3, 50)])

    def test_sc_catalog_four_tiers_gold_only_unlimited_and_enhanced_records(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE character_locations SET town_id=2 WHERE account='alice'")
        catalog, = self.sc.handle('alice', sc_request(4))
        count = struct.unpack_from('<I', catalog, 2)[0]
        self.assertEqual(count, 190)
        self.assertEqual(len(catalog), 6+30*count)
        wire = [struct.unpack_from('<IIBHIIIIBH', catalog, 6+30*n) for n in range(count)]
        self.assertEqual({r[2] for r in wire}, {0, 10, 15, 20, 25})
        self.assertEqual({r[3] for r in wire}, {65535})
        self.assertTrue(all(r[4] == r[6] == 0 and r[5] == r[7] > 0 for r in wire))
        self.assertTrue(all(o.item_id in self.sc.completion.enhancement.items for o in self.sc.offers.values() if o.enhancement))
        for level in (10, 15, 20, 25):
            lot = self.lot(level=level)
            reply = self.sc.handle('alice', sc_request(6, lot, 1, 2), identity=f'sc-level-{level}')
            gun = next(i for i in reversed(self.items()) if i.template_id == 301)
            self.assertEqual((gun.unknown_bytes_02[0], gun.unknown_bytes_03[0], gun.unknown_words), (level, level, (300+65*level,)*3))
            self.assertEqual(decode_asset_count(reply[1]).gold, 1000000-sum(1+7*l for l in (10, 15, 20, 25) if l <= level))
        self.assertEqual(next(i for i in self.items() if i.template_id == 3).count, 200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sc_sold').fetchone()[0], 0)

    def test_sc_frozen_cart_survives_policy_version_restart_and_preserves_other_account(self):
        lot = self.lot()
        self.sc.handle('alice', sc_request(9, lot), identity='cart-add')
        self.sc.handle('alice', sc_request(9, lot), identity='cart-add')
        self.policy['version'] = 2
        self.write_policy()
        reopened = CompletedSCShopStore(self.path, policy_path=self.policy_path)
        self.assertNotIn(lot, reopened.offers)
        self.assertEqual(reopened.handle('bob', sc_request(7)), (b'\xb4\x08'+bytes(22),))
        reply = reopened.handle('alice', sc_request(11, 1, 2), identity='frozen-checkout')
        self.assertEqual(decode_asset_count(reply[1]).gold, 1000000-71)
        self.assertEqual(next(i for i in self.items() if i.template_id == 301).unknown_bytes_03[0], 10)
        after = self.state()
        reopened.handle('alice', sc_request(11, 1, 2), identity='frozen-checkout')
        self.assertEqual(self.state(), after)

    def test_existing_legacy_cart_honors_price_and_gets_ammo_without_new_base_offer(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO sc_cart VALUES (?,100314,1)', ('alice',))
            db.execute('INSERT INTO sc_sold VALUES (?,100314,5)', ('alice',))
        with self.assertRaises(ValueError): self.sc.handle('alice', sc_request(6, 100314, 1, 2))
        with self.assertRaises(ValueError): self.sc.handle('alice', sc_request(9, 100314))
        reply = self.sc.handle('alice', sc_request(11, 1, 2), identity='legacy-checkout')
        self.assertEqual(decode_asset_count(reply[1]).gold, 999900)
        self.assertEqual([(i.template_id, i.count) for i in self.items()], [(314, 1), (14, 100)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT quantity FROM sc_sold WHERE account=?', ('alice',)).fetchone()[0], 6)

    def test_non_enhanceable_sc_supplies_keep_provisional_terms_and_ignore_old_sold_limit(self):
        lot = 100014
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO sc_sold VALUES (?,?,1000)', ('alice', lot))
        reply = self.sc.handle('alice', sc_request(6, lot, 1, 2))
        self.assertEqual(decode_asset_count(reply[1]).gold, 999975)
        self.assertEqual([(i.template_id, i.count, i.unknown_bytes_03[0]) for i in self.items()], [(14, 100, 0)])
        self.sc.handle('alice', sc_request(9, lot))
        self.sc.handle('alice', sc_request(11, 1, 2))
        self.assertEqual(self.items()[0].count, 200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT quantity FROM sc_sold WHERE account=? AND lot_id=?', ('alice', lot)).fetchone()[0], 1000)
        nonenhanced = [o for o in self.sc.offers.values() if o.enhancement == 0]
        self.assertEqual(len(nonenhanced), 10)
        self.assertTrue(all(o.item_id not in self.sc.completion.enhancement.items for o in nonenhanced))

    def test_sc_ownership_battle_gate_gold_failure_and_database_failure_are_atomic(self):
        lot = self.lot()
        for args in [('alice', sc_request(6, lot, 999, 2)), ('alice', sc_request(6, lot, 1, 1)), ('missing', sc_request(6, lot, 1, 2))]:
            before = self.state()
            with self.assertRaises(ValueError): self.sc.handle(*args)
            self.assertEqual(self.state(), before)
        with self.assertRaises(ValueError): self.sc.handle('alice', sc_request(6, lot, 1, 2), allow_mutation=False)
        self.sc.handle('alice', sc_request(9, lot))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET gold=70 WHERE account='alice'")
        before = self.state()
        with self.assertRaisesRegex(ValueError, 'Insufficient gold'): self.sc.handle('alice', sc_request(11, 1, 2))
        self.assertEqual(self.state(), before)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE wallets SET gold=1000 WHERE account='alice'")
            db.execute("CREATE TRIGGER fail_sc BEFORE UPDATE ON sc_receipts WHEN NEW.accepted=1 BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError): self.sc.handle('alice', sc_request(11, 1, 2))
        self.assertEqual(self.state(), before)

    def test_sc_same_identity_concurrent_purchase_and_current_snapshot_retry(self):
        lot = self.lot()
        def buy(_): return self.sc.handle('alice', sc_request(6, lot, 1, 2), identity='one-sc')
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(buy, range(2)))
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(len(self.items()), 2)
        self.buy(3)
        replay = buy(None)
        self.assertEqual(decode_item_list(replay[0])[1], self.items())
        self.assertEqual(next(i for i in self.items() if i.template_id == 3).count, 100)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sc_receipts WHERE accepted=1').fetchone()[0], 1)

    def test_shared_outer_transaction_rolls_back_both_shops_and_refuses_unleased_helpers(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.path):
                self.buy(301)
                self.sc.handle('alice', sc_request(6, self.lot(), 1, 2))
                raise RuntimeError('outer action rejected')
        self.assertEqual(self.items(), ())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 1000000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM shop_receipts').fetchone()[0], 0)
            with self.assertRaises(ValueError): self.completion().town(db, 'alice')

    def test_sc_warehouse_sequence_and_capacity_include_free_box(self):
        held = ItemRecord(5000, 327, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', ('alice', 5000, encode_item_list(0, (held,))))
        self.sc.handle('alice', sc_request(6, self.lot(), 1, 2))
        self.assertEqual([i.instance_id for i in self.items()], [5001, 5002])
        self.set_items(replace(held, instance_id=n) for n in range(1, 18))
        before = self.state()
        with self.assertRaises(ValueError): self.sc.handle('alice', sc_request(6, self.lot(), 1, 2))
        self.assertEqual(self.state(), before)


if __name__ == '__main__': unittest.main()
