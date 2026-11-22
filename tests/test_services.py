from wallet_fixture import fund_wallet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from xml.etree import ElementTree

from tio import services
from tio.wallets import WalletStore
from tio.protocol.binary import Writer
from tio.protocol.city_catalogs import ServiceOption, decode_service_shop
from tio.protocol.asset_count import decode_asset_count


def request(service=1, level=1, target=1, action=0):
    return Writer().u8(0xb1).u8(4).u8(action).u32(service).u8(level).u32(target).build()


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'state.sqlite3'
        self.wallets = WalletStore(self.path)
        for name in ('alice', 'bob'):
            fund_wallet(self.wallets.path, name, credits=10_000, gold=10_000)

    def set_credits(self, amount):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE wallets SET credits=? WHERE account=?', (amount, 'alice'))

    def test_purchase_retry_concurrent_and_account_isolation(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: services.purchase(self.path, 'alice', request()), range(4)))
        self.assertEqual(len(results), 4)
        self.assertEqual(self.wallets.ensure('alice').credits, 5000)
        self.assertEqual(self.wallets.ensure('bob').credits, 10000)
        self.assertEqual(services.snapshots(self.path, 'alice'), (services.status(1, 1),))
        self.assertEqual(services.snapshots(self.path, 'bob'), ())
        offers = decode_service_shop(services.catalog(self.path, 'alice'))
        self.assertEqual(offers[0].options[0].unknown_u8, 2)

    def test_reject_invalid_or_unfunded_without_mutation(self):
        for packet in (request(level=2), request(service=3), request(service=5),
                       request(target=2), request(action=1), request()+b'\0', request()[:-1]):
            with self.assertRaises(ValueError):
                services.purchase(self.path, 'alice', packet)
        self.assertEqual(self.wallets.ensure('alice').credits, 10000)
        services.purchase(self.path, 'alice', request())
        with self.assertRaises(ValueError):
            services.purchase(self.path, 'alice', request(level=2))
        self.assertEqual(self.wallets.ensure('alice').credits, 5000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(services.power(db, 'alice', 1), 8)
            self.assertEqual(services.power(db, 'bob', 1), 0)

    def test_upgrade_is_total_power_not_additive(self):
        services.purchase(self.path, 'alice', request(service=2))
        services.purchase(self.path, 'alice', request(service=2, level=2))
        self.assertEqual(self.wallets.ensure('alice').credits, 2200)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(services.power(db, 'alice', 2), 2)
        with self.assertRaises(ValueError):
            services.purchase(self.path, 'alice', request(service=2, level=1))
        self.assertEqual(services.snapshots(self.path, 'alice'), (services.status(2, 2),))

    def test_warehouse_tiers_charge_exact_prices_and_offer_only_next_level(self):
        self.set_credits(1_000_000)
        remaining = 1_000_000
        tiers = ((8, 5000), (16, 15000), (32, 30000), (64, 60000),
                 (128, 120000), (256, 240000))
        for number, (power, cost) in enumerate(tiers, 1):
            with self.subTest(level=number):
                offer = next(o for o in decode_service_shop(
                    services.catalog(self.path, 'alice')) if o.unknown_u32 == 1)
                self.assertEqual(offer.options, (ServiceOption(number, 0, cost),))
                replies = services.purchase(self.path, 'alice', request(level=number))
                remaining -= cost
                self.assertEqual(decode_asset_count(replies[1]).credits, remaining)
                with closing(sqlite3.connect(self.path)) as db:
                    self.assertEqual(services.power(db, 'alice', 1), power)
                self.assertEqual(services.snapshots(self.path, 'alice'),
                                 (services.status(1, number),))
        self.assertNotIn(1, [o.unknown_u32 for o in decode_service_shop(
            services.catalog(self.path, 'alice'))])

    def test_warehouse_shared_xml_contains_all_total_powers(self):
        root = ElementTree.fromstring(services.shared_xml())
        warehouse = root.find("service[@id='1']")
        self.assertEqual(warehouse.attrib, dict(id='1', name='se01', target='self',
                         expireType='never', canSellBack='false'))
        self.assertEqual([node.attrib for node in warehouse],
                         [dict(val=str(n), power=str(power)) for n, power in
                          enumerate((8, 16, 32, 64, 128, 256), 1)])

    def test_shared_xml_exposes_power_to_native_key_value_reader(self):
        root = ElementTree.fromstring(services.shared_xml())
        for service in root:
            for number, (power, _) in enumerate(services.OFFERS[int(service.get('id'))], 1):
                node = service.find(f"level[@val='{number}']/value[@key='power']")
                self.assertIsNotNone(node)
                self.assertEqual(node.get('val'), str(power))

    def test_concurrent_third_warehouse_level_charges_once_and_stays_private(self):
        self.set_credits(100_000)
        for number in (1, 2):
            services.purchase(self.path, 'alice', request(level=number))
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: services.purchase(
                self.path, 'alice', request(level=3)), range(4)))
        self.assertEqual(len(results), 4)
        self.assertEqual(self.wallets.ensure('alice').credits, 50_000)
        self.assertEqual(self.wallets.ensure('bob').credits, 10_000)
        self.assertEqual(services.snapshots(self.path, 'alice'), (services.status(1, 3),))
        self.assertEqual(services.snapshots(self.path, 'bob'), ())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(services.power(db, 'alice', 1), 32)
            self.assertEqual(services.power(db, 'bob', 1), 0)

    def test_extended_warehouse_rejections_preserve_balance_and_entitlement(self):
        self.set_credits(1_000_000)
        for number in (1, 2):
            services.purchase(self.path, 'alice', request(level=number))
        for number, cost in ((3, 30000), (4, 60000), (5, 120000), (6, 240000)):
            with self.subTest(level=number):
                self.set_credits(cost - 1)
                before = services.snapshots(self.path, 'alice')
                for packet in (request(level=number), request(level=number + 1),
                               request(level=number - 2), request(level=number, target=2)):
                    with self.assertRaises(ValueError):
                        services.purchase(self.path, 'alice', packet)
                    self.assertEqual(self.wallets.ensure('alice').credits, cost - 1)
                    self.assertEqual(services.snapshots(self.path, 'alice'), before)
                self.set_credits(cost)
                services.purchase(self.path, 'alice', request(level=number))
        with self.assertRaises(ValueError):
            services.purchase(self.path, 'alice', request(level=7))
        self.assertEqual(self.wallets.ensure('alice').credits, 0)
        self.assertEqual(services.snapshots(self.path, 'alice'), (services.status(1, 6),))

    def test_paid_roster_slot_changes_authoritative_hiring_limit(self):
        import json
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        from tio.owned_pets import OwnedPetStore
        root=Path(__file__).resolve().parents[1]
        trial=json.loads((root/'evidence/owned_pet_trial.json').read_text(encoding='utf-8'))
        store=HireStore(self.path,CityCatalogs(root/'config/city_catalogs.json'),bytes.fromhex(trial['packet_hex']))
        for _ in range(7):
            store.hire('alice',store.available('alice')[0].candidate_id)
        with self.assertRaises(ValueError):store.hire('alice',store.available('alice')[0].candidate_id)
        services.purchase(self.path,'alice',request(service=2))
        store.hire('alice',store.available('alice')[0].candidate_id)
        self.assertEqual(len(OwnedPetStore(self.path).list('alice')),8)
        with self.assertRaises(ValueError):store.hire('alice',store.available('alice')[0].candidate_id)
