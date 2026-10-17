from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import threading

from test_bank_economy import BankFixture
from tio import bank_economy as bank
from tio.db_transaction import transaction
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.item_marks import metadata
from tio.wallets import WalletStore
from tio.durability import repair_item
from server.economy_runtime import SharedEconomy,project_packet,private_command


def encode_send(channel,text):return bytes((0x21,channel))+text.encode('utf-16le')+b'\0\0'


class EconomyRuntimeTests(BankFixture):
    def test_only_genuine_marked_instance_receives_native_owner_projection(self):
        self.call(bank.mark_item,'alice',17,1,'1234','mark',now=self.now)
        packet=self.pets.inventory('alice',1)
        with patch('tio.bank_economy.time.time',return_value=self.now):
            self.assertEqual(metadata(project_packet(self.path,'alice',packet)),{17:('Alice',86400)})
            temporary=encode_item_list(1,(self.item,))
            self.assertEqual(project_packet(self.path,'alice',temporary),temporary)
        self.assertEqual(decode_item_list(packet)[1][0].optional_u32,None)

    def test_paid_gold_refresh_and_empty_account_login(self):
        with transaction(self.path) as db:
            db.execute("UPDATE wallets SET gold=? WHERE account='alice'",(bank.MAX,))
            db.execute("INSERT INTO bank_gold_payables VALUES ('alice',7)")
        self.assertEqual(WalletStore(self.path).ensure('alice').gold,bank.MAX)
        with transaction(self.path) as db:db.execute("UPDATE wallets SET gold=gold-10 WHERE account='alice'")
        self.assertEqual(WalletStore(self.path).ensure('alice').gold,bank.MAX-3)
        self.assertEqual(WalletStore(self.path).ensure('new-empty-login').gold,0)
        self.assertEqual(self.read("SELECT gold FROM bank_gold_payables WHERE account='alice'"),[(0,)])

    def test_marked_repair_preserves_owner_flag_and_wear(self):
        item=replace(self.item,unknown_bytes_02=b'\0\0\1\0',unknown_words=(100,300,300))
        kit=replace(self.item,instance_id=18,template_id=17,unknown_words=(100,100,100))
        fixed,*_=repair_item(item,kit)
        self.assertEqual(fixed.unknown_bytes_02,item.unknown_bytes_02)
        self.assertGreater(fixed.unknown_words[0],100)

    def test_offline_expiry_fenced_by_retained_owner_and_holder(self):
        mark=self.call(bank.mark_item,'alice',17,1,'1234','mark',now=self.now)
        self.call(bank.lend_marked,'alice',mark['mark_id'],'bob','lend',now=self.now)
        hub=SimpleNamespace(lock=threading.RLock(),private={},account_owners={'bob':2},retained=lambda a:a=='bob')
        router=SimpleNamespace(team_arena=hub,lock=threading.Lock(),active_accounts={})
        economy=SharedEconomy(self.path,clock=lambda:1)
        with patch('tio.bank_economy.time.time',return_value=self.now+86401):economy.tick(router)
        self.assertEqual(self.read('SELECT holder,state FROM bank_item_marks'),[('bob','active')])
        hub.account_owners.clear();hub.retained=lambda a:False;economy.next_tick=0
        with patch('tio.bank_economy.time.time',return_value=self.now+86401):economy.tick(router)
        self.assertEqual(self.read('SELECT holder,state FROM bank_item_marks'),[('alice','expired')])
        self.assertEqual(self.warehouse.items('alice')[0].unknown_words,(300,300,300))

    def test_bank_and_sc_are_private_even_in_battle_chat(self):
        self.assertTrue(private_command(encode_send(0,'!bank reclaim 17 1234 request_001')))
        self.assertTrue(private_command(encode_send(3,'!sc bid 1')))
        self.assertFalse(private_command(encode_send(0,'Привет')))
