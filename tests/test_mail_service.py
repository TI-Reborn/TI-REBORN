from collections import deque
from contextlib import closing
import sqlite3
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_mail
from server.presence import Presence
from server import mail_service as service
from tio.protocol import mail as wire
from tio.protocol.warehouse_transfer import WarehouseTransfer,encode_warehouse_transfer
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.warehouse import WarehouseStore


class Session:
    pass


class MailServiceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_mail.MailTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path;self.store=self.fixture.store;self.presence=Presence()
        trial=json.loads((test_mail.ROOT/'evidence/owned_pet_trial.json').read_text())
        OwnedPetStore(self.path).ensure('bob',bytes.fromhex(trial['packet_hex']),encode_item_list(1,()),human=True)
        self.sessions={}
        for owner in ('alice','bob','carol'):
            session=Session();session.__dict__.update(database=self.path,account=owner,owned_pet_probe=True,
                probe_character_id=1,arena=SimpleNamespace(_fields={},rooms=SimpleNamespace(snapshot=lambda:())),
                survival=SimpleNamespace(searching=lambda actor:False),locations=SimpleNamespace(current=lambda owner:3),
                router=SimpleNamespace(mail_store=self.store,team_arena=SimpleNamespace(busy=lambda session:False)))
            self.sessions[owner]=session;self.presence.players[session]=(3,None)
            self.presence.messages[session]=deque()

    def command(self,owner,packet):
        session=self.sessions[owner];self.presence.messages[session].clear()
        self.assertTrue(service.handle(self.presence,session,packet))
        return tuple(self.presence.messages[session])

    def test_item_quote_escrow_offline_claim_and_untrusted_echo(self):
        reply=self.command('alice',wire.encode_draft(wire.DraftRequest(0,b'Bobby','Подарок','Вложения',((1,2),))))
        preview=wire.decode_body(reply[0]);self.assertEqual(preview.price,125)
        self.assertEqual((preview.items[0].enhance,preview.items[0].damage_enhance,preview.items[0].special_enhance),(2,3,True))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,3000)
        self.presence.players.pop(self.sessions['bob'])
        self.command('alice',wire.encode_body_request(wire.BodyRequest(1,0,'Подарок','Вложения',0,
            (wire.ClaimItem(999,324,1000000),))))
        ident=self.store.listing('bob')[0]['id']
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,2875)
        self.assertEqual(WarehouseStore(self.path).items('alice')[0].count,3)
        delivered=wire.decode_body(self.command('bob',wire.encode_body_request(wire.BodyRequest(0,ident)))[0])
        self.assertEqual(delivered.items[0],preview.items[0])
        claim=wire.encode_body_request(wire.BodyRequest(1,ident,items=(wire.ClaimItem(1,1,999999),)))
        self.command('bob',claim)
        self.assertEqual(len(self.store.read('bob',ident)['items']),1)
        transfer=encode_warehouse_transfer(WarehouseTransfer(3,1,(),((delivered.items[0].identity,2),)))
        self.command('bob',transfer);self.command('bob',transfer)
        self.assertEqual(sum(i.count for i in decode_item_list(OwnedPetStore(self.path).inventory('bob',1))[1]),2)
        self.assertEqual(WarehouseStore(self.path).items('bob'),())
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3000)

    def test_quote_required_and_modified_money_or_text_rejected(self):
        self.assertEqual(self.command('alice',wire.encode_body_request(wire.BodyRequest(1,0)))[0][:1],b'\xf0')
        self.command('alice',wire.encode_money(wire.MoneyRequest(b'Bobby',20)))
        self.assertEqual(self.command('alice',wire.encode_money(wire.MoneyRequest(b'Bobby',21,False)))[0][:1],b'\xf0')
        self.assertEqual(self.command('alice',wire.encode_body_request(wire.BodyRequest(1,0,'Changed')))[0][:1],b'\xf0')
        self.assertEqual(self.store.listing('bob'),())
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,3000)

    def test_battle_and_foreign_letter_do_not_mutate_wallets(self):
        ident=self.store.send('alice',b'Bobby',credits=10,request_id='service-request-00001')
        self.sessions['bob'].router.team_arena.busy=lambda session:True
        self.assertEqual(self.command('bob',wire.encode_body_request(wire.BodyRequest(1,ident)))[0][:1],b'\xf0')
        self.assertEqual(self.command('carol',wire.encode_body_request(wire.BodyRequest(1,ident)))[0][:1],b'\xf0')
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3000)
        self.assertEqual(self.store.read('bob',ident)['state'],'pending')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM mail_receipts WHERE action='claimed'").fetchone()[0],0)

    def test_gold_pseudo_items_are_rejected_without_quote_or_debit(self):
        for pairs in (((0xffff0002,1),),((service.CREDITS_ID,1),(service.CREDITS_ID,2))):
            self.assertEqual(self.command('alice',wire.encode_draft(wire.DraftRequest(0,b'Bobby',items=pairs)))[0][:1],b'\xf0')
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,3000)

    def test_successful_money_claim_reply_survives_optional_post_list_overflow(self):
        ident=self.store.send('alice',b'Bobby',credits=10,request_id='service-request-overflow')
        with patch.object(service,'warehouse',side_effect=service.PacketError('Mail packet exceeds frame policy')):
            replies=self.command('bob',wire.encode_body_request(wire.BodyRequest(1,ident)))
        self.assertTrue(any(p.startswith(b'\xb7\x7a') for p in replies))
        self.assertTrue(any(p.startswith(b'\xb7\x79') for p in replies))
        self.assertFalse(any(p.startswith(b'\xf0') for p in replies))
        self.assertEqual(WalletStore(self.path).ensure('bob').credits,3010)


if __name__=='__main__':unittest.main()
