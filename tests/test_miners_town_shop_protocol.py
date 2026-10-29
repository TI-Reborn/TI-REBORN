"""Exact hosted catalogue candidate over encrypted native socket frames.

Resource fixtures come from the repository; the session handler and ShopStore
are loaded from the inspected host baseline/candidate, not the older local shop.
No hosting, real account, or installed client state is used.
"""
from contextlib import closing
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from wallet_fixture import fund_wallet
from test_server_deployment import Peer
from tio import premium
from tio.city_catalogs import CityCatalogs
from tio.locations import center
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.transport import InitialCipher, InitialFrameReader
from tio.shop_errors import shop_error_reply
from tools import prepare_miners_town_shop_protocol as builder

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/gameplay-completion/miners-town-shop-20261010'


def load_runtime(name, path, resource_file=None):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    before = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    if resource_file is not None:
        # This partial scoped candidate deliberately contains no copied game
        # assets. Resolve its unchanged resource lookups against test fixtures.
        module.__file__ = str(resource_file)
    return module


class MinersTownShopProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = json.loads((REPORT/'baseline/source-snapshot.json').read_text())
        shop_path = REPORT/'baseline/runtime/tio/shop.py'
        assert hashlib.sha256(shop_path.read_bytes()).hexdigest() == snapshot['files']['tio/shop.py']['sha256']
        assert hashlib.sha256((ROOT/'tio/shop_completion.py').read_bytes()).hexdigest() == snapshot['files']['tio/shop_completion.py']['sha256']
        assert (ROOT/'config/shop_completion.json').read_bytes() == (REPORT/'runtime/config/shop_completion.json').read_bytes()
        import server
        import tio.protocol
        # Two unchanged, host-only warehouse helpers are necessary for loading
        # the actual session handler. Exercise their real opt-out path rather
        # than replacing host code with a test stub; neither is deployed here.
        for module_name, receipt_name, parent in (
                ('tio.protocol.warehouse_capacity','source-warehouse-protocol.json',tio.protocol),
                ('server.warehouse_capacity','source-warehouse-capacity.json',server)):
            receipt = json.loads((REPORT/'baseline'/receipt_name).read_text())
            path = REPORT/'baseline/runtime'/receipt['path']
            assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt['sha256']
            setattr(parent, 'warehouse_capacity', load_runtime(module_name, path))
        cls.host_shop = load_runtime('tio._miners_shop_host_baseline', shop_path)
        cls.runtime = load_runtime('tools._miners_shop_protocol_candidate', builder.TARGET,
                                   ROOT/'tools/loopback_exchange.py')
        cls.runtime.ShopStore = cls.host_shop.ShopStore

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'players.sqlite3'
        for account in ('probe_user', 'peer_user'):
            fund_wallet(self.path, account, credits=10000, gold=10000)
        self.catalogs = CityCatalogs(ROOT/'config/city_catalogs.json')
        self.host_shop.ShopStore(self.path, self.catalogs)
        self.exchange = self.runtime.LoopbackExchange(None, database=self.path,
            open_town_probe=True, observation_seconds=0, owned_pet_probe=False)
        self.exchange.probe_character_id = 42
        self.exchange.probe_character_name = b'Protocol audit'
        self.exchange.quiet = True
        self.exchange.encounters = None  # Exclude independent random combat ticks.
        self.errors = []
        self.server_socket, client = socket.socketpair()
        client.settimeout(3)
        self.peer = Peer(client)
        self.thread = threading.Thread(target=self.run_session)
        self.addCleanup(self.stop_session)
        self.locate(9)
        self.thread.start()
        self.ping()

    def run_session(self):
        try:
            self.exchange.observe_game(self.server_socket,
                InitialFrameReader(InitialCipher('C2S')), InitialCipher('S2C'))
        except BaseException as error:
            self.errors.append(error)
        finally:
            self.server_socket.close()

    def stop_session(self):
        self.exchange.stop()
        self.peer.sock.close()
        self.thread.join(4)
        self.server_socket.close()
        self.assertFalse(self.thread.is_alive(), 'Encrypted session did not stop')
        self.assertEqual(self.errors, [])

    def locate(self, town):
        x, y = center(town) if town in (3,4,9,10) else (0,0)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.exchange.locations._save(db, self.exchange.account, town, x, y)

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            schema = tuple(db.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
            rows = {name: tuple(db.execute('SELECT * FROM "'+name+'"'))
                    for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
        return schema, rows

    def ping(self):
        self.peer.send(b'\x70')
        self.assertEqual(self.peer.until(b'\x9e'), b'\x9e')
        self.assertEqual(self.errors, [])

    def query(self, request):
        self.peer.send(request)
        self.peer.send(b'\x70')
        replies = []
        for _ in range(100):
            packet = self.peer.receive()
            if packet == b'\x9e':
                self.assertEqual(self.errors, [])
                return replies
            replies.append(packet)
        self.fail('Catalogue query lost the following encrypted ping')

    def test_exact_host_candidate_preserves_all_bytes_outside_catalogue_boundary(self):
        source = builder.SOURCE.read_bytes()
        expected, at = builder.patch_source(source)
        actual = builder.TARGET.read_bytes()
        self.assertEqual(actual, expected)
        self.assertEqual(actual[:at], source[:at])
        self.assertEqual(actual[at+len(builder.AFTER):], source[at+len(builder.BEFORE):])

    def test_miners_town_ordinary_and_gold_catalogues_keep_connection_and_saves(self):
        before = self.state()
        for request, prefix in ((b'\x73\0', b'\x74'), (b'\x76'+bytes(4), b'\x77')):
            with self.subTest(request=request.hex()):
                packets = self.query(request)
                selected = [p for p in packets if p.startswith(prefix)]
                self.assertEqual(len(selected), 1)
                self.assertGreater(len(selected[0]), 20)
                self.assertFalse(any(p.startswith(b'\xf0') for p in packets))
                self.assertEqual(self.state(), before)
        self.assertFalse(any(e.get('event') == 'shop_catalog_rejected' for e in self.exchange.events))

    def test_ordinary_and_gold_personal_discount_and_rounding_are_unchanged(self):
        ordinary = decode_item_shop(next(p for p in self.query(b'\x73\0') if p[0] == 0x74))[1]
        self.assertEqual(next(o.unknown_u32_03 for o in ordinary if o.item_id == 301), 150)
        premium.purchase(self.path, self.exchange.account, premium.encode_purchase(1,10))
        before = self.state()
        ordinary = decode_item_shop(next(p for p in self.query(b'\x73\0') if p[0] == 0x74))[1]
        self.assertEqual(next(o.unknown_u32_03 for o in ordinary if o.item_id == 301), 120)
        gold = next(p for p in self.query(b'\x76'+bytes(4)) if p[0] == 0x77)
        count = struct.unpack_from('<I', gold, 14)[0]
        self.assertEqual(len(gold), 18+40*count)
        rows = {struct.unpack_from('<I', gold, 18+40*i+2)[0]:
                struct.unpack_from('<I', gold, 18+40*i+19)[0] for i in range(count)}
        self.assertEqual(rows[304], 5)  # Original6 Gold rounds upward after20% discount.
        self.assertEqual(self.state(), before)

    def test_forbidden_city_catalogues_return_existing_wire_error_without_writes(self):
        expected = shop_error_reply(ValueError('Магазин доступен только в городе'))
        for town in (4,10):
            self.locate(town)
            self.ping()
            for request in (b'\x73\0', b'\x76'+bytes(4)):
                with self.subTest(town=town, request=request.hex()):
                    before = self.state()
                    self.assertIn(expected, self.query(request))
                    self.assertEqual(self.state(), before)
                    self.assertTrue(any(e.get('event') == 'shop_catalog_rejected'
                                        and e.get('request_hex') == request.hex()
                                        for e in self.exchange.events))

    def test_world_map_and_transit_requests_do_not_disconnect_or_modify_saves(self):
        self.locate(-1)
        self.ping()
        for request in (b'\x73\0', b'\x76'+bytes(4)):
            before = self.state()
            packets = self.query(request)
            self.assertTrue(any(p.startswith(b'\xf0') for p in packets))
            self.assertFalse(any(p[0] in (0x74,0x77) for p in packets))
            self.assertEqual(self.state(), before)
        # A frozen active native map journey remains in transit while queries
        # are processed; its normal movement projection need not write SQLite.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO map_journeys(account,x,y,tx,ty,started,arrives) VALUES (?,?,?,?,?,?,?)',
                       (self.exchange.account,0,0,1,1,1000,2000))
        self.exchange.locations.clock = lambda: 1500
        self.ping()
        for request in (b'\x73\0', b'\x76'+bytes(4)):
            before = self.state()
            self.assertTrue(any(p.startswith(b'\xf0') for p in self.query(request)))
            self.assertEqual(self.state(), before)

    def test_malformed_catalogue_requests_fail_closed_and_keep_encrypted_session(self):
        for request in (b'\x73',b'\x73\0\0',b'\x76',b'\x76\0',b'\x76'+bytes(5)):
            with self.subTest(request=request.hex()):
                before = self.state()
                packets = self.query(request)
                self.assertIn(shop_error_reply(ValueError('malformed request')), packets)
                self.assertFalse(any(p[0] in (0x74,0x77) for p in packets))
                self.assertEqual(self.state(), before)
                self.assertTrue(any(e.get('event') == 'shop_catalog_rejected'
                                    and e.get('request_hex') == request.hex()
                                    for e in self.exchange.events))

    def test_domain_rejection_after_valid_parse_uses_same_error_and_keeps_session(self):
        error = self.host_shop.PurchaseRejected('Inventory is full')
        with patch.object(self.host_shop.ShopStore, 'catalog', side_effect=error):
            for request in (b'\x73\0',b'\x76'+bytes(4)):
                before = self.state()
                self.assertIn(shop_error_reply(error), self.query(request))
                self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
