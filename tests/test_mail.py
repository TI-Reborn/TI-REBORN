from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.mail import MailStore
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore
from tio.owned_pets import OwnedPetStore
from tio.inventory_capacity import INVENTORY_SLOTS

ROOT=Path(__file__).resolve().parents[1]


class MailTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'mail.sqlite3'
        characters=CharacterStore(self.path)
        for owner,name in (('alice',b'Alice'),('bob',b'Bobby'),('carol',b'Carol')):
            characters.create(owner,CharacterCreateRequest(name,0,(0,0,0,0)))
            WalletStore(self.path).ensure(owner)
        self.store=MailStore(self.path)
        self.item=replace(decode_item_list(bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['inventory_packet_hex']))[1][0],
            instance_id=1,template_id=301,unknown_u32_01=5,unknown_u8_01=0,location_raw=0,unknown_bytes_02=bytes(4),optional_u32=None,
            unknown_words=(20,35,40),unknown_bytes_03=bytes((2,3,1)))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('alice',1,encode_item_list(0,(self.item,))))

    def send(self,**kwargs):
        return self.store.send('alice',b'Bobby','Предметы','Доставка',request_id='test-request-0001',now=100,**kwargs)

    def test_offline_send_restart_and_exactly_once_receive(self):
        ident=self.send(credits=200,items=((1,2),))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,3000-200-100-10-25)
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].count,3)
        reopened=MailStore(self.path)
        self.assertEqual(reopened.listing('bob',now=101)[0]['attachments'],1)
        viewed=reopened.read('bob',ident,now=101)
        self.assertEqual(viewed['body'],'Доставка')
        reopened.claim('bob',ident,now=102);reopened.claim('bob',ident,now=103)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3200)
        received=WarehouseStore(self.path).items('bob')
        self.assertEqual(received,(replace(self.item,unknown_u32_01=2),))
        self.assertEqual(reopened.read('bob',ident,now=104)['items'],())

    def test_same_request_replay_and_conflicting_retry(self):
        first=self.send(credits=500)
        self.assertEqual(self.send(credits=500),first)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,2375)
        with self.assertRaises(ValueError):self.send(credits=501)
        self.assertEqual(len(self.store.listing('bob',now=101)),1)

    def test_foreign_recipient_cannot_read_claim_or_delete(self):
        ident=self.send(credits=200)
        for method in (self.store.read,self.store.claim,self.store.delete):
            with self.assertRaises(ValueError):method('carol',ident,now=101)
        self.assertEqual(WalletStore(self.path).ensure('carol').credits,3000)
        self.assertEqual(self.store.read('bob',ident,now=101)['state'],'pending')

    def test_expiry_at_ten_day_boundary_destroys_escrow_no_refund(self):
        ident=self.send(credits=200,items=((1,5),));last=100+864000
        self.assertEqual(self.store.read('bob',ident,now=last-1)['state'],'pending')
        with self.assertRaises(ValueError):self.store.claim('bob',ident,now=last)
        self.store.expire(now=last)
        self.assertEqual(self.store.listing('bob',now=last),())
        self.assertEqual(WarehouseStore(self.path).items('alice'),())
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3000)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM mail_items').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM mail_receipts WHERE action='expired'").fetchone()[0],1)

    def test_two_concurrent_claims_have_one_delivery_and_receipt(self):
        ident=self.send(credits=300,items=((1,5),))
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _:MailStore(self.path).claim('bob',ident,now=101),range(2)))
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3300)
        self.assertEqual(sum(i.count for i in WarehouseStore(self.path).items('bob')),5)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail_receipts WHERE action='claimed'").fetchone()[0],1)

    def test_insufficient_credit_or_quantity_rolls_back_everything(self):
        for arguments in (dict(credits=3000),dict(items=((1,6),)),dict(items=((1,1),(1,1)))):
            with self.assertRaises(ValueError):self.send(**arguments)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,3000)
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].count,5)
        self.assertEqual(self.store.listing('bob',now=101),())

    def test_recipient_overflow_preserves_all_escrow(self):
        ident=self.send(credits=300,items=((1,5),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE wallets SET credits=? WHERE account=?',(0xffffffff,'bob'))
        with self.assertRaises(ValueError):self.store.claim('bob',ident,now=101)
        self.assertEqual(len(self.store.read('bob',ident,now=101)['items']),1)
        self.assertEqual(WarehouseStore(self.path).items('bob'),())
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE wallets SET credits=0 WHERE account='bob'")
        self.store.claim('bob',ident,now=102)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,300)

    def test_secondary_character_mail_does_not_touch_first_wallet(self):
        characters=CharacterStore(self.path)
        characters.create('bob',CharacterCreateRequest(b'SecondBob',0,(0,0,0,0)))
        secondary=characters.owner('bob',2)
        WalletStore(self.path).ensure(secondary)
        ident=self.store.send('alice',b'SecondBob',credits=400,request_id='secondary-request-01',now=100)
        with self.assertRaises(ValueError):self.store.claim('bob',ident,now=101)
        self.store.claim(secondary,ident,now=101)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3000)
        self.assertEqual(WalletStore(self.path).ensure(secondary).credits,3400)

    def test_recipient_instance_ids_allocated_without_collision(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('bob',1,encode_item_list(0,(self.item,))))
        ident=self.send(items=((1,5),))
        self.store.claim('bob',ident,now=101)
        self.assertEqual([i.instance_id for i in WarehouseStore(self.path).items('bob')],[1,2])

    def pet(self,owner='bob',items=()):
        raw=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        OwnedPetStore(self.path).ensure(owner,raw,encode_item_list(1,items),human=True)
        if items:
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',(encode_item_list(1,items),owner))

    def escrow(self,ident):return self.store.read('bob',ident,now=101)['items'][0]

    def test_take_money_does_not_take_items_and_replay_does_not_credit_twice(self):
        ident=self.send(credits=200,items=((1,5),))
        self.assertFalse(self.store.read('bob',ident,now=101)['money_claimed'])
        row=self.store.take_money('bob',ident,now=102)
        self.assertTrue(row['money_claimed']);self.assertEqual(row['state'],'pending')
        self.assertEqual(self.store.listing('bob',now=102)[0]['money_claimed'],True)
        self.store.take_money('bob',ident,now=103)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3200)
        self.assertEqual(self.escrow(ident).count,5);self.assertFalse(WarehouseStore(self.path).items('bob'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail_receipts WHERE action='money_claimed'").fetchone()[0],1)

    def test_money_only_take_finishes_and_legacy_claim_after_money_has_no_second_credit(self):
        ident=self.send(credits=200,items=((1,5),))
        self.store.take_money('bob',ident,now=102);self.store.claim('bob',ident,now=103)
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3200)
        self.assertEqual(self.store.read('bob',ident,now=103)['state'],'claimed')
        self.assertEqual(WarehouseStore(self.path).items('bob')[0].count,5)
        other=self.store.send('alice',b'Bobby',credits=10,request_id='money-only-request01',now=100)
        self.assertEqual(self.store.take_money('bob',other,now=102)['state'],'claimed')
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3210)

    def test_item_escrow_ids_unique_across_letters_senders_and_partial_remainder(self):
        first=self.send(items=((1,2),))
        other=self.store.send('alice',b'Bobby',items=((1,3),),request_id='second-items-request1',now=100)
        one=self.escrow(first).instance_id;two=self.escrow(other).instance_id
        self.assertNotEqual(one,two);self.pet()
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('carol',1,encode_item_list(0,(self.item,))))
        third=self.store.send('carol',b'Bobby',items=((1,1),),request_id='other-sender-request',now=100)
        three=self.escrow(third).instance_id
        self.store.withdraw('bob',1,items=((one,1),),now=102)
        remainder=self.escrow(first).instance_id
        self.assertEqual(len({one,two,three,remainder}),4)

    def test_partial_withdraw_retires_alias_replay_conflict_and_preserves_metadata(self):
        self.pet();ident=self.send(items=((1,5),));source=self.escrow(ident)
        packet=self.store.withdraw('bob',1,items=((source.instance_id,2),),now=102)
        delivered=decode_item_list(packet)[1][0];remaining=self.escrow(ident)
        self.assertEqual(delivered,replace(self.item,instance_id=delivered.instance_id,unknown_u32_01=2))
        self.assertEqual(remaining.count,3);self.assertNotEqual(remaining.instance_id,source.instance_id)
        self.assertEqual(self.store.withdraw('bob',1,items=((source.instance_id,2),),now=103),packet)
        with self.assertRaisesRegex(ValueError,'изменён'):self.store.withdraw('bob',1,items=((source.instance_id,1),),now=103)
        last=self.store.withdraw('bob',1,items=((remaining.instance_id,3),),now=104)
        self.assertEqual(sum(item.count for item in decode_item_list(last)[1]),5)
        self.assertEqual(self.store.read('bob',ident,now=104)['state'],'claimed')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail_receipts WHERE action LIKE 'items:%'").fetchone()[0],2)

    def test_items_first_leave_money_pending_and_complete_after_money_take(self):
        self.pet();ident=self.send(credits=100,items=((1,5),));item=self.escrow(ident)
        self.store.withdraw('bob',1,items=((item.instance_id,5),),now=102)
        row=self.store.read('bob',ident,now=102)
        self.assertEqual(row['state'],'pending');self.assertFalse(row['money_claimed']);self.assertFalse(row['items'])
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3000)
        self.assertEqual(self.store.take_money('bob',ident,now=103)['state'],'claimed')
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3100)

    def test_foreign_escrow_and_foreign_or_missing_pet_cannot_withdraw(self):
        self.pet();self.pet('carol');ident=self.send(items=((1,5),));source=self.escrow(ident)
        for owner,pet in (('carol',1),('bob',2)):
            with self.assertRaises(ValueError):self.store.withdraw(owner,pet,items=((source.instance_id,5),),now=102)
        with self.assertRaises(ValueError):self.store.take_money('carol',ident,now=102)
        self.assertEqual(self.escrow(ident).count,5);self.assertFalse(decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1])

    def test_expired_escrow_cannot_be_withdrawn(self):
        self.pet();ident=self.send(items=((1,5),));source=self.escrow(ident)
        with self.assertRaises(ValueError):self.store.withdraw('bob',1,items=((source.instance_id,5),),now=864100)
        self.assertFalse(decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1])

    def test_withdraw_allocates_above_all_pet_warehouse_and_sequence_ids(self):
        self.pet(items=(replace(self.item,instance_id=50,template_id=301,unknown_u32_01=1),))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('bob',80,encode_item_list(0,(replace(self.item,instance_id=80),))))
            db.execute("INSERT INTO item_sequences VALUES ('bob',100)")
        ident=self.send(items=((1,5),));source=self.escrow(ident)
        packet=self.store.withdraw('bob',1,items=((source.instance_id,5),),now=102)
        self.assertEqual([item.instance_id for item in decode_item_list(packet)[1]],[50,100])

    def test_full_inventory_or_quantity_failure_rolls_back_escrow_and_sequences(self):
        old=tuple(replace(self.item,instance_id=1000+i,template_id=301,unknown_u32_01=1) for i in range(INVENTORY_SLOTS))
        self.pet(items=old);ident=self.send(items=((1,5),));source=self.escrow(ident)
        with closing(sqlite3.connect(self.path)) as db:
            next_id=db.execute('SELECT next_id FROM mail_item_sequence').fetchone()[0]
        for count in (6,1):
            with self.assertRaises(ValueError):self.store.withdraw('bob',1,items=((source.instance_id,count),),now=102)
        self.assertEqual(self.escrow(ident),source)
        self.assertEqual(decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1],old)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT next_id FROM mail_item_sequence').fetchone()[0],next_id)
            self.assertFalse(db.execute("SELECT 1 FROM mail_receipts WHERE action LIKE 'items:%'").fetchone())

    def test_concurrent_partial_replays_deliver_one_quantity(self):
        self.pet();ident=self.send(items=((1,5),));source=self.escrow(ident)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _:MailStore(self.path).withdraw('bob',1,items=((source.instance_id,2),),now=102),range(2)))
        self.assertEqual(sum(item.count for item in decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1]),2)
        self.assertEqual(self.escrow(ident).count,3)

    def test_unknown_item_weight_rolls_back_inventory_escrow_receipts_and_sequences(self):
        self.pet(items=(replace(self.item,instance_id=50,unknown_u32_01=1),))
        unknown=replace(self.item,template_id=81)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=1',
                       (encode_item_list(0,(unknown,)),'alice'))
            db.execute("INSERT INTO item_sequences VALUES ('bob',100)")
        ident=self.send(items=((1,5),));source=self.escrow(ident)
        before_inventory=OwnedPetStore(self.path).inventory('bob',1)
        def saved_state():
            with closing(sqlite3.connect(self.path)) as db:
                return (
                    db.execute('SELECT * FROM mail_items ORDER BY message,position').fetchall(),
                    db.execute('SELECT * FROM mail_receipts ORDER BY message,action').fetchall(),
                    db.execute('SELECT * FROM mail_item_sequence').fetchall(),
                    db.execute('SELECT * FROM item_sequences ORDER BY account').fetchall(),
                    db.execute('SELECT * FROM mail_messages ORDER BY id').fetchall(),
                )
        before=saved_state()
        with self.assertRaisesRegex(ValueError,'Unknown item'):
            self.store.withdraw('bob',1,items=((source.instance_id,2),),now=102)
        self.assertEqual(OwnedPetStore(self.path).inventory('bob',1),before_inventory)
        self.assertEqual(saved_state(),before)
        self.assertEqual(self.escrow(ident),source)

if __name__=='__main__':unittest.main()
