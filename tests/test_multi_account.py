"""Two real TCP clients, including shared-IP/reordered mode1 and account isolation."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import socket
import sqlite3
import tempfile
import threading
import time
import unittest
import errno
from unittest.mock import patch

from server.accounts import Accounts
from server.config import ServerConfig
from server.runtime import Server, ROOT
from test_server_deployment import Peer
from tio.protocol.transport import (decode_initial_challenge, expected_reply_fields,
    InitialReply, encode_initial_reply, decode_initial_completion)
from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list
from tio.protocol.server_login import ServerLoginRequest, encode_server_login_request
from tio.protocol.mode1 import Mode1Reply, encode_mode1_reply, derive_mode1_key
from tio.protocol.character_select import decode_character_list
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info, PetInfo
from tio.owned_pets import OwnedPetStore
from wallet_fixture import fund_wallet

PASSWORD = 'test-only-password-123'


class MultiAccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        with socket.socket() as first, socket.socket() as second:
            first.bind(('127.0.0.1',0));second.bind(('127.0.0.1',0))
            ports = first.getsockname()[1], second.getsockname()[1]
        self.config = ServerConfig('127.0.0.1','127.0.0.1',ports[0],root,'ERROR',True,ports[1])
        self.accounts = Accounts(self.config.database)
        self.accounts.create('alice',PASSWORD,character='Alice')
        self.accounts.create('bob',PASSWORD,character='Bob')
        # Paid-gameplay tests use established funded players, not registration defaults.
        for account in ('alice','bob'):
            fund_wallet(self.config.database,account,credits=10_000,gold=10_000)
        self.clients = []
        self.errors = []
        self.server = None

    def start(self):
        self.server = Server(self.config)
        def run():
            try:self.server.serve()
            except BaseException as error:self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        deadline = time.monotonic()+5
        while self.server.listener is None and not self.errors:
            if time.monotonic()>deadline:raise AssertionError('Startup timeout')
            time.sleep(.01)
        self.assertFalse(self.errors)
        self.addCleanup(self.stop)

    def stop(self):
        if self.server is not None:
            self.server.stop()
            self.thread.join(10)
            self.assertFalse(self.thread.is_alive(),'Shutdown hung')
            self.assertFalse(self.errors)
        for connection in self.clients:connection.close()

    def connect(self,port):
        connection = socket.create_connection(('127.0.0.1',port),timeout=5)
        self.clients.append(connection)
        return connection

    def begin(self, login, password=PASSWORD, denied=False):
        peer = Peer(self.connect(self.config.game_port))
        challenge = decode_initial_challenge(peer.receive())
        previous = expected_reply_fields(challenge)
        peer.send(encode_initial_reply(InitialReply(*previous,0,b'\0'*3)))
        token = decode_initial_completion(peer.receive()).unknown_u32_01
        peer.send(encode_basic_login_request(BasicLoginRequest(login.encode(),password.encode(),transform_auth_value(token))))
        if denied:
            packet=peer.receive()
            self.assertIn(packet,(b'\x04\x03',b'\x04\x07',b'\x04\x0f',b'\x04\x10'))
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
            return packet
        self.assertEqual(peer.receive(),b'\x04\0')
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
        entry = decode_server_list(peer.receive()).entries[0]
        self.last_server_entry=entry
        self.assertEqual(entry.unknown_u16_01,self.config.session_port)
        peer.send(encode_server_login_request(ServerLoginRequest(1,b'\0'*8)))
        self.assertEqual(peer.receive(),b'\x08\0')
        peer.sock.close()
        return previous[1], token

    def test_server_load_counts_unique_accounts_and_releases_disconnects(self):
        from server.multi import MAX_SESSIONS
        self.start()
        alice=self.handoff(self.begin('alice'))
        self.character_screen(alice)
        self.assertEqual((self.last_server_entry.unknown_u16_02,self.last_server_entry.unknown_u16_03),(0,MAX_SESSIONS-1))
        bob=self.handoff(self.begin('bob'))
        self.character_screen(bob)
        self.assertEqual(self.last_server_entry.unknown_u16_02,1)
        self.begin('bob',denied=True)
        self.assertEqual(self.server.multi.server_population(),(2,MAX_SESSIONS))
        bob.sock.close()
        deadline=time.monotonic()+5
        while self.server.multi.server_population()[0]!=1:
            if time.monotonic()>deadline:self.fail('Disconnected account counted online')
            time.sleep(.01)
        self.handoff(self.begin('bob'))
        self.assertEqual(self.last_server_entry.unknown_u16_02,1)

    def test_update_disconnect_reaches_world_and_character_selection_before_eof(self):
        self.start()
        alice = self.handoff(self.begin('alice'))
        self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob'))
        self.character_screen(bob)

        self.server.stop_for_update()

        for peer in (alice, bob):
            self.assertEqual(peer.until(b'\x01'), b'\x01UPGD')
            with self.assertRaises(EOFError):
                peer.receive()

    def test_normal_stop_does_not_send_update_disconnect(self):
        self.start()
        peer = self.handoff(self.begin('alice'))
        self.character_screen(peer)

        self.server.stop()

        with self.assertRaises((EOFError, ConnectionResetError)):
            while True:
                self.assertNotEqual(peer.receive(), b'\x01UPGD')

    def test_busy_auction_tick_retries_and_keeps_game_listener_running(self):
        from tio.sc_auction import SCAuctionStore

        tick = SCAuctionStore.tick
        retried = threading.Event()
        first = True

        def busy_once(store, **kwargs):
            nonlocal first
            if first:
                first = False
                raise sqlite3.OperationalError('database is locked')
            result = tick(store, **kwargs)
            retried.set()
            return result

        with patch.object(SCAuctionStore, 'tick', busy_once):
            self.start()
            self.assertTrue(retried.wait(5))
            for login in ('alice', 'bob'):
                self.character_screen(self.handoff(self.begin(login)))

    def test_busy_mail_expiration_keeps_game_listener_running(self):
        from tio.mail import MailStore

        attempted = threading.Event()
        expire = MailStore.expire

        def expire_while_locked(store):
            with closing(sqlite3.connect(store.path)) as writer, writer:
                writer.execute('BEGIN IMMEDIATE')
                with patch('tio.mail.connect', lambda path: sqlite3.connect(path, timeout=0)):
                    try:
                        return expire(store)
                    finally:
                        attempted.set()

        with patch.object(MailStore, 'expire', expire_while_locked):
            self.start()
            self.assertTrue(attempted.wait(5), 'Mail expiration did not run')
            for login in ('alice', 'bob'):
                self.character_screen(self.handoff(self.begin(login)))

    def test_slow_login_construction_does_not_block_game_listener(self):
        from tools.loopback_exchange import LoopbackExchange
        self.start()
        constructing=threading.Event();release=threading.Event()
        original=LoopbackExchange.__init__
        def delayed_init(exchange,*args,**kwargs):
            constructing.set()
            if not release.wait(5):raise TimeoutError('test constructor release timed out')
            original(exchange,*args,**kwargs)

        def pending_count():
            with self.server.multi.lock:return len(self.server.multi.login_pending)

        def wait_pending(expected):
            deadline=time.monotonic()+5
            while pending_count()!=expected:
                if time.monotonic()>=deadline:self.fail('login admission reservation was not recorded')
                time.sleep(.01)

        with patch.object(LoopbackExchange,'__init__',delayed_init):
            try:
                login=Peer(self.connect(self.config.game_port))
                self.assertTrue(constructing.wait(5),'login constructor was not started')
                queued=[self.connect(self.config.game_port) for _ in range(3)]
                wait_pending(4)
                rejected=self.connect(self.config.game_port)
                rejected.settimeout(3)
                self.assertEqual(rejected.recv(1),b'','per-IP admission cap must include queued constructors')
                game=self.connect(self.config.session_port)
                data=bytearray()
                deadline=time.monotonic()+5
                while len(data)<11:
                    if time.monotonic()>=deadline:self.fail('game listener stalled behind login constructor')
                    part=game.recv(11-len(data))
                    if not part:raise EOFError('No game challenge while login constructor was blocked')
                    data.extend(part)
                self.assertEqual(len(data),11)
            finally:
                release.set()
            self.assertIsNotNone(decode_initial_challenge(login.receive()))

    def handoff(self,key,denied=False):
        connection = self.connect(self.config.session_port)
        raw = bytearray()
        while len(raw)<11:
            chunk = connection.recv(11-len(raw))
            if not chunk:raise EOFError('No mode1 challenge')
            raw.extend(chunk)
        peer = Peer(connection,derive_mode1_key(bytes(raw[3:])))
        peer.send(encode_mode1_reply(Mode1Reply(*key)))
        if denied:
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
            return
        self.assertEqual(peer.receive(),b'\x0b\0')
        return peer

    def character_screen(self,peer,appearance=False):
        peer.send(b'\x0c0.21:63\0\0')
        self.assertEqual(peer.receive(),b'\x0d\0')
        for name_bytes in (b'items',b'skills',b'zones',b'customization',b'premiumaccount',b'services'):
            self.assertTrue(peer.receive().startswith(b'\xb9\x01'))
            peer.send(b'\xb9\x02'+name_bytes+b'\0')
            self.assertTrue(peer.receive().startswith(b'\xb9\x03'))
            peer.send(b'\xb9\x04')
        if appearance:self.assertEqual(peer.receive(),b'\x12\x05')
        return decode_character_list(peer.receive())

    def enter(self,peer,name):
        records = self.character_screen(peer)
        self.assertEqual([r.name_bytes for r in records],[name.encode()])
        peer.send(bytes.fromhex('1701000000'))
        self.assertTrue(peer.receive().startswith(b'\x18'))
        peer.send(b'\x19');peer.until(b'\x66')
        self.ping(peer)

    def ping(self,peer):
        peer.send(b'\x70');self.assertEqual(peer.until(b'\x9e'),b'\x9e')

    def test_native_safe_deposit_reaches_shared_treasury(self):
        from tio.clans import ClansStore
        from tio.db_transaction import transaction
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.warehouse import decode_warehouse_list

        self.start()
        alice = self.handoff(self.begin('alice'))
        self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob'))
        self.enter(bob, 'Bob')
        path = self.config.database
        with transaction(path) as db:
            packet, = db.execute(
                "SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1"
            ).fetchone()
            pet = decode_pet_info(packet, human_equipment=True)
            pet.fields['0x8c4aef'] = 4
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",
                       (encode_pet_info(pet),))
        clan = ClansStore(path)
        clan.create('alice', b'Alpha')
        clan.invite('alice', b'Bob')
        clan.accept('bob', 1)

        deposit = bytes.fromhex('c2020100000002000000000001000100ffffe8030000')
        replies = self.exchange_inventory_requests(bob, [deposit])
        self.assertEqual(clan.info('alice')['credits'], 1000)
        self.assertTrue(any(decode_asset_count(p).credits == 9000
                            for p in replies if p.startswith(b'\xc8\x39')))

        # Bob can deposit with view permission but cannot withdraw the same money.
        withdrawal = bytes.fromhex('6b0201000000000001000100fffff4010000')
        denied = self.exchange_inventory_requests(bob, [withdrawal])
        self.assertTrue(any(p.startswith(b'\xf0\x8a') for p in denied))
        self.assertEqual(clan.info('alice')['credits'], 1000)
        replies = self.exchange_inventory_requests(alice, [withdrawal, b'\x69\x02'])
        safe = [decode_warehouse_list(p)[3] for p in replies if p.startswith(b'\x6a\x02\0\0\0')]
        self.assertTrue(any([(item.template_id, item.count) for item in items] == [(1, 500)]
                            for items in safe))

    def test_native_clan_donation_moves_ammo_from_personal_to_shared_stock(self):
        from tio.clans import ClansStore
        from tio.db_transaction import transaction
        from tio.protocol.item_list import ItemRecord
        from tio.protocol.warehouse import decode_warehouse_list
        from tio.warehouse_completion import stash

        self.start()
        alice = self.handoff(self.begin('alice'))
        self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob'))
        self.enter(bob, 'Bob')
        path = self.config.database
        with transaction(path) as db:
            packet, = db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()
            pet = decode_pet_info(packet, human_equipment=True)
            pet.fields['0x8c4aef'] = 4
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1", (encode_pet_info(pet),))
            ammo = ItemRecord(50001, 7, bytes(2), 20, 0, 0, (0, 0, 0), bytes(4), None, bytes(3))
            stash(db, 'bob', (ammo,), origin='test-clan-donation')
            bag_before, = db.execute("SELECT inventory_packet FROM owned_pets WHERE account='bob' AND pet_id=1").fetchone()
        clan = ClansStore(path)
        clan.create('alice', b'Alpha')
        clan.invite('alice', b'Bob')
        clan.accept('bob', 1)

        donation = bytes.fromhex('c20200000000010000000000010051c300000f000000')
        denied = self.exchange_inventory_requests(alice, [donation])
        self.assertTrue(any(p.startswith(b'\xf0\x8a') for p in denied))
        replies = self.exchange_inventory_requests(bob, [donation])
        self.assertEqual([p.hex() for p in replies if p.startswith(b'\xf0\x8a')], [])
        bins = {kind: items for p in replies if p.startswith(b'\x6a')
                for kind, _, _, items in [decode_warehouse_list(p)]}
        self.assertEqual([(i.instance_id, i.count) for i in bins[0]], [(50001, 5)])
        self.assertEqual([(i.template_id, i.count) for i in bins[1]], [(7, 15)])
        with transaction(path) as db:
            bag_after, = db.execute("SELECT inventory_packet FROM owned_pets WHERE account='bob' AND pet_id=1").fetchone()
        self.assertEqual(bag_before, bag_after)

        replay = self.exchange_inventory_requests(bob, [donation])
        self.assertTrue(any(p.startswith(b'\xf0\x8a') for p in replay))
        replies = self.exchange_inventory_requests(alice, [b'\x69\x01'])
        shared = [decode_warehouse_list(p)[3] for p in replies if p.startswith(b'\x6a\x01\0\0\0')]
        self.assertEqual(shared[-1], bins[1])

    def test_native_clan_repair_uses_shared_stock_and_safe_balance(self):
        from tio.clans import ClansStore, DEFAULT_RIGHTS, WITHDRAW_REPAIR
        from tio.db_transaction import transaction
        from tio.protocol.item_list import ItemRecord, encode_item_list
        from tio.protocol.warehouse import decode_warehouse_list
        from tio.warehouse import WarehouseStore
        from tio.warehouse_completion import stash

        self.start()
        alice = self.handoff(self.begin('alice'))
        self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob'))
        self.enter(bob, 'Bob')
        path = self.config.database
        kit = ItemRecord(51001, 17, bytes(2), 1, 0, 0, (600, 600, 600), bytes(4), None, bytes(3))
        coat = ItemRecord(51002, 222, bytes(2), 1, 0, 0, (100, 180, 180), bytes(4), None, bytes(3))
        with transaction(path) as db:
            raw, = db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()
            pet = decode_pet_info(raw, human_equipment=True)
            pet.fields['0x8c4aef'] = 4
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1", (encode_pet_info(pet),))
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice' AND pet_id=1", (encode_item_list(1, (coat,)),))
            stash(db, 'alice', (kit,), origin='test-clan-repair')
        clan = ClansStore(path)
        clan.create('alice', b'Alpha')
        clan.invite('alice', b'Bob')
        clan.accept('bob', 1)
        clan.exchange('alice', 1, 1, deposits=((coat.instance_id, 1),))
        self.exchange_inventory_requests(alice, [bytes.fromhex('c2020100000002000000000001007300ffff58020000')])
        self.assertEqual(clan.info('bob')['repair'], 600)
        self.assertEqual(WarehouseStore(path).items('alice'), ())

        repair = bytes.fromhex('c2030100000000000040')
        denied = self.exchange_inventory_requests(bob, [repair])
        self.assertTrue(any(p.startswith(b'\xf0\x8a') for p in denied))
        clan.permissions('alice', clan.info('bob')['member_id'], DEFAULT_RIGHTS | WITHDRAW_REPAIR, 0)
        replies = self.exchange_inventory_requests(bob, [repair, repair])
        self.assertTrue(any(p.startswith(b'\xf0\x70') for p in replies))
        self.assertTrue(any(any(i.durability == 178 for i in decode_warehouse_list(p)[3])
                            for p in replies if p.startswith(b'\x6a\x01\0\0\0')))
        self.assertEqual(clan.items('alice', 1)[0].unknown_words, (178, 178, 180))
        self.assertEqual(clan.info('alice')['repair'], 522)
        self.exchange_inventory_requests(bob, [bytes.fromhex('6b0201000000000001007300ffff0a020000')])
        self.assertEqual([i.unknown_words[0] for i in WarehouseStore(path).items('bob')], [522])
        self.assertEqual(clan.info('alice')['repair'], 0)

    def test_private_bank_commands_shared_securities_replay_and_no_peer_broadcast(self):
        from tio.db_transaction import transaction
        from tio.bank_economy import stock_quote
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        with transaction(self.config.database) as db:price=stock_quote(db)['price']
        def ask(peer,text=None):
            if text is not None:peer.send(b'\x21\0'+text.encode('utf-16le')+b'\0\0')
            peer.send(b'\x70');packets=[]
            for _ in range(2048):
                packet=peer.receive()
                if packet==b'\x9e':return packets
                packets.append(packet)
            self.fail('Missing native bank ping acknowledgement')
        text=f'!bank stocks buy 2 {price} bank_transport_buy_0001'
        replies=ask(alice,text)
        self.assertTrue(any(p.startswith(b'\x22') and b'Bank\0' in p for p in replies))
        def state():
            with closing(sqlite3.connect(self.config.database)) as db:
                return db.execute("SELECT credits,gold FROM wallets WHERE account='alice'").fetchone(),db.execute("SELECT stocks FROM bank_securities WHERE account='alice'").fetchone()
        first=state();self.assertEqual(first,((10000-2*price,10000),(2,)))
        ask(alice,text);self.assertEqual(state(),first)
        other=ask(bob)
        self.assertFalse(any(p.startswith(b'\x22') and b'Bank\0' in p for p in other))
        ask(alice,f'!bank stocks sell 2 {price} bank_transport_sell_0001')
        self.assertEqual(state(),((10000,10000),(0,)))
        private=[event for session in self.server.multi.active_accounts.values() for event in session.events
                 if '<private economy command>' in event.get('packets_hex',())]
        self.assertGreaterEqual(len(private),3)
        self.assertTrue(all(event['raw_hex'] is None for event in private))

    def test_hire_market_stale_inventory_lookups_do_not_flood_chat(self):
        from tio.protocol.city_catalogs import decode_pet_shop
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        alice.send(b'\x61')
        candidates=decode_pet_shop(alice.until(b'\x62'))
        self.assertTrue(candidates)

        for owner in range(0xfffffff0,0xfffffffa):
            alice.send(b'\x2f\x01\0'+owner.to_bytes(4,'little'))
        alice.send(b'\x70')
        replies=[]
        while True:
            packet=alice.receive()
            if packet==b'\x9e':break
            replies.append(packet)
        self.assertFalse([packet for packet in replies if packet.startswith(b'\xf0')],
                         'stale read-only inventory lookups must not create chat errors')

        empty_replies=self.exchange_inventory_requests(alice,[b'\x2f\0\0']*6)
        self.assertFalse([packet for packet in empty_replies if packet.startswith(b'\xf0')],
                         'empty read-only inventory lookups must not create chat errors')

        replies=self.exchange_inventory_requests(alice,[b'\x2f\x01\0\x01\0\0\0'])
        self.assertTrue(any(packet.startswith(b'\x30') and decode_item_list(packet)[0]==1
                            for packet in replies), 'existing owner inventory still responds')

    def exchange_inventory_requests(self,peer,requests):
        for request in requests:peer.send(request)
        peer.send(b'\x70');replies=[]
        while True:
            packet=peer.receive()
            if packet==b'\x9e':return replies
            replies.append(packet)

    def test_premium_purchase_and_personal_shop_prices(self):
        from tio.premium import encode_purchase
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.city_catalogs import decode_item_shop
        self.start()
        a=self.handoff(self.begin('alice'));self.enter(a,'Alice')
        b=self.handoff(self.begin('bob'));self.enter(b,'Bob')
        a.send(encode_purchase(1,10));assets=decode_asset_count(a.until(b'\xc8\x39'))
        self.assertEqual(assets.gold,9990)
        self.assertEqual(assets.optional_raw[1],1)
        self.assertTrue(86390<=assets.optional_raw[0]<=86400)
        for peer,price in ((a,120),(b,150)):
            peer.send(b'\x73\0')
            offers=decode_item_shop(peer.until(b'\x74'))[1]
            self.assertEqual(next(o.unknown_u32_03 for o in offers if o.unknown_u32_01==81),price)
        a.send(encode_purchase(1,10));self.assertEqual(decode_asset_count(a.until(b'\xc8\x39')).gold,9990)

    def test_services_and_shared_player_auction(self):
        from test_services import request
        from test_player_auction import create_packet
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.binary import Reader,Writer
        from tio.protocol.warehouse import decode_warehouse_list
        from tio.warehouse import WarehouseStore
        from tio.wallets import WalletStore
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text(encoding='utf-8'))
        item=replace(decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0],
                     instance_id=123,unknown_u32_01=1,unknown_u8_01=0,location_raw=0,
                     unknown_bytes_02=bytes(4),optional_u32=None)
        WarehouseStore(self.config.database)
        with closing(sqlite3.connect(self.config.database)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',123,encode_item_list(0,(item,))))
        self.start()
        a=self.handoff(self.begin('alice'));self.enter(a,'Alice')
        b=self.handoff(self.begin('bob'));self.enter(b,'Bob')
        a.send(request(service=2));a.until(b'\xb1\x01')
        self.assertEqual(decode_asset_count(a.until(b'\xc8\x39')).credits,8000)
        a.send(create_packet(instance=123));self.assertEqual(a.until(b'\xc8\x0c'),b'\xc8\x0c\x01\0\0\0')
        added=Reader(a.until(b'\xc8\x03')[2:]);self.assertEqual(added.u32(),1);lot=added.u32()
        listing=Writer().u8(0xc8).u8(8).u32(0).u32(77).u8(0).u8(0).u32(1).build()
        b.send(listing);record=Reader(b.until(b'\xc8\x09')[2:])
        self.assertEqual((record.u32(),record.u32(),record.u32(),record.u32(),record.u32()),(77,1,1,1,lot))
        b.send(Writer().u8(0xc8).u8(14).u32(lot).build())
        b.until(b'\xc8\x04')
        self.assertEqual(decode_asset_count(b.until(b'\xc8\x39')).credits,7000)
        goods=decode_warehouse_list(b.until(b'\x6a'))[3]
        self.assertEqual([i.template_id for i in goods],[item.template_id])
        deadline=time.monotonic()+5
        while WalletStore(self.config.database).ensure('alice').credits!=11000:
            if time.monotonic()>deadline:self.fail('Seller settlement missing')
            time.sleep(.05)
        self.assertEqual(len(WarehouseStore(self.config.database).items('bob')),1)
        a.send(Writer().u8(0xc8).u8(14).u32(lot).build());a.until(b'\xf0\x8a\x01\0\0')
        self.assertEqual(WalletStore(self.config.database).ensure('alice').credits,11000)

    def test_new_accounts_create_retry_select_customize_and_relogin(self):
        from tio.protocol.character_create import CharacterCreateRequest,encode_character_create
        from tio.appearance import encode_request,appearance_bytes
        self.accounts.create('new_alice',PASSWORD)
        self.accounts.create('new_bob',PASSWORD)
        self.start()
        peers=[self.handoff(self.begin(account)) for account in ('new_alice','new_bob')]
        for peer in peers:
            self.assertEqual(self.character_screen(peer),())
            self.ping(peer)
        def create(peer,name,sex):
            peer.send(encode_character_create(CharacterCreateRequest(name,0,(sex,0,0,0))))
            return peer.receive()
        self.assertEqual(create(peers[0],b'1',1),b'\x12\x04')
        self.assertEqual(create(peers[0],b'NewAlice',1),b'\x12\x05')
        self.assertEqual(decode_character_list(peers[0].receive())[0].resource_type,1)
        self.assertEqual(create(peers[1],b'newalice',2),b'\x12\x03')
        self.assertEqual(create(peers[1],b'NewBob',2),b'\x12\x05')
        self.assertEqual(decode_character_list(peers[1].receive())[0].resource_type,2)
        self.assertEqual(create(peers[0],b'Another',1),b'\x12\x02')
        exchange=self.server.multi.active_accounts['new_alice']
        peers[0].sock.close();exchange.thread.join(5)
        peers[0]=self.handoff(self.begin('new_alice'))
        self.assertEqual(self.character_screen(peers[0],appearance=True)[0].name_bytes,b'NewAlice')
        for peer,sex in zip(peers,(1,2)):
            # Cannot enter before confirming appearance, including default look.
            peer.send(bytes.fromhex('1701000000'))
            self.assertEqual(peer.receive(),b'\x12\x05')
            self.assertEqual(peer.receive()[0],0x10)
            peer.send(encode_request(1,bytes((sex,0 if sex==1 else 8,0,1,0,0))))
            self.assertEqual(peer.until(b'\x10')[0],0x10)
            peer.send(bytes.fromhex('1701000000'))
            self.assertTrue(peer.receive().startswith(b'\x18'))
            peer.send(b'\x19')
            pet=decode_pet_info(peer.until(b'\x66'),human_equipment=True)
            self.assertEqual(pet.fields['0x8c446f'],sex)
            self.ping(peer)
            # Fresh native characters now enter the authoritative introduction.
            # This appearance test leaves it using the normal client action.
            peer.send(b'\x36');self.ping(peer)
            peer.send(b'\x2a\x01');self.ping(peer)
            # 9E is also an unsolicited heartbeat, so it cannot identify this
            # ping's reply or flush the city roster that follows scene exit.
            # B103 is a city-only, request-specific service-list barrier.
            from tio.protocol.city_catalogs import decode_service_shop
            peer.send(b'\xb1\x02')
            self.assertTrue(decode_service_shop(peer.until(b'\xb1\x03')))
        look=bytes((2,12,0,4,0,0))
        peers[1].send(encode_request(1,look))
        # The customization's F0/138 acknowledges its contiguous 66 + assets
        # response. Periodic snapshots may precede it; an unrelated matching
        # PetInfo does not count as a successful customization response.
        replies=[]
        haircut_ack=bytes.fromhex('f08a00000000000000')
        for _ in range(100):
            reply=peers[1].receive();replies.append(reply)
            if reply==haircut_ack:break
        else:self.fail('Native haircut acknowledgement was not received')
        self.assertGreaterEqual(len(replies),3)
        self.assertEqual(replies[-3][:1],b'\x66')
        self.assertEqual(replies[-2][:2],b'\xc8\x39')
        refreshed=decode_pet_info(replies[-3],human_equipment=True)
        self.assertEqual(refreshed.fields['0x8c43eb'],1)
        self.assertEqual(appearance_bytes(refreshed),look)
        self.ping(peers[1])
        exchange=self.server.multi.active_accounts['new_bob']
        peers[1].sock.close();exchange.thread.join(5)
        restored=self.handoff(self.begin('new_bob'))
        records=self.character_screen(restored)
        self.assertEqual(records[0].optional_six,look)
        restored.send(bytes.fromhex('1701000000'));restored.receive();restored.send(b'\x19')
        self.assertEqual(appearance_bytes(decode_pet_info(restored.until(b'\x66'),human_equipment=True)),look)
        self.ping(restored);self.ping(peers[0])

    def test_empty_account_cannot_forge_world_entry(self):
        self.accounts.create('empty_user',PASSWORD)
        self.start();peer=self.handoff(self.begin('empty_user'))
        self.assertEqual(self.character_screen(peer),())
        peer.send(bytes.fromhex('1701000000'))
        with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
        self.assertEqual(OwnedPetStore(self.config.database).list('empty_user'),())

    def test_dead_connection_releases_only_its_account_and_allows_relogin(self):
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        multi=self.server.multi
        with multi.lock:
            exchange=multi.active_accounts['alice']
        game=exchange.connections[-1]
        self.assertEqual(game.getsockopt(socket.SOL_SOCKET,socket.SO_KEEPALIVE),1)
        if hasattr(socket,'TCP_KEEPIDLE'):
            self.assertEqual(game.getsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPIDLE),60)
            self.assertEqual(game.getsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPINTVL),15)
            self.assertEqual(game.getsockopt(socket.IPPROTO_TCP,socket.TCP_KEEPCNT),4)
        original_recv=socket.socket.recv
        polling_seen=threading.Event()
        fatal=threading.Event()
        def receive(connection,*args,**kwargs):
            if connection is game:
                if fatal.is_set():
                    raise TimeoutError(errno.ETIMEDOUT,'Simulated dead TCP peer')
                if not polling_seen.is_set():
                    polling_seen.set()
                    raise socket.timeout('Normal polling deadline')
            return original_recv(connection,*args,**kwargs)
        with patch.object(socket.socket,'recv',receive):
            self.assertTrue(polling_seen.wait(5))
            self.ping(alice)  # Healthy idle clients survive polling timeouts.
            self.begin('alice',denied=True)  # Live-session exclusion remains.
            fatal.set()
            exchange.thread.join(5)
            self.assertFalse(exchange.thread.is_alive(),'Dead account was not released')
        with multi.lock:
            self.assertNotIn('alice',multi.active_accounts)
            self.assertIn('bob',multi.active_accounts)
        self.ping(bob)
        restored=self.handoff(self.begin('alice'));self.enter(restored,'Alice')
        self.ping(restored)

    def test_reversed_handoffs_same_ip_isolation_and_restart(self):
        self.start()
        alice_key = self.begin('alice')
        bob_key = self.begin('bob')
        self.assertNotEqual(alice_key,bob_key)
        self.handoff((alice_key[0],bob_key[1]),denied=True)
        bob = self.handoff(bob_key);self.enter(bob,'Bob')
        alice = self.handoff(alice_key);self.enter(alice,'Alice')
        self.handoff(alice_key,denied=True)  # Consumed token cannot be replayed.
        alice.send(encode_shop_purchase(ShopPurchase(1,0,81,2)))
        alice.until(b'\xc8\x39');alice.until(b'\xb5\x03');alice.until(b'\xc8\x39')
        alice.send(b'\x2f\x01\0\x01\0\0\0');own = decode_item_list(alice.until(b'\x30'))[1]
        bob.send(b'\x2f\x01\0\x01\0\0\0');other = decode_item_list(bob.until(b'\x30'))[1]
        self.assertNotEqual(own,other)
        with closing(sqlite3.connect(self.config.database)) as db:
            wallets = dict(db.execute('SELECT account,credits FROM wallets'))
            self.assertEqual(wallets,{'alice':9800,'bob':10000})
            snapshots = list(db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets ORDER BY account,pet_id'))
        # Third-party actor is present only under Bob, never readable by Alice.
        fixture = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        pet = decode_pet_info(bytes.fromhex(fixture['packet_hex']),human_equipment=True)
        extra = encode_pet_info(PetInfo(True,{**pet.fields,'0x8c43eb':77}))
        OwnedPetStore(self.config.database).ensure('bob',extra,encode_item_list(77,()),human=True)
        alice.send(b'\x2f\x01\0'+(77).to_bytes(4,'little'))
        self.assertTrue(alice.until(b'\xf0').startswith(b'\xf0'))
        self.ping(bob)
        self.stop();self.start()
        restored = self.handoff(self.begin('alice'));self.enter(restored,'Alice')
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(dict(db.execute('SELECT account,credits FROM wallets')),wallets)
            self.assertEqual(list(db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets WHERE pet_id=1 ORDER BY account,pet_id')),snapshots)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_city_weapon_swap_tcp_persists_and_is_account_isolated(self):
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        store=OwnedPetStore(self.config.database)
        before_bob=store.inventory('bob',1)
        original=store.inventory('alice',1)
        owner,items,unknown=decode_item_list(original)
        sample=items[0]
        seed=encode_item_list(owner,(replace(sample,instance_id=9001,template_id=301,
                                            unknown_u32_01=1,unknown_u8_01=1,location_raw=16),
                                    replace(sample,instance_id=9002,template_id=303,
                                            unknown_u32_01=1,unknown_u8_01=1,location_raw=128)),unknown)
        with closing(sqlite3.connect(self.config.database)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(seed,'alice',owner))
        packet=b'\x6d'+owner.to_bytes(4,'little')
        for expected in ((128,16),(16,128)):
            alice.send(packet)
            response=alice.until(b'\x30')
            self.assertEqual(tuple(i.client_slot for i in decode_item_list(response)[1]),expected)
            self.assertEqual(store.inventory('alice',owner),response)
            self.assertEqual(store.inventory('bob',1),before_bob)
        self.assertEqual(store.inventory('alice',owner),seed)
        self.ping(alice);self.ping(bob)

    def test_city_exchange_moves_worn_armor_to_owned_backpack(self):
        from tio.protocol.battle_exchange import BattleExchange, encode_exchange

        self.start()
        alice = self.handoff(self.begin('alice')); self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob')); self.enter(bob, 'Bob')
        store = OwnedPetStore(self.config.database)
        before_bob = store.inventory('bob', 1)
        before_alice = store.inventory('alice', 1)
        owner, items, flag = decode_item_list(before_alice)
        armor = replace(items[0], instance_id=9001, template_id=264, unknown_u32_01=1,
                        unknown_u8_01=1, location_raw=4, unknown_words=(211, 400, 500),
                        unknown_bytes_03=bytes((3, 0, 1)))
        with closing(sqlite3.connect(self.config.database)) as db:
            raw, = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                              ('alice', owner)).fetchone()
        pet = decode_pet_info(raw, human_equipment=True)
        pet.fields.update({'0x8c43eb': 2, '0x8c44a6': 2, '0x8c446f': 2, '0x8c4aef': 5})
        donor = encode_item_list(2, (armor,), flag)
        store.ensure('alice', encode_pet_info(pet), donor, human=True)

        request = encode_exchange(BattleExchange(owner, 2, withdrawals=((armor.instance_id, 1),)))
        replies = self.exchange_inventory_requests(alice, [request])
        self.assertEqual(store.inventory('alice', 2), encode_item_list(2, (), flag))
        expected = encode_item_list(owner, (*items, replace(armor, unknown_u8_01=0, location_raw=0)), flag)
        self.assertEqual(store.inventory('alice', owner), expected)
        self.assertIn(expected, replies)
        self.assertIn(store.inventory('alice', 2), replies)
        self.assertEqual(store.inventory('bob', 1), before_bob)
        self.exchange_inventory_requests(alice, [request])
        self.assertEqual(store.inventory('alice', owner), expected)
        self.ping(bob)

    def test_bad_password_duplicate_login_and_reconnect_do_not_affect_other_player(self):
        self.start()
        bob = self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        with closing(sqlite3.connect(self.config.database)) as db:
            credentials_before=db.execute('SELECT * FROM accounts ORDER BY login').fetchall()
            characters_before=db.execute('SELECT * FROM characters ORDER BY account,slot').fetchall()
        with self.assertLogs('tio.server',level='WARNING') as logs:
            self.assertEqual(self.begin('alice','wrong-password',denied=True),b'\x04\x03')
            self.assertEqual(self.begin('unknown',denied=True),b'\x04\x03')
            self.assertEqual(self.begin('bob',denied=True),b'\x04\x07')
        self.assertTrue(any('category=credentials requested_login=alice' in line for line in logs.output))
        self.assertTrue(any('category=already-connected requested_login=bob' in line for line in logs.output))
        self.assertNotIn('wrong-password','\n'.join(logs.output))
        self.assertNotIn(PASSWORD,'\n'.join(logs.output))
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM accounts ORDER BY login').fetchall(),credentials_before)
            self.assertEqual(db.execute('SELECT * FROM characters ORDER BY account,slot').fetchall(),characters_before)
        self.ping(bob)
        alice = self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        alice.sock.close()
        deadline = time.monotonic()+5
        while 'alice' in self.server.multi.active_accounts:
            if time.monotonic()>deadline:raise AssertionError('Account not released')
            time.sleep(.02)
        self.ping(bob)
        self.enter(self.handoff(self.begin('alice')),'Alice')

    def test_unsupported_login_logs_opcode_without_credentials(self):
        self.start()
        peer=Peer(self.connect(self.config.game_port))
        challenge=decode_initial_challenge(peer.receive())
        peer.send(encode_initial_reply(InitialReply(*expected_reply_fields(challenge),0,b'\0'*3)))
        decode_initial_completion(peer.receive())
        private_packet=b'\x0aalice\0private-test-password\0'+b'\0'*4+b'affiliate\0'
        with self.assertLogs('tio.server',level='WARNING') as logs:
            peer.send(private_packet)
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
        text='\n'.join(logs.output)
        self.assertIn('category=protocol requested_login=<unparsed> opcode=10 transport=direct',text)
        self.assertNotIn('private-test-password',text)
        self.assertNotIn(private_packet.hex(),text)
        self.assertNotIn('affiliate',text)

    def test_unexpected_authorization_error_is_not_a_native_credentials_denial(self):
        self.start()
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        peer=Peer(self.connect(self.config.game_port))
        challenge=decode_initial_challenge(peer.receive())
        peer.send(encode_initial_reply(InitialReply(*expected_reply_fields(challenge),0,b'\0'*3)))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        with patch.object(self.server.multi.accounts,'verify',side_effect=ValueError('Injected internal error')):
            peer.send(encode_basic_login_request(BasicLoginRequest(b'alice',PASSWORD.encode(),transform_auth_value(token))))
            # A programming/storage error must not be relabeled as wrong credentials.
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
        self.ping(bob)

    def test_password_storage_reset_and_existing_save_preserved(self):
        self.assertEqual(self.accounts.verify(b'alice',PASSWORD.encode()),'alice')
        with closing(sqlite3.connect(self.config.database)) as db:
            before = db.execute('SELECT * FROM characters WHERE account=?',('alice',)).fetchall()
            salts = list(db.execute('SELECT salt,digest FROM accounts'))
        self.assertNotEqual(salts[0],salts[1])
        self.assertNotIn(PASSWORD.encode(),self.config.database.read_bytes())
        self.accounts.create('alice','changed-test-password',reset=True)
        with self.assertRaises(ValueError):self.accounts.verify(b'alice',PASSWORD.encode())
        with self.assertRaises(ValueError):self.accounts.create('alice',PASSWORD,character='Another')
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM characters WHERE account=?',('alice',)).fetchall(),before)
        self.assertEqual(self.accounts.verify(b'alice',b'changed-test-password'),'alice')

    def test_stop_during_pending_login_and_partial_game_handshake(self):
        self.start()
        self.begin('alice')
        self.connect(self.config.session_port).recv(11)
        self.stop()

    def test_failed_provision_is_atomic(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.accounts.create('charlie',PASSWORD,character='Alice')
        with self.assertRaises(ValueError):self.accounts.verify(b'charlie',PASSWORD.encode())

    def test_two_tcp_players_share_team_match_and_turns(self):
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_soldier import decode_battle_soldier
        from tio.protocol.battle_turn import encode_end_turn
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        request=encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0))
        for peer in (alice,bob):
            peer.send(request);peer.until(b'\x25')
            peer.send(b'\x2e')
        own=[]
        for peer in (alice,bob):
            ids=[]
            for _ in range(100):
                packet=peer.receive()
                if packet==b'\x41':break
                if packet[:1]==b'\x3b':
                    actor=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                    if actor.owner_id==1:ids.append(actor.soldier_id)
            else:self.fail('No shared scene end')
            self.assertEqual(len(ids),1)
            own.append(ids[0])
            peer.send(b'\x36')
        self.assertNotEqual(own[0],own[1])
        alice.until(b'\x38')
        alice.send(encode_end_turn(own[0]))
        bob.until(b'\x38')
        self.ping(alice);self.ping(bob)
        self.stop()
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone()[0],2)

    def test_wall_two_humans_six_bots_repeat_skip_and_timeout(self):
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_soldier import decode_battle_soldier
        from tio.protocol.battle_turn import encode_end_turn
        self.start()
        peers=[];actors=[]
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=self.handoff(self.begin(account));self.enter(peer,name);peers.append(peer)
            peer.send(encode_create_request(ArenaCreateRequest(4,0,8,2,40,1,1,0,0)))
            peer.until(b'\x25');peer.send(b'\x2e')
        for peer in peers:
            own=[]
            for _ in range(150):
                packet=peer.receive()
                if packet==b'\x41':break
                if packet[:1]==b'\x3b':
                    actor=decode_battle_soldier(packet,human_equipment=int.from_bytes(packet[9:13],'little') in (1,2,6))
                    if actor.owner_id==1:own.append(actor.soldier_id)
            else:self.fail('No wall scene completion')
            self.assertEqual(len(own),1);actors.append(own[0]);peer.send(b'\x36')
        # Original button can send either zero or the selected owned soldier.
        for cycle in range(3):
            for peer,actor in zip(peers,actors):
                # Six AI turns now contain native movement/attack events,
                # instead of eight final-coordinate snapshots per bot.
                peer.until(b'\x38',max_packets=2048)
                peer.send(encode_end_turn(actor if cycle%2 else 0))
                self.assertEqual(peer.until(b'\x39'),b'\x39')
        peers[0].until(b'\x38',max_packets=2048)
        hub=self.server.multi.team_arena
        with hub.lock:
            battle=next(iter(hub.battles.values()));arena=battle['arena'];room=battle['room']
            turn=arena._turns[room.room_id]
            arena._turns[room.room_id]=(turn[0],turn[1],time.monotonic()-1)
        peers[0].until(b'\x39',max_packets=2048);peers[1].until(b'\x38',max_packets=2048)
        self.ping(peers[0]);self.ping(peers[1])

    def test_private_chat_waits_for_town_after_battle(self):
        from tio.protocol.arena import ArenaCreateRequest, encode_create_request
        from tio.protocol.chat import encode_message
        from tio.protocol.system_message import encode_open_town_view

        self.start()
        alice = self.handoff(self.begin('alice')); self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob')); self.enter(bob, 'Bob')
        request = encode_create_request(ArenaCreateRequest(1, 0, 4, 2, 40, 1, 1, 0, 0))
        for peer in (alice, bob):
            peer.send(request); peer.until(b'\x25'); peer.send(b'\x2e')
        for peer in (alice, bob):
            peer.until(b'\x41', max_packets=512)
        lines = ('Во время боя', 'На экране результатов')
        expected = [encode_message(1, b'Bob', line) for line in lines]

        def send(line):
            bob.send(b'\x21\1' + line.encode('utf-16-le') + b'\0\0Alice\0')
            # A presence roster confirms that the preceding chat was processed.
            bob.send(b'\xc7\1'); bob.until(b'\xc7\2', max_packets=512)

        def read_until(peer, prefix):
            received = []
            for _ in range(1024):
                packet = peer.receive()
                if packet.startswith(prefix):
                    return received
                if packet in expected:
                    received.append(packet)
            self.fail('Missing response ' + prefix.hex())

        send(lines[0])
        hub = self.server.multi.team_arena
        with hub.lock:
            session = self.server.multi.active_accounts['alice']
            owner = hub.identities[session]
            battle = hub.battles[owner]
            field = battle['field']
            for identity, actor in tuple(field._actors.items()):
                if field.side(actor.owner_id) != field.side(owner):
                    field._actors[identity] = replace(actor, health=0)
            hub.finish(battle)
        self.assertEqual(read_until(alice, b'\x4c'), [])
        bob.until(b'\x4c', max_packets=512)
        send(lines[1])
        alice.send(b'\x2a\x01')
        self.assertEqual(read_until(alice, encode_open_town_view()), [])
        # Presence still drains while native city controls are loading.
        alice.send(b'\xc7\1')
        self.assertEqual(read_until(alice, b'\xc7\2'), [])
        alice.send(b'\x50\x03')
        self.assertEqual(alice.until(b'\x22', max_packets=512), expected[0])
        self.assertEqual(alice.until(b'\x22', max_packets=512), expected[1])
        alice.send(b'\x50\x03'); alice.send(b'\xb1\x02')
        self.assertEqual(read_until(alice, b'\xb1\x03'), [])
        bob.send(b'\xc7\1')
        self.assertEqual(read_until(bob, b'\xc7\x02'), [])

    def test_two_tcp_clients_presence_chat_and_leave(self):
        self.start()
        alice=self.handoff(self.begin('alice'));self.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob'));self.enter(bob,'Bob')
        alice.send(b'\xc7\1');alice.until(b'\xc7\4')
        listing=alice.until(b'\xc7\2')
        self.assertIn(b'Alice\0',listing);self.assertIn(b'Bob\0',listing)
        local=alice.until(b'\x4f')
        self.assertIn(b'Alice\0',local);self.assertIn(b'Bob\0',local)
        from tio.protocol.chat import encode_message
        for channel in (0,6,8,12):
            self.ping(alice)
            text=f'Привет, канал {channel}!'
            alice.send(bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0')
            expected=encode_message(channel,b'Alice',text)
            self.assertEqual(bob.until(b'\x22'),expected)
            for peer,label in ((alice,'sender'),(bob,'recipient')):
                timeout=peer.sock.gettimeout();peer.sock.settimeout(.05)
                try:
                    deadline=time.monotonic()+.2
                    while time.monotonic()<deadline:
                        try:packet=peer.receive()
                        except socket.timeout:break
                        self.assertFalse(packet.startswith(b'\x22'),f'Shared chat message repeated for {label}')
                finally:peer.sock.settimeout(timeout)
        alice.send(b'\x68\0Bob\0')
        profile=alice.until(b'\xa7\0')
        self.assertIn(b'Bob\0',profile);self.assertNotIn(b'Alice\0',profile)
        self.assertNotIn(PASSWORD.encode(),profile)
        bob.sock.close()
        deadline=time.monotonic()+5
        while True:
            listing=alice.until(b'\xc7\2')
            if b'Bob\0' not in listing:break
            if time.monotonic()>deadline:self.fail('Disconnected player still listed')

    def test_three_tcp_clients_rosters_and_travel(self):
        from tio.locations import LocationStore,center
        import struct
        self.accounts.create('carol',PASSWORD,character='Carol')
        # This fixture provisions an existing character, so provision its
        # wallet explicitly; login must never repair a missing saved wallet.
        fund_wallet(self.config.database,'carol',credits=3_000,gold=0)
        locations=LocationStore(self.config.database)
        with closing(sqlite3.connect(self.config.database)) as db,db:
            locations._save(db,'carol',9,*center(9))
        self.start()
        peers=[]
        for name in ('Alice','Bob','Carol'):
            peer=self.handoff(self.begin(name.lower()));self.enter(peer,name);peers.append(peer)
        alice,bob,carol=peers

        def snapshot(peer):
            self.ping(peer)  # Discard older unsolicited snapshots before request.
            peer.send(b'\xc7\1');peer.until(b'\xc7\4')
            global_list=peer.until(b'\xc7\2');peer.until(b'\x51')
            return global_list,peer.until(b'\x4f')

        for peer in peers:
            global_list,local=snapshot(peer)
            for name in (b'Alice\0',b'Bob\0',b'Carol\0'):self.assertIn(name,global_list)
            self.assertEqual(b'Carol\0' in local,peer is carol)
        with patch('tio.locations.MAP_SPEED',10000):
            bob.send(b'\x1b'+struct.pack('<ii',*center(9)))
            bob.until(b'\xf0\x61\0\0\0')  # Leave city.
            bob.until(b'\xc8\x2d')  # Arrival / town info.
        deadline=time.monotonic()+5
        while True:
            global_list,local=snapshot(carol)
            if b'Bob\0' in local:break
            if time.monotonic()>deadline:self.fail('Arrival roster not updated')
            time.sleep(.1)
        self.assertNotIn(b'Bob\0',snapshot(alice)[1])
        self.assertIn(b'Bob\0',snapshot(alice)[0])
        bob.sock.close()
        deadline=time.monotonic()+5
        while True:
            if b'Bob\0' not in snapshot(alice)[0]:break
            if time.monotonic()>deadline:self.fail('Global disconnect not delivered to another town')
            time.sleep(.1)

    def test_full_repair_bag_rejection_keeps_both_tcp_clients_connected(self):
        import struct
        from tio.db_transaction import transaction
        from tio.inventory_capacity import INVENTORY_SLOTS
        from tio.protocol.item_list import ItemRecord

        self.start()
        alice = self.handoff(self.begin('alice')); self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob')); self.enter(bob, 'Bob')
        gear = ItemRecord(9001, 301, bytes(2), 1, 1, 16, (50, 350, 350),
                          bytes(4), None, bytes(3))
        kit = ItemRecord(5, 17, bytes(2), 2, 0, 0, (600, 600, 600),
                         bytes(4), None, bytes(3))
        fillers = tuple(replace(kit, instance_id=100 + i, template_id=317,
                                unknown_u32_01=1, unknown_words=(1, 1, 1))
                        for i in range(INVENTORY_SLOTS - 2))
        alice_inventory = encode_item_list(1, (gear, kit, *fillers))
        bob_inventory = encode_item_list(1, (gear, replace(kit, unknown_u32_01=1)))
        with transaction(self.config.database) as db:
            db.executemany('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                           ((alice_inventory, 'alice'), (bob_inventory, 'bob')))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                       'DO UPDATE SET next_id=excluded.next_id', ('alice', 9600))

        request = b'\xc2\x03' + struct.pack('<II', 1, 9001)
        alice.send(request)
        refusal = alice.until(b'\xf0\x8a\x01\x00\x00')
        self.assertIn('Inventory is full'.encode('utf-16-le'), refusal)
        self.ping(alice); self.ping(bob)
        store = OwnedPetStore(self.config.database)
        self.assertEqual(store.inventory('alice', 1), alice_inventory)
        self.assertEqual(store.inventory('bob', 1), bob_inventory)
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('SELECT next_id FROM item_sequences WHERE account=?',
                                        ('alice',)).fetchone()[0], 9600)

        bob.send(request)
        repaired = decode_item_list(bob.until(b'\x30'))[1]
        self.assertEqual([i.unknown_words[0] for i in repaired], [341, 309])
        self.assertEqual(store.inventory('alice', 1), alice_inventory)
        self.ping(alice); self.ping(bob)
