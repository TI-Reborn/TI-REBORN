from contextlib import closing
import json
from pathlib import Path
import secrets
import struct
import tempfile
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from tio import battle_rewards, battle_settlement, reservation_quests as quests
from tio.city_catalogs import CityCatalogs
from tio.db_transaction import connect, transaction
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
from tio.shop import ShopStore
from tio.wallets import WalletStore

ROOT = Path(__file__).resolve().parents[1]


class ReservationQuestTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'quests.sqlite3'
        self.shop = ShopStore(self.path, CityCatalogs(ROOT / 'config/city_catalogs.json'))
        trial = json.loads((ROOT / 'evidence/owned_pet_trial.json').read_text())
        for owner in ('newbie', 'peer'):
            OwnedPetStore(self.path).ensure(
                owner, bytes.fromhex(trial['packet_hex']), encode_item_list(1, ()), human=True)
            WalletStore(self.path).ensure(owner)
        with closing(connect(self.path)) as db, db:
            db.execute('UPDATE wallets SET credits=10000')

    def buy(self, owner, template, receipt=None):
        offer = next(entry for entry in self.shop.catalogs.items[0] if entry.item_id == template)
        return self.shop.purchase(owner, ShopPurchase(1, 0, offer.unknown_u32_01, 1),
                                  identity=receipt)

    def test_purchases_and_durable_victory_advance_only_their_owner(self):
        self.buy('newbie', 245)
        quests.act(self.path, 'newbie', 'accept_welcome')
        with self.assertRaises(ValueError):
            quests.act(self.path, 'newbie', 'accept_survival')
        self.buy('newbie', 245, 'helmet')
        self.buy('newbie', 245, 'helmet')
        self.buy('peer', 246)
        self.buy('newbie', 3)
        self.assertEqual(quests.state(self.path, 'newbie')['purchases'], [245])
        self.assertEqual(quests.state(self.path, 'peer')['purchases'], [])
        for template in (246, 247, 301):
            self.buy('newbie', template)
        self.assertEqual(quests.state(self.path, 'newbie')['welcome'], 'ready')
        quests.act(self.path, 'newbie', 'turn_in_welcome')
        quests.act(self.path, 'newbie', 'accept_survival')
        self.assertEqual(quests.active_survivors(self.path, ['peer', 'newbie']), {'newbie'})
        battle_rewards.settle(self.path, 'newbie', 'other-mode', 1)
        battle_rewards.settle(self.path, 'newbie', 'loss', 0, reservation_survival=True)
        self.assertEqual(quests.state(self.path, 'newbie')['survival'], 'active')
        self.assertEqual(quests.state(self.path, 'newbie')['outcome'], 0)
        battle_settlement.enqueue(self.path, 'win', [
            ('newbie', 1, {'reservation_survival': True}),
            ('peer', 0, {}),
        ])
        self.assertCountEqual(battle_settlement.retry(self.path, force=True), [('win', 'newbie'), ('win', 'peer')])
        battle_settlement.apply(self.path, 'win', 'newbie')
        self.assertEqual(quests.act(self.path, 'newbie', 'turn_in_survival')['survival'], 'done')
        self.assertEqual(quests.act(self.path, 'newbie', 'turn_in_survival')['survival'], 'done')
        self.assertEqual(quests.state(self.path, 'peer')['survival'], 'locked')

    def test_rolled_back_purchase_never_credits_quest_and_escape_never_wins(self):
        quests.act(self.path, 'newbie', 'accept_welcome')
        with self.assertRaisesRegex(ValueError, 'rollback'):
            with transaction(self.path):
                self.buy('newbie', 245)
                raise ValueError('rollback')
        self.assertEqual(quests.state(self.path, 'newbie')['purchases'], [])
        for template in (245, 246, 247, 301):
            self.buy('newbie', template)
        quests.act(self.path, 'newbie', 'turn_in_welcome')
        quests.act(self.path, 'newbie', 'accept_survival')
        battle_rewards.settle(self.path, 'newbie', 'escaped', 1, escaped=True,
                              reservation_survival=True)
        self.assertEqual(quests.state(self.path, 'newbie')['survival'], 'active')


