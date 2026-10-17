from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.warehouse_queries import handles,reply
from tio.warehouse import WarehouseStore,WarehouseRejected
from tio.protocol.item_list import encode_item_list
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.warehouse_service import transfer_private_items
from tio.wallets import WalletStore
from test_combat import item


class WarehouseQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db.sqlite3'
        WarehouseStore(self.path)
        for name in ('alice','bob'):WalletStore(self.path).ensure(name)
        with closing(sqlite3.connect(self.path)) as db,db:
            for name,credits,template in (('alice',123,301),('bob',987,339)):
                db.execute('UPDATE wallets SET credits=? WHERE account=?',(credits,name))
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',
                           (name,1001,encode_item_list(0,(item(1001,template),))))

    def test_assets_are_current_and_scoped_to_authenticated_account(self):
        for name,expected in (('alice',123),('bob',987)):
            self.assertEqual(decode_asset_count(reply(self.path,name,b'\xb8\x11')[0]).credits,expected)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=50 WHERE account=?',('alice',))
        self.assertEqual(decode_asset_count(reply(self.path,'alice',b'\xb8\x11')[0]).credits,50)

    def test_private_warehouse_still_uses_owned_items(self):
        for name,template in (('alice',301),('bob',339)):
            kind,total,segment,items=decode_warehouse_list(reply(self.path,name,b'\x69\0')[0])
            self.assertEqual((kind,total,segment),(0,1,0))
            self.assertEqual([i.template_id for i in items],[template])

    def test_clan_kinds_clear_requested_cache_and_deny_without_leaking_items(self):
        for kind in (1,2):
            packets=reply(self.path,'alice',bytes((0x69,kind)))
            self.assertEqual(decode_warehouse_list(packets[0]),(kind,1,0,()))
            self.assertEqual(packets[1][0],0xf0)
            with self.assertRaises(WarehouseRejected):
                transfer_private_items(self.path,'alice',encode_warehouse_transfer(
                    WarehouseTransfer(kind,1,(),((1001,1),))),capacity=100)
        self.assertEqual(len(WarehouseStore(self.path).items('alice')),1)

    def test_empty_postbox_is_mail_packet_not_personal_warehouse_alias(self):
        self.assertEqual(reply(self.path,'alice',b'\x69\x03'),(bytes.fromhex('b77500000000'),))
        with self.assertRaises(WarehouseRejected):
            transfer_private_items(self.path,'alice',encode_warehouse_transfer(
                WarehouseTransfer(3,1,(),((1001,1),))),capacity=100)

    def test_marks_and_clan_rankings_do_not_return_ordinary_items(self):
        self.assertEqual(reply(self.path,'alice',b'\xb8\x04'),(bytes.fromhex('c82900000000'),))
        self.assertEqual(reply(self.path,'alice',b'\xb8\x09'),(bytes.fromhex('b80a00000000'),))

    def test_imported_marker_without_owner_is_not_silently_invented(self):
        marked=replace(item(1001,301),unknown_bytes_02=b'\0\0\x01\0')
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=?',
                       (encode_item_list(0,(marked,)),'alice'))
        with self.assertRaises(WarehouseRejected):reply(self.path,'alice',b'\xb8\x04')
        self.assertEqual(reply(self.path,'bob',b'\xb8\x04'),(bytes.fromhex('c82900000000'),))

    def test_bad_queries_and_unrelated_commands(self):
        for packet in (b'\x69',b'\x69\x04',b'\x69\x05',b'\x69\0\0',b'\xb8\x11\0',b'\xb8\x04\0'):
            self.assertTrue(handles(packet))
            with self.assertRaises(ValueError):reply(self.path,'alice',packet)
        self.assertFalse(handles(b'\xb8\x06'))
        self.assertIsNone(reply(self.path,'alice',b'\xb8\x06'))

    def test_encrypted_dispatch_routes_every_recovered_request(self):
        from tools.audit_unanswered_requests import replay
        for request,prefix in (('b804','c829'),('b809','b80a'),('b811','c839'),
                               ('6901','6a01000000'),('6902','6a02000000'),('6903','b775')):
            with self.subTest(request=request):
                self.assertTrue(replay(request)[0].startswith(prefix))
