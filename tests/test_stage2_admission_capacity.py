"""Admission work budgets and atomic carried-inventory limits."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing,ExitStack
from dataclasses import replace
import sqlite3
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

import test_multi_account as tcp_fixture
import test_sc_shop as sc_fixture
import test_equipment_templates as template_fixture
from server.login_guard import LoginGuard,LoginThrottled
from server.runtime import Server
from server.multi import MultiServer
from tio.inventory_capacity import validate_capacity,INVENTORY_SLOTS
from tio.item_stacking import MAX_STACK
from tio.shop import ShopStore
from tio.city_catalogs import CityCatalogs
from tio.warehouse import WarehouseStore
from tio.rental import RentalStore
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list
from tio.protocol.shop_purchase import ShopPurchase


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now=0;self.guard=LoginGuard(clock=lambda:self.now)

    def slot(self,name='alice',ip='192.0.2.1'):
        with self.guard.hash_slot(ip,name.encode()):pass

    def test_ip_account_attempt_budget_refills_without_account_wide_lockout(self):
        for _ in range(5):self.slot()
        with self.assertRaises(LoginThrottled):self.slot()
        self.slot(ip='192.0.2.2');self.slot('bob')
        self.now=9.99
        with self.assertRaises(LoginThrottled):self.slot()
        self.now=10;self.slot()

    def test_ip_budget_limits_rotating_login_names(self):
        for i in range(12):self.slot('user'+str(i))
        with self.assertRaises(LoginThrottled):self.slot('newuser')
        self.slot('newuser','192.0.2.2');self.now=2;self.slot('newuser')

    def test_global_budget_limits_rotating_addresses(self):
        for i in range(24):self.slot('user'+str(i),'192.0.2.'+str(i+1))
        with self.assertRaises(LoginThrottled):self.slot('newuser','192.0.2.100')
        self.now=.25;self.slot('newuser','192.0.2.100')

    def test_hash_parallelism_and_same_account_concurrency_are_bounded(self):
        with ExitStack() as stack:
            stack.enter_context(self.guard.hash_slot('192.0.2.1',b'alice'))
            with self.assertRaises(LoginThrottled):self.slot('alice','192.0.2.2')
            stack.enter_context(self.guard.hash_slot('192.0.2.2',b'bob'))
            with self.assertRaises(LoginThrottled):self.slot('carol','192.0.2.3')
            self.assertEqual(self.guard.snapshot()['hashing'],2)
        self.slot('carol');self.assertEqual(self.guard.snapshot()['hashing'],0)

    def test_hash_exception_releases_slot_but_does_not_refund_attempt(self):
        with self.assertRaises(ValueError):
            with self.guard.hash_slot('192.0.2.1',b'alice'):raise ValueError('Invalid credentials')
        for _ in range(4):self.slot()
        with self.assertRaises(LoginThrottled):self.slot()
        self.assertEqual(self.guard.snapshot()['hashing'],0)

    def test_bucket_memory_is_bounded_and_idle_state_expires(self):
        self.guard.MAX_BUCKETS=8
        for i in range(6):self.slot('user'+str(i))
        with self.assertRaises(LoginThrottled):self.slot('another')
        self.assertEqual(self.guard.snapshot()['buckets'],8)
        self.now=301;self.slot('another');self.assertEqual(self.guard.snapshot()['buckets'],3)

    def test_invalid_and_oversized_names_share_bounded_key(self):
        for name in (b'x'*60000,b'UPPER',b'\xff',b'',b'-invalid-'):
            with self.guard.hash_slot('192.0.2.1',name):pass
        with self.assertRaises(LoginThrottled):
            with self.guard.hash_slot('192.0.2.1',b'different invalid'):pass
        self.assertEqual(self.guard.snapshot()['buckets'],3)

    def test_preauthentication_budget_is_separate_from_authorized_accounts(self):
        self.guard.admit_connection('192.0.2.2',unauthenticated=['192.0.2.1']*4,total=20,max_sessions=16)
        with self.assertRaises(LoginThrottled):
            self.guard.admit_connection('192.0.2.1',unauthenticated=['192.0.2.1']*4,total=4,max_sessions=16)
        with self.assertRaises(LoginThrottled):
            self.guard.admit_connection('192.0.2.3',unauthenticated=['192.0.2.1']*4+['192.0.2.2']*4,total=8,max_sessions=16)

    def test_handoff_budget_reserves_other_addresses(self):
        with self.assertRaises(LoginThrottled):
            self.guard.admit_handoff('192.0.2.1',addresses=['192.0.2.1']*4,max_handoffs=8)
        self.guard.admit_handoff('192.0.2.2',addresses=['192.0.2.1']*4,max_handoffs=8)

    def test_constructor_is_not_called_for_denied_connection(self):
        case=tcp_fixture.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups)
        hub=MultiServer(Server(case.config))
        hub.sessions={Mock(login_peer_address='192.0.2.1',authenticated_account=None) for _ in range(4)}
        connection=Mock()
        with patch('tools.loopback_exchange.LoopbackExchange') as constructor:
            hub.new_login(connection,('192.0.2.1',12345));constructor.assert_not_called()
        connection.close.assert_called_once()

    def test_authorized_capacity_is_checked_even_with_spare_handshake_slots(self):
        case=tcp_fixture.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups)
        hub=MultiServer(Server(case.config));hub.active_accounts={str(i):Mock() for i in range(16)}
        with patch.object(hub.accounts,'verify',return_value='alice'):
            with self.assertRaisesRegex(ValueError,'capacity'):
                hub.authorize(SimpleNamespace(login_peer_address='192.0.2.1'),SimpleNamespace(login_bytes=b'alice',password_bytes=b'synthetic-only'))
        self.assertEqual(len(hub.active_accounts),16)

    def test_denied_authentication_skips_hashing_and_healthy_tcp_account_stays_online(self):
        case=tcp_fixture.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        alice=case.handoff(case.begin('alice'));case.enter(alice,'Alice')
        bob=case.handoff(case.begin('bob'));case.enter(bob,'Bob')
        with patch.object(case.server.multi.accounts,'verify',wraps=case.server.multi.accounts.verify) as verify:
            for _ in range(6):case.begin('unknown01',denied=True)
            self.assertEqual(verify.call_count,5)
        case.ping(alice);case.ping(bob);self.assertFalse(case.errors)

    def test_idle_handshakes_cannot_disconnect_authenticated_tcp_accounts(self):
        case=tcp_fixture.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        alice=case.handoff(case.begin('alice'));case.enter(alice,'Alice')
        bob=case.handoff(case.begin('bob'));case.enter(bob,'Bob')
        for _ in range(4):
            connection=case.connect(case.config.game_port)
            self.assertTrue(connection.recv(64))  # Hold four initial challenges open.
        denied=case.connect(case.config.game_port);self.assertEqual(denied.recv(64),b'')
        case.ping(alice);case.ping(bob);self.assertTrue(case.thread.is_alive())


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.case=sc_fixture.SCShopTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path

    def weapon(self,identity):
        return ItemRecord(identity,314,bytes(2),1,0,0,(300,)*3,bytes(4),None,bytes(3))

    def bag(self,count,*,ammo=None):
        items=tuple(self.weapon(2000+i) for i in range(count-int(ammo is not None)))
        if ammo is not None:
            offer=self.case.store.offers[100014]
            items+= (replace(self.weapon(4000),template_id=14,unknown_u32_01=ammo,unknown_words=(offer.durability,)*3),)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",(encode_item_list(1,items),))
        return items

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {name:tuple(db.execute('SELECT * FROM "'+name+'"')) for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def reject_unchanged(self,operation):
        before=self.state()
        with self.assertRaisesRegex(ValueError,'Inventory is full'):operation()
        self.assertEqual(self.state(),before)

    def test_manual_limit_includes_equipped_items_and_preserves_legacy_bags(self):
        self.assertEqual(INVENTORY_SLOTS,18)
        validate_capacity(range(18),range(18));validate_capacity(range(22),range(21));validate_capacity(range(22),range(22))
        with self.assertRaises(ValueError):validate_capacity(range(22),range(23))

    def test_sc_direct_19th_item_rolls_back_money_stock_sequence_and_achievements(self):
        self.bag(17)
        self.case.store.handle('alice',sc_fixture.request(6,self.case.lot,1,2))
        self.reject_unchanged(lambda:self.case.store.handle('alice',sc_fixture.request(6,self.case.lot,1,2)))

    def test_sc_cart_failure_preserves_cart_and_whole_purchase(self):
        self.bag(17)
        for _ in range(2):self.case.store.handle('alice',sc_fixture.request(9,self.case.lot))
        self.reject_unchanged(lambda:self.case.store.handle('alice',sc_fixture.request(11,1,2)))

    def test_full_bag_accepts_compatible_stack_but_rejects_stack_overflow(self):
        self.bag(18,ammo=50)
        inventory=self.case.store.handle('alice',sc_fixture.request(6,100014,1,2))[0]
        self.assertEqual(len(decode_item_list(inventory)[1]),18)
        self.assertEqual(next(i.count for i in decode_item_list(inventory)[1] if i.template_id==14),150)
        self.bag(18,ammo=MAX_STACK)
        self.reject_unchanged(lambda:self.case.store.handle('alice',sc_fixture.request(6,100014,1,2)))

    def test_ordinary_and_premium_shop_share_limit(self):
        shop=ShopStore(self.path,CityCatalogs(sc_fixture.ROOT/'config/city_catalogs.json'));self.bag(18)
        self.reject_unchanged(lambda:shop.purchase('alice',ShopPurchase(1,0,81,1)))
        offer=next(o for o in shop.catalogs.premium_items if o.item_id not in (3,4,5,6,7,12,13,14,15,36,37,9,34))
        packet=b'\x78'+struct.pack('<5IQI',1,offer.offer_id,1,1,0,shop.catalogs.price_revision,0)
        self.reject_unchanged(lambda:shop.purchase_premium('alice',packet))

    def test_rental_limit_rolls_back_currency_and_lease(self):
        rental=RentalStore(self.path);self.bag(18)
        self.reject_unchanged(lambda:rental.handle('alice',b'\xb4\x10'+struct.pack('<IHIB',331410,3,1,2)))

    def test_warehouse_withdrawal_is_atomic_and_deposit_releases_slot(self):
        store=WarehouseStore(self.path,capacity=100);self.bag(18)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',5000,encode_item_list(0,(self.weapon(5000),))))
        self.reject_unchanged(lambda:store.exchange('alice',1,withdrawals=((5000,1),)))
        inventory,_=store.exchange('alice',1,deposits=((2000,1),),withdrawals=((5000,1),))
        self.assertEqual(len(decode_item_list(inventory)[1]),18)

    def test_legacy_overfull_bag_can_deposit_without_deleting_other_items(self):
        store=WarehouseStore(self.path,capacity=100);items=self.bag(20)
        self.reject_unchanged(lambda:self.case.store.handle('alice',sc_fixture.request(6,self.case.lot,1,2)))
        inventory,_=store.exchange('alice',1,deposits=((2000,1),))
        self.assertEqual(decode_item_list(inventory)[1],items[1:])

    def test_overfull_delivery_warehouse_can_shrink_but_cannot_grow(self):
        store=WarehouseStore(self.path,capacity=1);self.bag(1)
        with closing(sqlite3.connect(self.path)) as db,db:
            for identity in (5000,5001,5002):
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',identity,encode_item_list(0,(self.weapon(identity),))))
        before=self.state()
        with self.assertRaisesRegex(ValueError,'Warehouse capacity exceeded'):store.exchange('alice',1,deposits=((2000,1),))
        self.assertEqual(self.state(),before)
        inventory,stored=store.exchange('alice',1,withdrawals=((5000,1),))
        self.assertEqual(len(stored),2);self.assertEqual(len(decode_item_list(inventory)[1]),2)

    def test_parallel_purchases_cannot_both_claim_last_slot(self):
        self.bag(17)
        def buy(_):
            try:self.case.store.handle('alice',sc_fixture.request(6,self.case.lot,1,2));return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:self.assertEqual(sorted(pool.map(buy,range(2))),[False,True])
        from tio.owned_pets import OwnedPetStore
        self.assertEqual(len(decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1]),18)

    def test_equipment_template_cannot_pull_19th_item_from_warehouse(self):
        case=template_fixture.EquipmentTemplateTests();case.setUp();self.addCleanup(case.doCleanups)
        # Keep eighteen unstackable extras; the requested rifle remains stored.
        with closing(sqlite3.connect(case.path)) as db,db:
            db.execute("UPDATE owned_pets SET inventory_packet=? WHERE account='alice'",(encode_item_list(1,tuple(self.weapon(2000+i) for i in range(18))),))
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',1001,encode_item_list(0,(case.gun,))))
        t=replace(case.t,remove_extra=0,elements=(template_fixture.Element(object_id=1001),*[template_fixture.Element() for _ in range(6)]))
        identity=case.create(t);before=case.state()
        with self.assertRaisesRegex(ValueError,'Inventory is full'):case.store.handle('alice',template_fixture.command(4,identity))
        self.assertEqual(case.state(),before)


if __name__=='__main__':unittest.main()