class ReservationQuestTcpTests(unittest.TestCase):
    def test_two_clients_buy_and_finish_one_authoritative_survival(self):
        from test_game_tls import GameTLSTests

        tls = GameTLSTests()
        tls.setUp()
        self.addCleanup(tls.doCleanups)
        tls.case.config = replace(tls.case.config, contracts_enabled=True)
        tls.case.start()
        original_connect = tls.connect
        tokens = {account: secrets.token_bytes(32) for account in ('alice', 'bob')}
        bridge_token = None

        def connect(kind, *, preface=None, **kwargs):
            if kind == 'login' and preface is not None:
                preface = preface[:4] + b'\x03' + preface[5:] + bytes(38) + bridge_token
            return original_connect(kind, preface=preface, **kwargs)

        tls.connect = connect
        clients = {}
        for index, account in enumerate(tokens, 31001):
            bridge_token = tokens[account]
            client = tls.handoff(tls.begin(account, index))
            tls.case.enter(client, account.capitalize())
            clients[account] = client

        def control(account, action):
            request = {'action': 'location_npcs'} if action == 'location_npcs' else {
                'action': 'ruth', 'value': action}
            body = json.dumps(request).encode()
            with original_connect('login') as channel:
                channel.sendall(struct.pack('!4sBBH', b'TIOC', 1, 0, len(body))
                                + bytes(38) + tokens[account] + body)
                with channel.makefile('rb') as response:
                    reply = json.loads(response.read(int.from_bytes(response.read(4), 'big')))
            time.sleep(.16)
            return reply

        alice, bob = (clients[name] for name in ('alice', 'bob'))
        catalog = CityCatalogs(ROOT / 'config/city_catalogs.json')
        def available_npc(account):
            menu = control(account, 'location_npcs')['state']
            self.assertEqual(menu['town'], 3)
            self.assertEqual([(npc['id'], npc['name']) for npc in menu['npcs']], [('ruth', 'Рут Восс')])
            return menu['npcs'][0]['has_available_quest']

        self.assertTrue(available_npc('alice'))
        for account, client in clients.items():
            self.assertTrue(control(account, 'accept_welcome')['ok'])
            self.assertFalse(available_npc(account))
            if account == 'alice':
                self.assertTrue(available_npc('bob'))
            for template in (245, 246, 247, 301):
                offer = next(item for item in catalog.items[0] if item.item_id == template)
                client.send(encode_shop_purchase(ShopPurchase(1, 0, offer.unknown_u32_01, 1)))
                tls.case.ping(client)
            tls.until(lambda: quests.state(tls.case.config.database, account)['welcome'] == 'ready')
            self.assertFalse(available_npc(account))
            self.assertTrue(control(account, 'turn_in_welcome')['ok'])
            self.assertTrue(available_npc(account))
            self.assertTrue(control(account, 'accept_survival')['ok'])
            self.assertFalse(available_npc(account))
            client.send(b'\xba\x03\0\x01')
        alice.until(b'\x41')
        bob.until(b'\x41')
        alice.send(b'\x36')
        bob.send(b'\x36')
        hub = tls.case.server.multi.team_arena
        tls.until(lambda: any(match['reward_started'] for match in hub.battles.copy().values()))
        self.assertEqual(control('alice', 'location_npcs')['state'], {'town': None, 'npcs': []})
        with patch('server.battle_reconnect.RECONNECT_SECONDS', .01):
            bob.sock.close()
            alice.until(b'\x4c')
        alice.send(b'\x2a\x01')
        tls.case.ping(alice)
        self.assertEqual(control('alice', 'turn_in_survival')['state']['survival'], 'done')
        self.assertFalse(available_npc('alice'))
        self.assertEqual(quests.state(tls.case.config.database, 'bob')['survival'], 'active')
