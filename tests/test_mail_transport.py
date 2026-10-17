"""Original mail packets over two actual encrypted TCP account sessions.

All fixtures and sockets are temporary/local; no hosted account data is used.
"""
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import test_multi_account as network
from tio.owned_pets import OwnedPetStore
from tio.protocol import mail as wire
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.item_list import decode_item_list,encode_item_list
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore

CREDITS_ID=0xffff0001
ERROR=b'\xf0\x8a\x01\0\0'


class MailTransportTests(unittest.TestCase):
    evidence=[]

    def setUp(self):
        self.case=network.MultiAccountTests('test_server_load_counts_unique_accounts_and_releases_disconnects')
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.config.database
        for owner,name in (('mail_alice','MailAlice'),('mail_bob','MailBob')):
            self.case.accounts.create(owner,network.PASSWORD,character=name)
            assets=WalletStore(self.path).ensure(owner)
            self.assertEqual((assets.credits,assets.gold),(3000,0))
        trial=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
        self.item=replace(decode_item_list(bytes.fromhex(trial['inventory_packet_hex']))[1][0],
            instance_id=900001,unknown_u32_01=5,
            unknown_u8_01=0,location_raw=0,unknown_bytes_02=bytes(4),optional_u32=None,
            unknown_bytes_03=bytes(3))
        WarehouseStore(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',('mail_alice',self.item.instance_id,encode_item_list(0,(self.item,))))
        self.case.start()

    def login(self,owner,name):
        peer=self.case.handoff(self.case.begin(owner));self.case.enter(peer,name)
        return peer

    def disconnect(self,peer,owner):
        peer.sock.close();deadline=time.monotonic()+5
        while owner in self.case.server.multi.active_accounts:
            if time.monotonic()>deadline:self.fail('Mail account authentication claim not released')
            time.sleep(.01)

    def command(self,peer,packet):
        peer.send(packet);peer.send(b'\x70');replies=[]
        for _ in range(100):
            reply=peer.receive()
            if reply==b'\x9e':return tuple(replies)
            replies.append(reply)
        self.fail('Mail command did not complete through TCP')

    def reply(self,replies,prefix):
        candidates=[packet for packet in replies if packet.startswith(prefix)]
        self.assertTrue(candidates,'Missing native reply '+prefix.hex()+'; received '+','.join(p[:5].hex() for p in replies))
        return candidates[-1]

    def fingerprint(self):
        with closing(sqlite3.connect(self.path)) as db:
            queries=(
                'SELECT account,credits,gold FROM wallets ORDER BY account',
                'SELECT account,instance_id,item_packet FROM warehouse_items ORDER BY account,instance_id',
                'SELECT account,pet_id,inventory_packet FROM owned_pets ORDER BY account,pet_id',
                'SELECT * FROM mail_items ORDER BY message,position',
                'SELECT id,credits,state FROM mail_messages ORDER BY id',
                'SELECT * FROM mail_receipts ORDER BY message,action',
            )
            return tuple(tuple(db.execute(query)) for query in queries)

    def rejected(self,peer,packet):
        before=self.fingerprint();replies=self.command(peer,packet)
        self.reply(replies,ERROR);self.assertEqual(self.fingerprint(),before)

    def inventory(self,owner):return OwnedPetStore(self.path).inventory(owner,1)

    def quantity(self,owner):
        return sum(i.count for i in decode_item_list(self.inventory(owner))[1] if i.template_id==self.item.template_id)

    def transfer(self,peer,identity,count,*,actor=1,deposit=False):
        pairs=((identity,count),)
        return self.command(peer,encode_warehouse_transfer(WarehouseTransfer(3,actor,pairs if deposit else (),() if deposit else pairs)))

    def test_offline_native_delivery_money_partial_items_replay_and_relogin(self):
        a=self.login('mail_alice','MailAlice')
        b=self.login('mail_bob','MailBob')
        baseline=self.quantity('mail_bob');before_inventory=self.inventory('mail_bob')
        self.disconnect(b,'mail_bob')
        self.assertNotIn('mail_bob',self.case.server.multi.active_accounts)

        draft=wire.DraftRequest(0,b'MailBob','Доставка','Проверка почты',((CREDITS_ID,10),(self.item.instance_id,5)))
        preview=wire.decode_body(self.reply(self.command(a,wire.encode_draft(draft)),b'\xb7\x7a'))
        self.assertEqual((preview.identity,preview.price),(0,126))
        self.assertEqual(WalletStore(self.path).ensure('mail_alice').credits,3000)
        self.assertEqual(WarehouseStore(self.path).items('mail_alice'),(self.item,))
        quoted=wire.decode_body(self.reply(self.command(a,wire.encode_recalculate()),b'\xb7\x7a'))
        self.assertEqual(quoted,preview)
        confirm=wire.encode_body_request(wire.BodyRequest(1,0,draft.subject,draft.body))
        self.assertEqual(decode_asset_count(self.reply(self.command(a,confirm),b'\xc8\x39')).credits,2864)
        self.assertEqual(WarehouseStore(self.path).items('mail_alice'),())
        # The stored draft token makes native confirmation retransmission inert.
        self.assertEqual(decode_asset_count(self.reply(self.command(a,confirm),b'\xc8\x39')).credits,2864)

        b=self.login('mail_bob','MailBob')
        rows=wire.decode_list(self.reply(self.command(b,wire.encode_page()),b'\xb7\x79'))[2]
        self.assertEqual(len(rows),1);identity=rows[0].identity
        self.assertEqual((rows[0].sender,rows[0].subject,rows[0].attachments),('MailAlice',draft.subject,2))
        received=wire.decode_body(self.reply(self.command(b,wire.encode_body_request(wire.BodyRequest(0,identity))),b'\xb7\x7a'))
        money=next(i for i in received.items if i.template==1)
        item=next(i for i in received.items if i.template==self.item.template_id)
        self.assertEqual((money.count,item.count),(10,5))
        self.assertNotEqual(item.identity,self.item.instance_id)
        self.assertEqual((received.subject,received.body),(draft.subject,draft.body))

        # Foreign mail/body access, foreign pet, deposits, duplicate/overflow
        # quantities fail over the real router without mutating game assets.
        self.rejected(a,wire.encode_body_request(wire.BodyRequest(0,identity)))
        self.rejected(a,encode_warehouse_transfer(WarehouseTransfer(3,1,(),((item.identity,1),))))
        self.rejected(b,encode_warehouse_transfer(WarehouseTransfer(3,77,(),((item.identity,1),))))
        self.rejected(b,encode_warehouse_transfer(WarehouseTransfer(3,1,((item.identity,1),),())))
        self.rejected(b,encode_warehouse_transfer(WarehouseTransfer(3,1,(),((item.identity,0xffffffff),))))
        self.rejected(b,encode_warehouse_transfer(WarehouseTransfer(3,1,(),((item.identity,1),(item.identity,1)))))

        # Recipient wallet overflow must leave money and item escrow available.
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=? WHERE account='mail_bob'",(0xffffffff,))
        take=wire.encode_body_request(wire.BodyRequest(1,identity,items=(wire.ClaimItem(0xfffffffc,324,0xffffffff),)))
        self.rejected(b,take)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE wallets SET credits=3000 WHERE account='mail_bob'")
        take_reply=self.command(b,take)
        self.assertEqual(decode_asset_count(self.reply(take_reply,b'\xc8\x39')).credits,3010)
        self.assertEqual(self.inventory('mail_bob'),before_inventory)
        remaining=wire.decode_body(self.reply(take_reply,b'\xb7\x7a'))
        self.assertEqual([(i.template,i.count) for i in remaining.items],[(self.item.template_id,5)])
        self.assertEqual(decode_asset_count(self.reply(self.command(b,take),b'\xc8\x39')).credits,3010)

        for query in (b'\x69\x03',b'\xb7\x0b'):
            post=wire.decode_post_warehouse(self.reply(self.command(b,query),b'\xb7\x75'))
            self.assertEqual(len(post),1)
            self.assertEqual((post[0].identity,post[0].item.identity,post[0].item.count),(identity,item.identity,5))

        partial=self.transfer(b,item.identity,2)
        self.assertEqual(decode_item_list(self.reply(partial,b'\x30'))[0],1)
        self.assertEqual(self.quantity('mail_bob'),baseline+2)
        post=wire.decode_post_warehouse(self.reply(partial,b'\xb7\x75'))
        self.assertEqual(len(post),1);remaining_id=post[0].item.identity
        self.assertNotEqual(remaining_id,item.identity);self.assertEqual(post[0].item.count,3)
        unchanged=self.inventory('mail_bob')
        repeated=self.transfer(b,item.identity,2)
        self.assertEqual(self.inventory('mail_bob'),unchanged)
        self.assertEqual(wire.decode_post_warehouse(self.reply(repeated,b'\xb7\x75'))[0].item.identity,remaining_id)
        self.rejected(b,encode_warehouse_transfer(WarehouseTransfer(3,1,(),((item.identity,1),))))

        finished=self.transfer(b,remaining_id,3)
        self.assertEqual(wire.decode_post_warehouse(self.reply(finished,b'\xb7\x75')),())
        self.assertEqual(self.quantity('mail_bob'),baseline+5)
        unchanged=self.inventory('mail_bob');self.transfer(b,remaining_id,3)
        self.assertEqual(self.inventory('mail_bob'),unchanged)
        self.assertEqual(WalletStore(self.path).ensure('mail_bob').credits,3010)
        self.assertEqual(WalletStore(self.path).ensure('mail_alice').credits,2864)

        self.disconnect(a,'mail_alice');self.disconnect(b,'mail_bob')
        self.case.stop();self.case.start()
        b=self.login('mail_bob','MailBob')
        self.assertEqual(self.inventory('mail_bob'),unchanged)
        self.assertEqual(WalletStore(self.path).ensure('mail_bob').credits,3010)
        self.assertEqual(wire.decode_post_warehouse(self.reply(self.command(b,b'\x69\x03'),b'\xb7\x75')),())
        self.transfer(b,item.identity,2);self.assertEqual(self.inventory('mail_bob'),unchanged)
        self.assertEqual(decode_asset_count(self.reply(self.command(b,take),b'\xc8\x39')).credits,3010)
        self.evidence.append(dict(test=self.id(),transport='two original encrypted TCP sessions',
            new_wallets=dict(credits=3000,gold=0),fee=126,transferred_credits=10,transferred_items=5,
            partial_items=2,remainder_items=3,sender_credits=2864,recipient_credits=3010,
            rejected_without_mutation=['foreign letter','foreign escrow','foreign pet','deposit','quantity overflow','duplicate selection','wallet overflow','modified replay'],
            replay_inert=True,partial_alias_rotated=True,restart_relogin_persists=True))


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(MailTransportTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        output=ROOT/'reports/stage7/mail-transport-validation.json'
        output.write_text(json.dumps(dict(passed=True,tests=result.testsRun,skipped=len(result.skipped),
            scope=__doc__,cases=MailTransportTests.evidence),ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
