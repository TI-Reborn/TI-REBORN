"""Actual city-scoped warehouse resources, private accounts and native counters."""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio.db_transaction import transaction
from tio.protocol.asset_count import AssetCount, decode_asset_count, encode_asset_count
from tio.protocol.item_list import ItemRecord, encode_item_list, decode_item_list
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tio.owned_pets import OwnedPetStore
from tio.warehouse_resources import counts, project_assets
from tio.warehouse_service import transfer_private_items

ROOT=Path(__file__).resolve().parents[1]


def item(identity, template, quantity=1, resource=1, capacity=None):
    capacity=resource if capacity is None else capacity
    return ItemRecord(identity,template,bytes(2),quantity,0,0,(resource,capacity,capacity),bytes(4),None,bytes(3))


class WarehouseResourcesTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path=Path(self.folder.name)/'shared.sqlite3'
        raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        for name in ('alice','bob'):
            OwnedPetStore(self.path).ensure(name,raw,encode_item_list(1,()),human=True)
            WalletStore(self.path).ensure(name)
        self.store=WarehouseStore(self.path)
        with transaction(self.path) as db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)',(('alice',),('bob',)))

    def stash(self, items, owner='alice', town=None, bucket='city'):
        with transaction(self.path) as db:
            for i in items:
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',(owner,i.instance_id,encode_item_list(0,(i,))))
                if town is not None:
                    db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?)',(owner,i.instance_id,bucket,town,'owned-test'))

    def assets(self, owner='alice'):
        return WalletStore(self.path).ensure(owner)

    def test_counts_units_and_remaining_resource_for_all_supported_kits(self):
        self.stash((item(1,30,3),item(2,30,2),item(3,17,resource=328,capacity=600),
                    item(4,18,resource=612,capacity=1200),item(5,19,resource=3600),
                    item(6,17,resource=0,capacity=600),item(7,301,resource=300)))
        a=self.assets()
        self.assertEqual((a.upgrade_kits,a.repair_points),(5,4540))
        self.assertEqual(decode_asset_count(encode_asset_count(a)),a)

    def test_city_scope_matches_the_actual_list_and_preserves_legacy_overflow(self):
        self.stash((item(1,30,2),))
        self.stash((item(2,17,resource=600),),town=3)
        self.stash((item(3,18,resource=1200),item(4,30,7)),town=2)
        self.stash((item(5,19,resource=3600),),town=2,bucket='overflow')
        self.assertEqual((self.assets().upgrade_kits,self.assets().repair_points),(2,4200))
        with transaction(self.path) as db:db.execute('UPDATE character_locations SET town_id=2 WHERE account=?',('alice',))
        self.assertEqual((self.assets().upgrade_kits,self.assets().repair_points),(9,4800))
        self.assertEqual({i.instance_id for i in self.store.items('alice')},{1,3,4,5})

    def test_other_accounts_bags_and_clan_treasury_never_contribute(self):
        self.stash((item(1,30,2),))
        self.stash((item(1,19,resource=3600),item(2,30,99)),'bob')
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (encode_item_list(1,(item(10,17,resource=600),item(11,30,9))),'alice'))
            # The previous bug returned these two amounts as repair/upgrades.
            db.execute('CREATE TABLE clans(id INTEGER PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.execute('INSERT INTO clans VALUES (1,999999,888888)')
        a=self.assets();b=self.assets('bob')
        self.assertEqual((a.repair_points,a.upgrade_kits),(0,2))
        self.assertEqual((b.repair_points,b.upgrade_kits),(3600,99))

    def test_existing_clan_projection_entry_point_clears_stale_funds(self):
        from tio.clans import project_assets as compatibility
        self.stash((item(1,30,4),item(2,17,resource=452,capacity=600)))
        old=AssetCount(1234,0,5,6,7,8,9,99999,88888,3,(100,1))
        with transaction(self.path) as db:a=compatibility(db,'alice',old)
        self.assertEqual(a,replace(old,unknown_u32_08=452,unknown_u32_09=4))

    def test_projection_is_read_only_even_when_schema_is_missing(self):
        with sqlite3.connect(':memory:') as db:
            before=tuple(db.iterdump());a=project_assets(db,'alice',AssetCount(3,0,unknown_u32_08=99,unknown_u32_09=98))
            self.assertEqual((a.repair_points,a.upgrade_kits),(0,0))
            self.assertEqual(tuple(db.iterdump()),before)
        self.stash((item(1,17,resource=328,capacity=600),))
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN');before=tuple(db.iterdump())
            for _ in range(3):self.assertEqual(counts(db,'alice'),(328,0))
            self.assertEqual(tuple(db.iterdump()),before)

    def test_legacy_identical_kit_stack_counts_each_remaining_resource(self):
        self.stash((item(1,18,quantity=3,resource=123,capacity=1200),))
        self.assertEqual(self.assets().repair_points,369)

    def test_deposit_and_withdraw_immediately_refresh_counters_and_reject_replay(self):
        from tio.warehouse import WarehouseRejected
        bag=(item(1,30,quantity=3),item(2,17,resource=328,capacity=600))
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,bag),'alice'))
        request=encode_warehouse_transfer(WarehouseTransfer(0,1,((1,2),(2,1)),()))
        replies=transfer_private_items(self.path,'alice',request,capacity=32)
        a=decode_asset_count(replies[-1]);self.assertEqual((a.upgrade_kits,a.repair_points),(2,328))
        before=self.assets()
        with self.assertRaises(WarehouseRejected):transfer_private_items(self.path,'alice',request,capacity=32)
        self.assertEqual(self.assets(),before)
        entries=self.store.items('alice')
        replies=transfer_private_items(self.path,'alice',encode_warehouse_transfer(WarehouseTransfer(0,1,(),tuple((i.instance_id,i.count) for i in entries))),capacity=32)
        a=decode_asset_count(replies[-1]);self.assertEqual((a.upgrade_kits,a.repair_points),(0,0))
        self.assertEqual(sum(i.count for i in decode_item_list(replies[0])[1] if i.template_id==30),3)

    def test_failed_deposit_cannot_change_inventory_or_counters(self):
        bag=(item(1,30),)
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,bag),'alice'))
            db.execute("CREATE TRIGGER reject_kit BEFORE INSERT ON warehouse_items BEGIN SELECT RAISE(ABORT,'injected'); END")
        before=self.assets()
        with self.assertRaises(sqlite3.IntegrityError):
            transfer_private_items(self.path,'alice',encode_warehouse_transfer(WarehouseTransfer(0,1,((1,1),),())),capacity=32)
        self.assertEqual(self.assets(),before)
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1],bag)

    def test_passive_inventory_change_refreshes_header_once(self):
        from server.economy_runtime import refresh_inventory
        session=SimpleNamespace(database=self.path,account='alice')
        with patch('server.economy_runtime.city_idle',return_value=True):
            rows=refresh_inventory(session)
            self.assertEqual(decode_asset_count(rows[-1]).upgrade_kits,0)
            self.assertEqual(refresh_inventory(session),())
            self.stash((item(1,30,quantity=7),))
            self.assertEqual(decode_asset_count(refresh_inventory(session)[-1]).upgrade_kits,7)

    def test_u32_display_bound_never_changes_item_quantities(self):
        self.stash((item(1,30,quantity=0xffffffff),item(2,30)))
        self.assertEqual(self.assets().upgrade_kits,0xffffffff)
        self.assertEqual(sum(i.count for i in self.store.items('alice')),0x100000000)

    def test_clan_cash_still_uses_authorised_safe_rows(self):
        import test_clans as fixtures
        from tio.protocol.warehouse import decode_warehouse_list
        f=fixtures.ClanTests();f.setUp();self.addCleanup(f.doCleanups)
        f.exchange('bob',2,deposits=((0xffff0001,500),))
        a=WalletStore(f.path).ensure('alice')
        self.assertEqual((a.repair_points,a.upgrade_kits),(0,0))
        safe=decode_warehouse_list(f.store.warehouse_packets('alice',2)[0])[3]
        self.assertIn((1,500),[(i.template_id,i.count) for i in safe])
        self.assertEqual(f.store.info('alice')['credits'],500)

    def test_repaired_then_redeposited_kit_counts_only_its_remaining_points(self):
        import struct
        from tio.repair import repair
        bag=(item(1,17,resource=600),item(2,301,resource=50,capacity=350))
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,bag),'alice'))
        with patch('tio.achievements.update'):
            updated,_=repair(self.path,'alice',b'\xc2\x03'+struct.pack('<II',1,2))
        kit=next(i for i in decode_item_list(updated)[1] if i.template_id==17)
        self.assertEqual(kit.unknown_words[0],309)
        replies=transfer_private_items(self.path,'alice',encode_warehouse_transfer(WarehouseTransfer(0,1,((1,1),),())),capacity=32)
        self.assertEqual(decode_asset_count(replies[-1]).repair_points,309)

    def test_all_seven_header_values_use_independent_authoritative_sources(self):
        self.stash((item(1,30,quantity=3),item(2,17,resource=328,capacity=600)))
        with transaction(self.path) as db:
            db.execute('CREATE TABLE crystal_wallets(account TEXT PRIMARY KEY,amount INTEGER)')
            db.execute('INSERT INTO crystal_wallets VALUES (?,71)',('alice',))
            db.execute('CREATE TABLE bank_securities(account TEXT PRIMARY KEY,bonds INTEGER,stocks INTEGER)')
            db.execute('INSERT INTO bank_securities VALUES (?,72,73)',('alice',))
            db.execute('CREATE TABLE range_accounts(account TEXT PRIMARY KEY,used_day INTEGER,golden INTEGER)')
            db.execute('INSERT INTO range_accounts VALUES (?,-1,74)',('alice',))
        a=self.assets()
        self.assertEqual((a.upgrade_kits,a.repair_points,a.spectra_crystals,a.spectra_bonds,a.spectra_stock,a.gold_slug,a.slug),
                         (3,328,71,72,73,74,1))
        b=self.assets('bob')
        self.assertEqual((b.upgrade_kits,b.repair_points,b.spectra_crystals,b.spectra_bonds,b.spectra_stock,b.gold_slug),
                         (0,0,0,0,0,0))

    def test_failed_passive_header_read_is_retried_instead_of_cached(self):
        from server.economy_runtime import refresh_inventory
        session=SimpleNamespace(database=self.path,account='alice')
        with patch('server.economy_runtime.city_idle',return_value=True):
            with patch('tio.wallets.WalletStore.ensure',side_effect=sqlite3.OperationalError('busy')):
                with self.assertRaises(sqlite3.OperationalError):refresh_inventory(session)
            self.assertFalse(hasattr(session,'_economy_inventory_digest'))
            self.assertTrue(refresh_inventory(session))
