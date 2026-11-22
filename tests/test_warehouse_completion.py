"""Shared location access, owner isolation and real consumer transactions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import importlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
from types import ModuleType
import unittest

from wallet_fixture import fund_wallet
from tio import warehouse_completion as completion
from tio.db_transaction import transaction
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.warehouse import decode_warehouse_list, encode_private_warehouse_snapshot

ROOT = Path(__file__).resolve().parents[1]


def runtime(name):
    actual = importlib.import_module(name)
    if hasattr(importlib.import_module('tio.warehouse'), 'completion'): return actual
    path = ROOT/'reports/gameplay-followup/stage3-warehouses/runtime'/Path(*name.split('.')).with_suffix('.py')
    module = ModuleType(name.rsplit('.', 1)[0]+'._warehouse_completion_'+name.rsplit('.', 1)[1])
    module.__package__ = name.rsplit('.', 1)[0]
    module.__file__ = str(ROOT/Path(*name.split('.')).with_suffix('.py'))
    sys.modules[module.__name__] = module
    exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
    return module


WAREHOUSE = runtime('tio.warehouse')
MARKET = runtime('tio.market_inventory')
MAIL = runtime('tio.mail')
TEMPLATES = runtime('tio.equipment_templates')
STACKING = runtime('tio.item_stacking')
CLANS = runtime('tio.clans')
AUCTION = runtime('tio.player_auction')
ACHIEVEMENTS = runtime('tio.achievements')
BENEFITS = runtime('tio.clan_benefits')
BANK = runtime('tio.bank_economy')
RENTAL = runtime('tio.rental')


class WarehouseCompletionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'shared.sqlite3'
        trial = json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        pet = decode_pet_info(bytes.fromhex(trial['packet_hex']), human_equipment=True)
        pet.fields['0x8c4aef'] = 4
        self.pet = encode_pet_info(pet)
        self.gun = ItemRecord(1, 301, bytes(2), 1, 0, 0, (300,)*3, bytes(4), None, bytes(3))
        for account in ('alice', 'bob', 'carol'):
            OwnedPetStore(self.path).ensure(account, self.pet, encode_item_list(1, ()), human=True)
            fund_wallet(self.path, account, credits=1000000, gold=0)
        self.store = WAREHOUSE.WarehouseStore(self.path, capacity=3000)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE character_locations(account TEXT PRIMARY KEY,town_id INTEGER NOT NULL)')
            db.executemany('INSERT INTO character_locations VALUES (?,3)', [(a,) for a in ('alice','bob','carol')])
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT UNIQUE)')
            db.executemany('INSERT INTO characters VALUES (?,1,?,?)', [(a,a.title().encode(),a) for a in ('alice','bob','carol')])
        self.clans = CLANS.ClansStore(self.path)
        self.clan = self.clans.create('alice', b'Alpha')
        self.clans.invite('alice', b'Bob');self.clans.accept('bob', 1)

    def location(self, account, town):
        with transaction(self.path) as db: db.execute('UPDATE character_locations SET town_id=? WHERE account=?', (town, account))

    def inventory(self, items, account='alice'):
        with transaction(self.path) as db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1', (encode_item_list(1, tuple(items)), account))

    def stash(self, count, *, first=100, account='alice', origin='accepted-test-delivery'):
        items = tuple(replace(self.gun, instance_id=first+n) for n in range(count))
        with transaction(self.path) as db: completion.stash(db, account, items, origin=origin)
        return items

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return {table: db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                    for table in ('owned_pets','wallets','warehouse_items','warehouse_places','item_sequences','clan_paid_services','warehouse_service_receipts','clan_items')}

    def test_initialization_preserves_legacy_packets_ids_and_overflow_in_every_city(self):
        legacy = tuple(replace(self.gun, instance_id=1000+n) for n in range(100))
        with transaction(self.path) as db:
            db.executemany('INSERT INTO warehouse_items VALUES (?,?,?)', [('alice', i.instance_id, encode_item_list(0, (i,), 7)) for i in legacy])
        before = self.state()
        WAREHOUSE.WarehouseStore(self.path, capacity=32)
        self.assertEqual(self.state(), before)
        for town in (3,2,5,8,9,18):
            self.location('alice', town)
            self.assertEqual(tuple(i.instance_id for i in self.store.items('alice')), tuple(i.instance_id for i in legacy))
        self.inventory((self.gun,))
        self.store.exchange('alice', 1, deposits=((1,1),))
        with transaction(self.path) as db:
            status = completion.status(db, 'alice')
            self.assertEqual((status['capacity'],status['used'],status['legacy'],status['accessible']), (32,1,100,101))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM warehouse_places').fetchone()[0], 1)

    def test_cities_share_stock_while_account_isolation_and_ids_are_preserved(self):
        self.inventory((replace(self.gun, instance_id=5000),))
        self.store.exchange('alice',1,deposits=((5000,1),))
        self.location('alice',2)
        self.assertEqual(self.store.items('alice'), (replace(self.gun,instance_id=5000),))
        before = self.state()
        with self.assertRaises(ValueError): self.store.exchange('bob',1,withdrawals=((5000,1),))
        self.assertEqual(self.state(),before)
        ammo = replace(self.gun, instance_id=1, template_id=3, unknown_u32_01=50, unknown_words=(1,)*3)
        self.inventory((ammo,))
        self.store.exchange('alice',1,deposits=((1,20),))
        self.location('alice',3)
        self.assertEqual([(i.instance_id,i.count) for i in self.store.items('alice')],[(5000,1),(5001,20)])

    def test_capacity32_and_paid_service8_16_legacy_does_not_consume_city_slots(self):
        self.stash(32)
        self.inventory((self.gun,))
        before = self.state()
        with self.assertRaises(ValueError): self.store.exchange('alice',1,deposits=((1,1),))
        self.assertEqual(self.state(), before)
        from tio.services import purchase
        purchase(self.path,'alice',b'\xb1\x04\0'+struct.pack('<I',1)+b'\1'+struct.pack('<I',1))
        self.store.exchange('alice',1,deposits=((1,1),))
        with transaction(self.path) as db:
            self.assertEqual(completion.capacity(db,'alice'),40)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,995000)

    def test_durable_delivery_overflow_retains_origin_id_and_withdraws_elsewhere(self):
        delivered = self.stash(33, origin='mail:accepted-1')
        self.location('alice',2)
        self.assertEqual(self.store.items('alice'), delivered)
        result,_ = self.store.exchange('alice',1,withdrawals=((132,1),))
        self.assertEqual(decode_item_list(result)[1], (delivered[-1],))
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT bucket,origin FROM warehouse_places WHERE instance_id=132').fetchone(), ('overflow','mail:accepted-1'))
            self.assertEqual(completion.status(db,'alice')['stored_total'],32)

    def test_merge_compaction_combines_city_stacks_but_preserves_legacy(self):
        ammo = replace(self.gun, template_id=3, unknown_u32_01=50, unknown_words=(1,)*3)
        with transaction(self.path) as db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', ('alice',9000,encode_item_list(0,(replace(ammo,instance_id=9000),),7)))
        for town,key in ((3,1),(2,2)):
            self.location('alice',town);self.inventory((replace(ammo,instance_id=key),))
            self.store.exchange('alice',1,deposits=((key,50),))
        before = self.state()
        STACKING.compact_saved_items(self.path,'alice')
        self.assertEqual(self.state(),before)
        self.assertEqual([(i.instance_id,i.count) for i in self.store.items('alice')],[(1,100),(9000,50)])

    def test_market_and_mail_can_select_stock_deposited_in_another_town(self):
        self.stash(1)
        self.location('alice',2)
        before = self.state()
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                self.assertEqual(MARKET.take(db,'alice',100,1).instance_id,100)
                raise RuntimeError('rollback probe')
        self.assertEqual(self.state(),before)
        mail = MAIL.MailStore(self.path)
        mail.send('alice',b'Bob','Items','Delivery',items=((100,1),),request_id='shared-mail-test-0001',now=100)
        self.assertEqual(self.store.items('alice'),())

    def test_mail_claim_overflow_is_once_only_and_not_lost_on_full_city(self):
        self.stash(32,account='bob',first=1000)
        self.stash(1)
        mail = MAIL.MailStore(self.path)
        ident = mail.send('alice',b'Bob','Items','Delivery',items=((100,1),),request_id='actual-mail-test-0001',now=100)
        mail.claim('bob',ident,now=101);mail.claim('bob',ident,now=102)
        with transaction(self.path) as db:
            self.assertEqual((completion.status(db,'bob')['used'],completion.status(db,'bob')['overflow']), (32,1))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM mail_receipts WHERE action='claimed'").fetchone()[0],1)

    def test_template_can_pull_equipment_deposited_in_another_town(self):
        from tio.protocol.equipment_templates import Element, Template
        from test_equipment_templates import save, command
        self.stash(1)
        self.location('alice',2)
        store = TEMPLATES.EquipmentTemplateStore(self.path)
        t = Template('My outfit',1,0,0,(Element(object_id=100),*[Element() for _ in range(6)]))
        identity = int.from_bytes(store.handle('alice',save(t))[1][2:],'little')
        store.handle('alice',command(4,identity))
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).inventory('alice',1))[1][0].instance_id,100)
        self.assertEqual(self.store.items('alice'),())

    def test_outer_transaction_rejection_rolls_back_inventory_placements_and_services(self):
        self.inventory((self.gun,));before = self.state()
        with self.assertRaises(RuntimeError):
            with transaction(self.path) as db:
                self.store.exchange('alice',1,deposits=((1,1),))
                completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='outer')
                raise RuntimeError('Rejected action')
        self.assertEqual(self.state(),before)

    def test_database_write_failure_rolls_back_no_partial_placement_or_charge(self):
        self.inventory((self.gun,))
        with transaction(self.path) as db:
            db.execute("CREATE TRIGGER fail_place BEFORE INSERT ON warehouse_places BEGIN SELECT RAISE(ABORT,'test'); END")
        before = self.state()
        with self.assertRaises(sqlite3.IntegrityError): self.store.exchange('alice',1,deposits=((1,1),))
        self.assertEqual(self.state(),before)

    def test_clan_purchase_shared_entitlement_manual_prices_rights_and_replay(self):
        with transaction(self.path) as db:
            with self.assertRaises(ValueError): completion.clan_purchase(db,'bob',3,1,expected_clan=self.clan,identity='bob-unauthorized')
            first = completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='clan-level1')
            replay = completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='clan-level1')
            self.assertFalse(first['replayed']);self.assertTrue(replay['replayed'])
            self.assertEqual(completion.clan_status(db,'bob')['services'][0]['capacity'],40)
            completion.clan_purchase(db,'alice',3,2,expected_clan=self.clan,identity='clan-level2')
            completion.clan_purchase(db,'alice',4,1,expected_clan=self.clan,identity='safe-level1')
            self.assertEqual((completion.clan_capacity(db,self.clan,1),completion.clan_capacity(db,self.clan,2)), (48,40))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,1000000-15000-45000-15000)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,1000000)

    def test_clan_service_wrong_clan_skip_insufficient_city_and_conflicting_identity(self):
        before = self.state()
        for kwargs in (dict(service=3,wanted=2,expected_clan=self.clan,identity='skip'),dict(service=3,wanted=1,expected_clan=self.clan+1,identity='foreign'),dict(service=3.0,wanted=1,expected_clan=self.clan,identity='not-integer')):
            with self.assertRaises(ValueError):
                with transaction(self.path) as db: completion.clan_purchase(db,'alice',**kwargs)
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db: db.execute('UPDATE wallets SET credits=10 WHERE account=?',('alice',))
        insufficient = self.state()
        with self.assertRaises(ValueError):
            with transaction(self.path) as db: completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='insufficient')
        self.assertEqual(self.state(),insufficient)
        with transaction(self.path) as db: db.execute('UPDATE wallets SET credits=1000000 WHERE account=?',('alice',))
        self.location('alice',-1)
        with self.assertRaises(ValueError):
            with transaction(self.path) as db: completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='road')
        self.location('alice',3)
        with transaction(self.path) as db:
            completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='identity')
        before = self.state()
        with self.assertRaises(ValueError):
            with transaction(self.path) as db: completion.clan_purchase(db,'alice',4,1,expected_clan=self.clan,identity='identity')
        self.assertEqual(self.state(),before)

    def test_clan_concurrent_same_receipt_spends_once_and_changes_shared_capacity(self):
        def buy(_):
            with transaction(self.path) as db: return completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='parallel')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(buy,range(2)))
        self.assertEqual(sorted(r['replayed'] for r in results),[False,True])
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,985000)

    def test_clan_exchange_enforces_expansion_and_preserves_prior_overflow(self):
        with transaction(self.path) as db:
            db.executemany('INSERT INTO clan_items VALUES (?,?,?,?)',
                [(self.clan,1,0x40000000+n,encode_item_list(0,(replace(self.gun,instance_id=0x40000000+n),))) for n in range(32)])
            db.execute('UPDATE clans SET next_item=? WHERE id=?',(0x40000020,self.clan))
        self.inventory((self.gun,))
        before = self.state()
        with self.assertRaises(ValueError): self.clans.exchange('alice',1,1,deposits=((1,1),))
        self.assertEqual(self.state(),before)
        with transaction(self.path) as db: completion.clan_purchase(db,'alice',3,1,expected_clan=self.clan,identity='expand-full')
        self.clans.exchange('alice',1,1,deposits=((1,1),))
        self.assertEqual(len(self.clans.items('bob',1)),33)
        # A legacy overflowing safe must remain withdrawable before a purchase.
        kit = replace(self.gun,template_id=30,unknown_words=(1,)*3)
        with transaction(self.path) as db:
            db.executemany('INSERT INTO clan_items VALUES (?,?,?,?)',
                [(self.clan,2,0x50000000+n,encode_item_list(0,(replace(kit,instance_id=0x50000000+n),))) for n in range(33)])
        self.clans.exchange('alice',1,2,withdrawals=((0x50000000,1),))
        self.assertEqual(len(self.clans.items('alice',2)),32)

    def test_auction_can_select_shared_warehouse_item_from_another_town(self):
        from test_player_auction import create_packet
        self.stash(1);self.location('alice',2)
        auction = AUCTION.AuctionStore(self.path,pledge_percent=5)
        auction.create('alice','Alice',create_packet(instance=100),session='shared-warehouse',now=100)
        self.assertEqual(self.store.items('alice'),())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM player_auction_lots').fetchone()[0],1)

    def test_native_warehouse_projection_includes_all_deposit_locations(self):
        self.stash(1);self.location('alice',2);self.stash(1,first=200)
        packets = encode_private_warehouse_snapshot(self.store.items('alice'))
        self.assertEqual([i.instance_id for p in packets for i in decode_warehouse_list(p)[3]], [100,200])
        with transaction(self.path) as db:
            from tio.warehouse import WarehouseStore
            self.assertEqual(set(WarehouseStore._read(db,'alice')), {100,200})

    def test_delivery_rejects_inventory_alias_before_any_item_is_written(self):
        self.inventory((self.gun,));before = self.state()
        with transaction(self.path) as db:
            with self.assertRaises(ValueError):
                completion.stash(db,'alice',(replace(self.gun,instance_id=100),self.gun),origin='delivery-alias')
        self.assertEqual(self.state(),before)

    def test_pending_achievement_and_clan_prizes_survive_full_city_then_deliver_once(self):
        remote = self.stash(1,first=5000)
        self.location('alice',2);self.stash(32)
        store = ACHIEVEMENTS.AchievementStore(self.path)
        with transaction(self.path) as db:
            ACHIEVEMENTS.update(db,'alice',add={'kills':10})
            BENEFITS.schema(db)
            db.execute('INSERT INTO clan_assault_prizes VALUES (?,?,?,?,0)',('accepted-fixture-event','alice',5003,1))
        store.flush('alice')
        with transaction(self.path) as db:
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=? AND id=4 AND position=0',('alice',)).fetchone()[0],0)
            self.assertEqual(BENEFITS.deliver_prizes(db,'alice'),())
            self.assertEqual(db.execute('SELECT delivered FROM clan_assault_prizes WHERE account=?',('alice',)).fetchone()[0],0)
        self.store.exchange('alice',1,withdrawals=tuple((i,1) for i in range(100,106)))
        store.flush('alice')
        with transaction(self.path) as db:
            self.assertTrue(BENEFITS.deliver_prizes(db,'alice'))
            self.assertEqual(BENEFITS.deliver_prizes(db,'alice'),())
            self.assertEqual(db.execute('SELECT delivered FROM achievement_prizes WHERE account=? AND id=4 AND position=0',('alice',)).fetchone()[0],1)
            self.assertEqual(completion.status(db,'alice')['used'],32)
        self.location('alice',3)
        self.assertIn(remote[0],self.store.items('alice'))
        self.assertEqual(store.flush('alice'),())

    def test_mark_and_loan_can_use_shared_stock_and_expiry_restores_owner(self):
        self.stash(1);self.location('alice',2)
        with transaction(self.path) as db:
            mark = BANK.mark_item(db,'alice',100,1,'1234','shared-mark',now=100)
            BANK.lend_marked(db,'alice',mark['mark_id'],'bob','loan-mark',now=100)
        self.location('bob',13)
        self.assertEqual(len(self.store.items('bob')),1)
        with transaction(self.path) as db:
            self.assertEqual(BANK.expire_marks(db,now=86500),('alice','bob'))
        self.assertEqual(self.store.items('bob'),())
        self.assertEqual(len(self.store.items('alice')),1)
        self.assertFalse(self.store.items('alice')[0].unknown_bytes_02[2])

    def test_rental_remote_expiry_preserves_city_rows_and_emits_only_visible_snapshot(self):
        clock = [100]
        store = RENTAL.RentalStore(self.path,clock=lambda:clock[0])
        offer = next(o for o in store.offers.values() if o.item_id==301 and o.enhancement==10 and o.hours==3)
        with transaction(self.path) as db: db.execute('UPDATE wallets SET gold=10000 WHERE account=?',('alice',))
        packet,_ = store.handle('alice',b'\xb4\x10'+struct.pack('<IHIB',offer.lot_id,3,1,2))
        rented = decode_item_list(packet)[1][-1]
        self.store.exchange('alice',1,deposits=((rented.instance_id,1),))
        self.location('alice',2);visible = self.stash(1,first=5000)
        clock[0] += 10800
        packets = store.refresh('alice')
        projected = [i.instance_id for p in packets if p[:1]==b'\x6a' for i in decode_warehouse_list(p)[3]]
        self.assertEqual(projected,[5000])
        self.assertEqual(self.store.items('alice'),visible)
        self.location('alice',3)
        self.assertEqual(self.store.items('alice'),visible)


if __name__ == '__main__': unittest.main()
