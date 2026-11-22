from wallet_fixture import fund_wallet
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from tio.player_auction import AuctionStore
from tio.protocol.binary import Writer
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]


def create_packet(request=1, instance=1, count=1, hours=12, price=1000, step=100, buyout=3000):
    w = Writer().u8(0xc8).u8(10).u32(request).u32(1).u32(instance).u32(count).u8(hours).u32(price).u32(step)
    w.data.extend('Проверка\0'.encode('utf-16le'))
    w.u8(int(buyout is not None))
    if buyout is not None:
        w.u32(buyout)
    return w.build()


class AuctionTests(unittest.TestCase):
    def test_history_uses_one_based_pages(self):
        from server.player_auction import AuctionSession
        from tio.protocol.binary import Reader

        lot = self.create(price=100, step=1, buyout=None)
        for index in range(30):
            self.store.bid('buyer', 'Покупатель', lot, 100+index, index, now=101+index)
        session = AuctionSession(self.store, 'buyer', 'Покупатель')
        request = Writer().u8(0xc8).u8(6).u32(lot).build()
        for suffix, expected_page, count, kind, amount in (
                (b'\0', 1, 30, 1, 100),
                (b'\1'+bytes(4), 1, 30, 1, 100),
                (b'\1'+(1).to_bytes(4, 'little'), 1, 30, 1, 100),
                (b'\1'+(2).to_bytes(4, 'little'), 2, 1, 3, 129),
                (b'\1'+b'\xff'*4, 2, 1, 3, 129)):
            with self.subTest(page=expected_page, request=suffix):
                reply, = session.handle(request+suffix)
                reader = Reader(reply)
                self.assertEqual(reader.read(2), b'\xc8\x07')
                self.assertEqual([reader.u32() for _ in range(6)],
                                 [lot, expected_page, 2, count, kind, amount])

    def test_native_confirmation_packets_buy_out_and_cancel_the_correct_lots(self):
        from server.player_auction import AuctionSession

        seller = AuctionSession(self.store, 'seller', 'Продавец')
        buyer = AuctionSession(self.store, 'buyer', 'Покупатель')
        sold, cancelled = [int.from_bytes(seller.handle(create_packet(request=i))[1][6:10], 'little')
                           for i in (1, 2)]
        self.assertIn(b'\xc8\x04'+sold.to_bytes(4, 'little'),
                      buyer.handle(b'\xc8\x0e'+sold.to_bytes(4, 'little')))
        self.assertIn(b'\xc8\x05'+cancelled.to_bytes(4, 'little'),
                      seller.handle(b'\xc8\x0f'+cancelled.to_bytes(4, 'little')))
        self.assertEqual((self.store.get(sold)[0]['state'], self.store.get(cancelled)[0]['state']),
                         ('sold', 'cancelled'))

    def test_buyout_remains_available_when_next_bid_exceeds_buyout(self):
        lot = self.create(price=100, step=50, buyout=120)
        self.store.bid('buyer', 'Покупатель', lot, 100, 0, now=101)
        self.store.bid('other', 'Другой', lot, None, None, buyout=True, now=102)
        self.assertEqual(self.store.get(lot)[0]['state'], 'sold')
        self.assertEqual([self.wallets.ensure(n).credits for n in ('seller', 'buyer', 'other')],
                         [10120, 10000, 9880])
        self.assertEqual(WarehouseStore(self.path).items('other')[0].template_id, self.item.template_id)

    def test_personal_lots_are_restored_and_updated_in_a_new_session(self):
        from server.player_auction import AuctionSession

        lot = self.create()
        seller = AuctionSession(self.store, 'seller', 'Продавец')
        other = AuctionSession(self.store, 'other', 'Другой')
        added = b'\xc8\x03\x01\0\0\0' + lot.to_bytes(4, 'little')
        self.assertTrue(any(p.startswith(added) for p in seller.refresh()))
        self.assertFalse(any(p.startswith(added) for p in other.refresh()))
        self.store.bid('buyer', 'Покупатель', lot, 1000, 0, now=101)
        buyer = AuctionSession(self.store, 'buyer', 'Покупатель')
        self.assertTrue(any(p.startswith(added) for p in buyer.refresh()))
        seller.next_refresh = 0
        self.assertTrue(any(p.startswith(added) for p in seller.refresh()))
        self.store.bid('other', 'Другой', lot, None, None, buyout=True, now=102)
        seller.next_refresh = 0
        self.assertIn(b'\xc8\x04' + lot.to_bytes(4, 'little'), seller.refresh())

    def test_native_first_page_and_load_more_are_one_based(self):
        from unittest.mock import patch
        from server.player_auction import AuctionSession
        from tio.protocol.player_auction import decode_list
        self.create();row,items=self.store.get(1)
        lots=[({**dict(row),'id':i},items) for i in range(1,24)]
        session=AuctionSession(self.store,'buyer','Покупатель')
        with patch.object(self.store,'lots',return_value=lots):
            for page,count,first in ((1,10,1),(2,10,11),(3,3,21),(4,0,None),(0,10,1)):
                # Original UI: all categories -> empty type list, full ranges.
                request=(Writer().u8(0xc8).u8(8).u32(0).u32(77).u8(1)
                         .u32(0).u32(0).u8(1).u8(0).u8(27).u8(1).u8(0).u8(100)
                         .u8(1).u32(3).u32(3).u32(page).build())
                reply=session.listing(decode_list(request))
                self.assertEqual([int.from_bytes(reply[o:o+4],'little') for o in (2,6,10,14)],
                                 [77,max(1,page),3,count])
                if first is not None:self.assertEqual(int.from_bytes(reply[18:22],'little'),first)

    def test_buy_pages_count_lots_the_native_tab_can_display(self):
        from server.player_auction import AuctionSession

        self.create()
        query = (0, 77, 1, (), (), None, None, None)
        seller = AuctionSession(self.store, 'seller', 'Продавец')
        buyer = AuctionSession(self.store, 'buyer', 'Покупатель')
        self.assertEqual(int.from_bytes(seller.listing(query)[14:18], 'little'), 0)
        self.assertEqual(int.from_bytes(buyer.listing(query)[14:18], 'little'), 1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'state.sqlite3'
        self.wallets = WalletStore(self.path)
        for name in ('seller','buyer','other'):
            fund_wallet(self.wallets.path, name, credits=10_000, gold=10_000)
        self.store = AuctionStore(self.path, pledge_percent=5)
        packet = bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text(encoding='utf-8'))['inventory_packet_hex'])
        self.item = replace(decode_item_list(packet)[1][0], instance_id=1, unknown_u32_01=5,
                            unknown_u8_01=0, location_raw=0, unknown_bytes_02=bytes(4), optional_u32=None,
                            unknown_words=(20,35,40), unknown_bytes_03=bytes((2,3,1)))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', ('seller',1,encode_item_list(0,(self.item,))))

    def create(self, **kwargs):
        return self.store.create('seller','Продавец',create_packet(**kwargs),session='test',now=100)

    def test_bid_refund_buyout_preserves_instance_and_money(self):
        lot = self.create(count=2)
        self.assertEqual(self.wallets.ensure('seller').credits,9950)
        self.assertEqual(WarehouseStore(self.path).items('seller')[0].count,3)
        self.store.bid('buyer','Первый',lot,1000,0,now=101)
        self.store.bid('other','Второй',lot,1100,1,now=102)
        self.assertEqual(self.wallets.ensure('buyer').credits,10000)
        self.store.bid('buyer','Первый',lot,None,None,buyout=True,now=103)
        self.assertEqual([self.wallets.ensure(n).credits for n in ('seller','buyer','other')], [13000,7000,10000])
        received = WarehouseStore(self.path).items('buyer')
        self.assertEqual(len(received),1)
        self.assertEqual(replace(received[0],instance_id=1),replace(self.item,unknown_u32_01=2))
        with self.assertRaises(ValueError):
            self.store.bid('other','Другой',lot,None,None,buyout=True,now=104)
        self.assertEqual(self.store.get(lot)[0]['state'],'sold')

    def test_expiry_and_reopen_are_exactly_once(self):
        lot = self.create(count=5,buyout=None)
        self.store.bid('buyer','Покупатель',lot,1000,0,now=101)
        reopened = AuctionStore(self.path,pledge_percent=5)
        reopened.settle(now=43300)
        reopened.settle(now=99999)
        self.assertEqual(self.wallets.ensure('seller').credits,11000)
        self.assertEqual(len(WarehouseStore(self.path).items('buyer')),1)
        self.assertEqual(reopened.get(lot)[0]['state'],'sold')

    def test_cancel_and_expired_unsold_keep_pledge(self):
        lot = self.create(count=5)
        with self.assertRaises(ValueError):
            self.store.cancel('other',lot,now=101)
        self.store.cancel('seller',lot,now=101)
        self.store.cancel('seller',lot,now=101)
        self.assertEqual(sum(i.count for i in WarehouseStore(self.path).items('seller')),5)
        self.assertEqual(self.wallets.ensure('seller').credits,9950)
        item = WarehouseStore(self.path).items('seller')[0]
        lot2 = self.create(request=2,instance=item.instance_id,count=5)
        self.store.settle(now=43300)
        self.assertEqual(self.store.get(lot2)[0]['state'],'expired')
        self.assertEqual(self.wallets.ensure('seller').credits,9900)

    def test_racing_buyers_and_duplicate_create(self):
        def create(_):
            return self.create(count=5)
        with ThreadPoolExecutor(max_workers=4) as workers:
            lots = list(workers.map(create, range(4)))
        self.assertEqual(len(set(lots)),1)
        self.assertEqual(self.wallets.ensure('seller').credits,9950)
        def buy(name):
            try:
                self.store.bid(name,name,lots[0],None,None,buyout=True,now=101)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(buy,('buyer','other')))
        self.assertEqual(sum(results),1)
        self.assertEqual(sum(self.wallets.ensure(n).credits for n in ('seller','buyer','other')),30000)
        self.assertEqual(sum(len(WarehouseStore(self.path).items(n)) for n in ('buyer','other')),1)

    def test_rejected_bid_does_not_refund_or_change_owner(self):
        lot=self.create()
        self.store.bid('buyer','buyer',lot,1000,0,now=101)
        for account,amount,index in [('seller',1100,1),('other',1099,1),('other',1200,0),('other',20000,1)]:
            with self.assertRaises(ValueError):
                self.store.bid(account,account,lot,amount,index,now=102)
        with self.assertRaises(ValueError):
            self.store.cancel('seller',lot,now=102)
        self.assertEqual(self.wallets.ensure('buyer').credits,9000)
        self.assertEqual(self.store.get(lot)[0]['bid'],1000)

    def test_transaction_rollback_keeps_goods_and_balance(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TRIGGER deny_lot BEFORE INSERT ON player_auction_items BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create()
        self.assertEqual(self.wallets.ensure('seller').credits,10000)
        self.assertEqual(WarehouseStore(self.path).items('seller'),(self.item,))

    def test_native_hours_and_malformed_requests(self):
        from tio.protocol.player_auction import decode_create
        for hours in (12,24,48,96,168):
            self.assertEqual(decode_create(create_packet(hours=hours)).hours,hours)
        for packet in (create_packet(hours=0),create_packet(count=0),create_packet()+b'\0',create_packet()[:-1]):
            with self.assertRaises(ValueError):
                decode_create(packet)
