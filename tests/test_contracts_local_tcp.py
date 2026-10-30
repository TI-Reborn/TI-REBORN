"""Authenticated loopback TCP coverage; this does not validate graphical clients."""
from contextlib import closing
from dataclasses import replace
import json
import socket
import sqlite3
import struct
import threading
import time
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
import zlib

import test_multi_account as account_fixture
from server.runtime import Server
from tio.characters import CharacterStore
from tio.owned_pets import OwnedPetStore
from tio.onboarding import prepare
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.character_select import decode_character_list
from tio.protocol.pet_info import decode_pet_info
from tio.protocol.shared_config import decode_shared_config_data
from tio.protocol.town_info import decode_town_info


class ContractsLocalTcpTests(unittest.TestCase):
    # Reuse the authenticated fixture's helpers without inheriting its tests.
    connect = account_fixture.MultiAccountTests.connect
    begin = account_fixture.MultiAccountTests.begin
    handoff = account_fixture.MultiAccountTests.handoff
    character_screen = account_fixture.MultiAccountTests.character_screen
    enter = account_fixture.MultiAccountTests.enter
    ping = account_fixture.MultiAccountTests.ping

    def setUp(self):
        account_fixture.MultiAccountTests.setUp(self)
        self.config = replace(self.config, contracts_enabled=True)
        self.frames = {}
        self.peers = {}

    def start(self):
        self.server = Server(self.config)

        def run():
            try:
                self.server.serve()
            except BaseException as error:
                self.errors.append(error)

        self.thread = threading.Thread(target=run, daemon=True)
        self.addCleanup(self.stop)
        self.thread.start()
        self.wait(lambda: self.server.listener is not None or self.errors, 'Listener startup')
        self.assertFalse(self.errors)
        self.service = self.server.multi.contracts
        self.fake_now = time.time()
        self.service.travel.clock = lambda: self.fake_now

    def stop(self):
        # Close clients first, including when a packet assertion fails mid-test.
        for connection in self.clients:
            try:
                connection.close()
            except OSError:
                pass
        if self.server is not None:
            self.server.stop()
            self.thread.join(10)
            self.assertFalse(self.thread.is_alive(), 'Loopback server shutdown hung')
            self.assertFalse(self.errors)

    def wait(self, predicate, label, *, timeout=6):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= deadline:
                self.fail(label + ' timed out')
            time.sleep(.01)

    def connect_player(self, login, name):
        peer = self.handoff(self.begin(login))
        self.peers[login] = peer
        history = self.frames.setdefault(login, [])
        original = peer.receive

        def receive():
            packet = original()
            history.append(packet)
            return packet

        peer.receive = receive
        self.enter(peer, name)
        self.flush(peer)
        return peer

    def flush(self, peer):
        # A second barrier drains replies queued by the preceding request loop.
        self.ping(peer)
        self.ping(peer)

    @staticmethod
    def chat(text):
        return b'\x21\0' + text.encode('utf-16-le') + b'\0\0'

    @staticmethod
    def message(packet):
        if packet[:1] != b'\x22':
            return None
        end = packet.index(0, 6)
        return packet[6:end].decode('cp1251'), packet[end+1:-2].decode('utf-16-le')

    def texts(self, login, start=0):
        return [self.message(packet) for packet in self.frames[login][start:] if packet[:1] == b'\x22']

    def command(self, login, text):
        start = len(self.frames[login])
        self.peers[login].send(self.chat(text))
        self.flush(self.peers[login])
        return self.texts(login, start)

    def native_markers(self, login):
        result = {}
        for packet in self.frames[login]:
            if packet[:2] == b'\xc8\x2d' and int.from_bytes(packet[2:4], 'little') in (23, 24, 25):
                marker = decode_town_info(packet)
                if marker.town_id in (23, 24, 25):
                    result[marker.town_id] = marker.final_bool
        return result

    def group_and_accept(self):
        self.command('alice', '!party create')
        self.command('alice', '!party invite Bob')
        invitations = self.service.parties.invitations('bob')
        self.assertEqual(len(invitations), 1)
        self.command('bob', '!party accept ' + str(invitations[0]['id']))
        room = self.service.parties.info('alice')
        self.assertEqual({member['login'] for member in room['members']}, {'alice', 'bob'})
        self.command('alice', '!contracts take camp')
        contract = self.service.contracts.active(room['id'])
        self.assertIsNotNone(contract)
        self.assertEqual(contract['state'], 'accepted')
        self.assertFalse(any(member['ready'] for member in self.service.parties.info('alice')['members']))
        return room, contract

    def travel_to_contract(self, room, contract):
        self.command('alice', '!party ready')
        self.command('bob', '!party ready')
        target = contract['target']
        self.peers['alice'].send(struct.pack('<Bii', 0x1b, target['x'], target['y']))
        self.flush(self.peers['alice'])
        self.wait(lambda: self.service.travel.route(room['id']) is not None, 'Shared route creation')
        return self.service.travel.route(room['id'])

    def test_invitation_delivered_as_system_notice_only_to_target_and_leader(self):
        self.accounts.create('carol',account_fixture.PASSWORD,character='Carol')
        account_fixture.fund_wallet(self.config.database,'carol',credits=10_000,gold=10_000)
        self.start()
        for login,name in (('alice','Alice'),('bob','Bob'),('carol','Carol')):
            self.connect_player(login,name)
        self.command('alice','!party create')
        bob_start,carol_start=len(self.frames['bob']),len(self.frames['carol'])
        leader=self.command('alice','!party invite Bob')
        self.flush(self.peers['bob']);self.flush(self.peers['carol'])
        invitation=self.service.parties.invitations('bob')[0]
        notices=[packet for packet in self.frames['bob'][bob_start:] if packet[:1]==b'\x22']
        self.assertEqual(len(notices),1)
        self.assertEqual(notices[0][5],5)
        text=self.message(notices[0])[1]
        self.assertIn('[Контракты]',text)
        self.assertIn('Alice приглашает в группу',text)
        self.assertIn(f"!party accept {invitation['id']}",text)
        self.assertIn(f"!party decline {invitation['id']}",text)
        self.assertTrue(any('отправлено Bob' in text for _,text in leader))
        self.assertFalse(self.texts('carol',carol_start))
        self.assertIsNone(self.service.parties.info('bob'))
        self.command('bob',f"!party accept {invitation['id']}")
        self.assertEqual({member['login'] for member in self.service.parties.info('alice')['members']},
                         {'alice','bob'})

    def test_private_commands_hidden_bootstrap_markers_and_shared_movement(self):
        self.accounts.create('carol', account_fixture.PASSWORD, character='Carol')
        # Provision a complete established save, including its wallet. Login
        # must not manufacture a replacement wallet for an existing character.
        account_fixture.fund_wallet(self.config.database, 'carol', credits=10_000, gold=10_000)
        self.start()
        for login, name in (('alice', 'Alice'), ('bob', 'Bob'), ('carol', 'Carol')):
            self.connect_player(login, name)
            snapshots = [decode_shared_config_data(packet) for packet in self.frames[login]
                         if packet[:2] == b'\xb9\x03']
            zones = next(data for data in snapshots if data.name_bytes == b'zones')
            xml = ET.fromstring(zlib.decompress(zones.compressed_bytes))
            self.assertEqual([int(town.get('id')) for town in xml], list(range(1, 26)))
            for town in xml[-3:]:
                values = {value.get('key'): value.get('val') for value in town}
                self.assertEqual(values['enabled'], '0')
            self.assertEqual(self.native_markers(login), {23: 0, 24: 0, 25: 0})

        bob_start, carol_start = len(self.frames['bob']), len(self.frames['carol'])
        replies = self.command('alice', '!contracts list')
        self.assertEqual(sum(name == 'Контракты' and ': ' in text for name, text in replies), 6)
        self.flush(self.peers['bob'])
        self.flush(self.peers['carol'])
        for login, start in (('bob', bob_start), ('carol', carol_start)):
            self.assertFalse(any('camp:' in text or '!contracts list' in text for _, text in self.texts(login, start)))

        room, contract = self.group_and_accept()
        for login in self.peers:
            self.flush(self.peers[login])
        self.assertEqual(self.native_markers('alice'), {23: 1, 24: 0, 25: 0})
        self.assertEqual(self.native_markers('bob'), {23: 1, 24: 0, 25: 0})
        self.assertEqual(self.native_markers('carol'), {23: 0, 24: 0, 25: 0})
        for owner in ('alice', 'bob'):
            roster = OwnedPetStore(self.config.database).list(owner)
            self.assertTrue(all(decode_pet_info(raw, human_equipment=True).fields['0x8c4ab1'] > 0 for _, raw, _ in roster))
        encounter_checks = []
        for owner in ('alice', 'bob'):
            encounters = self.server.multi.active_accounts[owner].encounters
            observer = patch.object(encounters, 'tick', wraps=encounters.tick)
            self.addCleanup(observer.stop)
            encounter_checks.append(observer.start())

        self.peers['bob'].send(struct.pack('<Bii', 0x1b, -250, -200))
        self.flush(self.peers['bob'])
        self.assertIsNone(self.service.travel.route(room['id']))
        departure_starts = {login: len(self.frames[login]) for login in self.peers}
        route = self.travel_to_contract(room, contract)
        self.flush(self.peers['bob'])
        self.flush(self.peers['carol'])
        from tio.locations import leave_town_packet
        for login in ('alice', 'bob'):
            packets = self.frames[login][departure_starts[login]:]
            leave = next(index for index, packet in enumerate(packets) if packet == leave_town_packet())
            mode = next(index for index, packet in enumerate(packets) if packet == b'\xee\x02\0')
            movement = next(index for index, packet in enumerate(packets) if packet[:1] == b'\x1d')
            self.assertLess(leave, mode)
            self.assertLess(mode, movement)
        self.assertNotIn(b'\xee\x02\0', self.frames['carol'][departure_starts['carol']:])
        self.assertEqual(route[8], contract['id'])
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM travel_party_journeys').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM map_journeys').fetchone()[0], 0)
        self.fake_now = (route[4] + route[5]) / 2
        for login in ('alice', 'bob'):
            self.flush(self.peers[login])
            packets = [packet for packet in self.frames[login] if packet[:1] == b'\x1d']
            self.assertTrue(packets)
            # Each 1D points at the next turn of the shared road path.
            turns = {tuple(map(round, point)) for point in (route[2:4],)}
            self.assertIn(struct.unpack_from('<ii', packets[-1], 17), turns)
        first = next(packet for packet in reversed(self.frames['alice']) if packet[:1] == b'\x1d')
        second = next(packet for packet in reversed(self.frames['bob']) if packet[:1] == b'\x1d')
        self.assertEqual(struct.unpack_from('<ii', first, 5), struct.unpack_from('<ii', second, 5))
        before = route
        self.peers['bob'].send(struct.pack('<Bii', 0x1b, 0, 0))
        self.flush(self.peers['bob'])
        self.assertEqual(self.service.travel.route(room['id']), before)
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM world_encounter_audit WHERE account IN (?,?)', ('alice', 'bob')).fetchone()[0], 0)
        for login in ('alice', 'bob'):
            self.assertFalse(any(event.get('event') == 'world_encounter_started' for event in self.server.multi.active_accounts[login].events))
        self.assertTrue(all(check.call_count == 0 for check in encounter_checks),
                        'Grouped players were evaluated for independent random encounters')

    def test_shared_contract_start_sends_both_clients_same_ground_and_scene_complete(self):
        self.start()
        self.connect_player('alice', 'Alice')
        self.connect_player('bob', 'Bob')
        room, contract = self.group_and_accept()
        route = self.travel_to_contract(room, contract)
        self.fake_now = route[5] + 1
        self.wait(lambda: self.service.contracts.get(contract['id'])['state'] == 'arrived', 'Whole party contract arrival')
        for login in ('alice', 'bob'):
            self.command(login, '!party ready')
        starts = {login: len(self.frames[login]) for login in ('alice', 'bob')}
        self.peers['alice'].send(self.chat('!contracts start'))
        for login in ('alice', 'bob'):
            self.peers[login].until(b'\x41', max_packets=180)
        ground = {}
        for login in ('alice', 'bob'):
            packets = self.frames[login][starts[login]:]
            ground[login] = next(packet for packet in packets if packet[:1] == b'\x35')
            self.assertIn(b'\x41', packets)
            self.assertTrue(any(packet[:1] == b'\x6c' for packet in packets))
        self.assertEqual(ground['alice'], ground['bob'])
        self.assertEqual(self.service.contracts.get(contract['id'])['state'], 'active')
        hub = self.server.multi.team_arena
        alice = self.server.multi.active_accounts['alice']
        bob = self.server.multi.active_accounts['bob']
        with hub.lock:
            a_owner, b_owner = hub.identities[alice], hub.identities[bob]
            battle = hub.battles[a_owner]
            self.assertIs(battle, hub.battles[b_owner])
            self.assertEqual(battle['kind'], 'contract')
            self.assertEqual(battle['field'].teams[a_owner], battle['field'].teams[b_owner])

    def test_map_tooltip_poll_works_at_target_without_start_or_city_service_access(self):
        self.accounts.create('carol', account_fixture.PASSWORD, character='Carol')
        account_fixture.fund_wallet(self.config.database, 'carol', credits=10_000, gold=10_000)
        self.start()
        for login, name in (('alice', 'Alice'), ('bob', 'Bob'), ('carol', 'Carol')):
            self.connect_player(login, name)
        room, contract = self.group_and_accept()
        route = self.travel_to_contract(room, contract)
        self.fake_now = route[5] + 1
        self.wait(lambda: self.service.contracts.get(contract['id'])['state'] == 'arrived', 'Contract arrival')
        self.peers['carol'].send(struct.pack('<Bii', 0x1b, 0, 0))
        self.flush(self.peers['carol'])
        self.assertIsNone(self.server.multi.active_accounts['carol'].locations.current('carol'))
        for login in ('alice', 'bob', 'carol'):
            start = len(self.frames[login])
            for packet in (b'\x79\x17', b'\x79\x18', b'\x79\x02', b'\x79\x01',
                           b'\x79\xff', b'\x79\x1a', b'\x79', b'\x79\x17\0'):
                self.peers[login].send(packet)
            self.flush(self.peers[login])
            replies = self.frames[login][start:]
            infos = {info.town_id: info for packet in replies if packet[:2] == b'\xc8\x2d'
                     for info in (decode_town_info(packet),)}
            self.assertEqual(infos[23].final_bool, int(login != 'carol'))
            self.assertEqual(infos[24].final_bool, 0)
            self.assertEqual(infos[2].final_bool, 1)
            self.assertEqual(infos[1].final_bool, 0)
            self.assertNotIn(26, infos)
            self.assertNotIn(255, infos)
            self.assertFalse(any(packet[:5] == b'\xf0' + (394).to_bytes(4, 'little') for packet in replies))
            self.assertFalse(any(packet[:1] in (b'\x35', b'\x41') for packet in replies))
        self.assertEqual(self.service.contracts.get(contract['id'])['state'], 'arrived')
        self.assertEqual(self.service.parties.info('alice')['state'], 'at_target')
        self.assertFalse(self.server.multi.team_arena.battles)
        # Only79 was admitted; an actual shop mutation still hits the city gate.
        from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase
        start = len(self.frames['alice'])
        self.peers['alice'].send(encode_shop_purchase(ShopPurchase(1, 0, 1, 1)))
        self.flush(self.peers['alice'])
        replies = self.frames['alice'][start:]
        self.assertTrue(any('сначала дойдите до входа'.encode('utf-16-le') in packet for packet in replies))
        self.assertEqual(self.service.contracts.get(contract['id'])['state'], 'arrived')

    def test_reconnect_keeps_party_save_owner_and_rejects_character_switch(self):
        characters = CharacterStore(self.config.database)
        characters.create('bob', CharacterCreateRequest(b'BobTwo', 0, (1, 0, 0, 0)))
        # The alternative is an established slot, so the selection fence is
        # exercised directly rather than an unfinished appearance editor.
        prepare(self.config.database, '@character:bob:2')
        with closing(sqlite3.connect(self.config.database)) as db, db:
            db.execute('UPDATE character_onboarding SET completed=1 WHERE account=?', ('@character:bob:2',))
        self.start()
        self.connect_player('alice', 'Alice')
        peer = self.handoff(self.begin('bob'))
        records = self.character_screen(peer)
        self.assertEqual([record.name_bytes for record in records], [b'Bob', b'BobTwo'])
        peer.send(bytes.fromhex('1701000000'))
        self.assertTrue(peer.receive().startswith(b'\x18'))
        peer.send(b'\x19')
        peer.until(b'\x66')
        self.peers['bob'] = peer
        self.frames['bob'] = []
        self.flush(peer)
        room, contract = self.group_and_accept()
        exchange = self.server.multi.active_accounts['bob']
        peer.sock.close()
        exchange.thread.join(5)
        self.assertFalse(exchange.thread.is_alive())
        self.wait(lambda: 'bob' not in self.server.multi.active_accounts, 'Disconnected login release')
        offline = next(member for member in self.service.parties.info('alice')['members'] if member['owner'] == 'bob')
        self.assertFalse(offline['online'])
        restored = self.handoff(self.begin('bob'))
        self.character_screen(restored)
        restored.send(bytes.fromhex('1702000000'))
        packet = restored.receive()
        self.assertEqual(packet, b'\x18\x01', 'Grouped account switched to another save owner')
        restored.until(b'\x10')
        self.assertEqual(self.service.selected_owner('bob'), 'bob')
        self.assertEqual(self.service.contracts.active(room['id'])['id'], contract['id'])
        self.assertIsNone(self.service.contracts.target_for('@character:bob:2'))
        restored.send(bytes.fromhex('1701000000'))
        self.assertEqual(restored.receive()[:2], b'\x18\0')
        restored.send(b'\x19')
        restored.until(b'\x66')
        self.flush(restored)
        self.wait(lambda: next(member for member in self.service.parties.info('alice')['members']
                               if member['owner'] == 'bob')['online'], 'Reconnected exact party owner')


if __name__ == '__main__':
    unittest.main()
