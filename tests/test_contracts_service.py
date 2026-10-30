"""Opt-in routing and private command checks on disposable account data."""
from dataclasses import replace
from pathlib import Path
import json
import tempfile
import threading
import unittest

from server.accounts import Accounts
from server.config import ServerConfig
from server.contracts_service import ContractsService
from server.team_arena import TeamArena
from tio.arena_service import ArenaService
from tio.locations import LocationStore
from tio.owned_pets import OwnedPetStore
from tio.survival_service import SurvivalService


class Session:
    def stop(self):
        raise AssertionError('Unexpected queue overflow')


class ContractsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'game.db'
        accounts = Accounts(self.path)
        self.hub = TeamArena(); self.service = ContractsService(self.hub, self.path)
        self.sessions = []
        for login in ('alice', 'bob', 'carol'):
            accounts.create(login, 'disposable-test-password', character=login.title())
            fixture = json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
            from tio.protocol.item_list import encode_item_list
            OwnedPetStore(self.path).ensure(login, bytes.fromhex(fixture['packet_hex']), encode_item_list(1, ()), human=True)
            session = Session(); session.account = login; session.database = self.path
            session.authenticated_account = login; session.probe_character_id = 1
            session.probe_character_name = login.title().encode()
            session.arena = ArenaService(); session.survival = SurvivalService()
            session.stopping = threading.Event(); session.locations = self.service.locations(LocationStore(self.path))
            self.hub.identity(session); self.sessions.append(session)

    def send(self, index, text):
        session = self.sessions[index]
        self.assertTrue(self.service.command(session, text))
        queue = self.hub.queues[self.hub.identities[session]]
        replies = tuple(queue); queue.clear()
        return replies

    def test_commands_private_invitation_consent_and_frozen_edits(self):
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.assertIsNone(self.service.member(self.sessions[1]))
        invitation = self.service.parties.invitations('bob')[0]['id']
        self.send(1, f'!party accept {invitation}')
        self.send(0, '!contracts take camp')
        party = self.service.parties.info('alice')
        self.assertFalse(any(member['ready'] for member in party['members']))
        self.assertTrue(self.service.contracts.active(party['id']))
        self.assertFalse(self.hub.queues[self.hub.identities[self.sessions[2]]])
        before = party['members']
        replies = self.send(0, '!party kick Bob')
        self.assertEqual(self.service.parties.info('alice')['members'], before)
        self.assertIn('отмените контракт'.encode('utf-16-le'), replies[-1])

    def test_invitation_uses_native_system_channel_and_acknowledges_named_recipient(self):
        self.send(0, '!party create')
        leader_reply=self.send(0, '!party invite Bob')
        invitation=self.service.parties.invitations('bob')[0]
        target_queue=self.hub.queues[self.hub.identities[self.sessions[1]]]
        self.assertEqual(len(target_queue),1)
        packet=target_queue[0]
        # Native channel0 needs the Location tab. Channel5 uses an enabled tab,
        # including Global when Location has been closed.
        self.assertEqual(packet[:6],b'\x22\0\0\0\0\5')
        self.assertIn('[Контракты]'.encode('utf-16-le'),packet)
        self.assertIn(f"!party accept {invitation['id']}".encode('utf-16-le'),packet)
        self.assertIn(f"!party decline {invitation['id']}".encode('utf-16-le'),packet)
        self.assertIn('Bob'.encode('utf-16-le'),leader_reply[-1])
        self.assertIn('отправлено'.encode('utf-16-le'),leader_reply[-1])
        self.assertIsNone(self.service.member(self.sessions[1]))
        self.assertFalse(self.hub.queues[self.hub.identities[self.sessions[2]]])

    def test_group_queries_and_errors_remain_visible_without_location_tab(self):
        for command in ('!party status','!party invite Bob','!contracts list'):
            replies=self.send(0,command)
            self.assertTrue(replies)
            self.assertTrue(all(packet[:6]==b'\x22\0\0\0\0\5' for packet in replies))
            self.assertTrue(all('[Контракты]'.encode('utf-16-le') in packet for packet in replies))
        self.assertFalse(self.service.parties.invitations('bob'))
        for session in self.sessions[1:]:
            self.assertFalse(self.hub.queues[self.hub.identities[session]])

    def test_hidden_native_zones_and_private_marker_updates(self):
        from xml.etree import ElementTree as ET
        from tio.protocol.town_info import decode_town_info
        zones = ET.fromstring(self.service.zones_xml())
        self.assertEqual([int(t.get('id')) for t in zones], list(range(1,26)))
        for zone in list(zones)[22:]:
            values = {value.get('key'): value.get('val') for value in zone}
            self.assertEqual(values['enabled'], '0')
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!contracts take camp')
        for session in self.sessions:
            self.service.sync(session)
            updates = [decode_town_info(packet) for packet in self.hub.queues[self.hub.identities[session]]
                       if packet[:2] == b'\xc8\x2d']
            self.assertEqual({info.town_id for info in updates}, {23,24,25})
            self.assertEqual([info.town_id for info in updates if info.final_bool],
                             [23] if session.account in ('alice','bob') else [])

    def test_existing_gameplay_allowed_when_ungrouped(self):
        self.assertFalse(self.service.guard(self.sessions[0], b'\xba\x03\x01\x01'))
        self.send(0, '!party create')
        self.assertTrue(self.service.guard(self.sessions[0], b'\xba\x03\x01\x01'))
        self.assertTrue(self.service.guard(self.sessions[0], b'\x29\x01\x00\x00\x00'))
        self.assertFalse(self.service.guard(self.sessions[0], b'\x70'))
        self.assertFalse(self.service.command(self.sessions[0], 'Обычный чат'))

    def test_arrival_sync_sends_start_hint_once_to_each_actual_member(self):
        import struct
        now = [1000.0]
        self.service.clock = self.service.parties.clock = self.service.contracts.clock = self.service.travel.clock = lambda: now[0]
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!contracts take camp')
        self.send(0, '!party ready'); self.send(1, '!party ready')
        for session in self.sessions:
            self.service.sync(session)
            self.hub.queues[self.hub.identities[session]].clear()
        party = self.service.parties.info('alice')
        target = self.service.contracts.active(party['id'])['target']
        self.service.travel_map(self.sessions[0], struct.pack('<Bii', 0x1b, target['x'], target['y']))
        now[0] = self.service.travel.route(party['id'])[5] + 1
        self.service.travel.arrive('alice')
        arrived_party = self.service.parties.info('alice')
        contract = self.service.contracts.active(party['id'])
        self.assertEqual(contract['state'], 'arrived')
        hint = 'Цель контракта достигнута. Лидер: !contracts start — начать зачистку.'.encode('utf-16-le')
        for session in self.sessions:
            self.service.sync(session)
            queue = self.hub.queues[self.hub.identities[session]]
            notices = [packet for packet in queue if hint in packet]
            self.assertEqual(len(notices), int(session.account in ('alice', 'bob')))
            if notices:
                self.assertEqual(notices[0][:6], b'\x22\0\0\0\0\5')
                self.assertIn('Группа:'.encode('utf-16-le'), queue[0])
            queue.clear()
            self.service.sync(session)
            self.assertFalse(queue)
        self.assertEqual(self.service.parties.info('alice'), arrived_party)
        self.assertEqual(self.service.contracts.active(party['id']), contract)
        self.assertFalse(self.hub.battles)

    def test_map_stop_without_own_contract_target_has_no_start_hint(self):
        import struct
        for has_contract in (False, True):
            with self.subTest(has_contract=has_contract):
                now = [1000.0]
                self.service.clock = self.service.parties.clock = self.service.contracts.clock = self.service.travel.clock = lambda: now[0]
                self.send(0, '!party create'); self.send(0, '!party invite Bob')
                self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
                if has_contract:
                    self.send(0, '!contracts take camp')
                self.send(0, '!party ready'); self.send(1, '!party ready')
                party = self.service.parties.info('alice')
                self.service.travel_map(self.sessions[0], struct.pack('<Bii', 0x1b, 0, 0))
                now[0] = self.service.travel.route(party['id'])[5] + 1
                self.service.travel.arrive('alice')
                self.assertEqual(self.service.parties.info('alice')['state'], 'at_target')
                for session in self.sessions[:2]:
                    queue = self.hub.queues[self.hub.identities[session]]
                    queue.clear()
                    self.service.sync(session)
                    self.assertFalse(any('!contracts start'.encode('utf-16-le') in packet for packet in queue))
                self.assertFalse(self.hub.battles)
                # Return and disband through the normal authoritative route.
                from tio.locations import center
                self.service.travel_map(self.sessions[0], struct.pack('<Bii', 0x1b, *center(3)))
                now[0] = self.service.travel.route(party['id'])[5] + 1
                self.service.travel.arrive('alice')
                if has_contract:
                    self.send(0, '!contracts cancel')
                self.send(0, '!party disband')

    def test_map_tooltip_poll_resolves_only_own_private_contract_slot(self):
        from tio.protocol.town_info import decode_town_info
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!contracts take camp')
        party = self.service.parties.info('alice')
        contract = self.service.contracts.active(party['id'])
        for session in self.sessions:
            for town in (23, 24, 25):
                replies = self.service.map_query(session, bytes((0x79, town)))
                self.assertEqual(len(replies), 1)
                info = decode_town_info(replies[0])
                enabled = session.account in ('alice', 'bob') and town == 23
                self.assertEqual((info.town_id, info.final_bool), (town, int(enabled)))
                self.assertEqual(info.unknown_bools, (0, 0, 0))
                if enabled:
                    self.assertEqual(info.unknown_bytes[:2], tuple(contract['target']['levels']))
        self.assertEqual(self.service.parties.info('alice'), party)
        self.assertEqual(self.service.contracts.active(party['id']), contract)
        self.assertFalse(self.hub.battles)

    def test_map_tooltip_public_reads_preserve_scene_visibility(self):
        from xml.etree import ElementTree as ET
        from tio.protocol.town_info import decode_town_info
        zones = ET.fromstring(self.service.zones_xml())
        for town in (1, 2, 3, 4, 7, 10, 13, 17):
            zone = zones[town-1]
            values = {value.get('key'): value.get('val') for value in zone}
            replies = self.service.map_query(self.sessions[0], bytes((0x79, town)))
            self.assertEqual(len(replies), 1)
            packet = replies[0]
            self.assertEqual(packet[:4], b'\xc8\x2d' + town.to_bytes(2, 'little'))
            self.assertEqual(packet[-1], int(values['enabled'] == '1'))
            if town in (7, 13):
                self.assertGreater(len(packet), 39)  # Native territory schedule survives the read.
            else:
                self.assertEqual(decode_town_info(packet).town_id, town)
        self.assertIsNone(self.service.member(self.sessions[0]))

    def test_map_tooltip_unknown_malformed_and_cancelled_slots_stay_private(self):
        from tio.protocol.town_info import decode_town_info
        for packet in (b'\x79', b'\x79\x17\0', b'\x79\0', b'\x79\x1a', b'\x79\xff'):
            self.assertEqual(self.service.map_query(self.sessions[2], packet), ())
        self.assertIsNone(self.service.map_query(self.sessions[0], b'\x75'))
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!contracts take camp'); self.send(0, '!contracts cancel')
        self.assertEqual(decode_town_info(self.service.map_query(self.sessions[0], b'\x79\x17')[0]).final_bool, 0)

    def test_city_button_queries_do_not_create_group_and_replies_are_private(self):
        contracts = self.send(0, '!contracts list')
        group = self.send(0, '!party status')
        self.assertEqual(len([packet for packet in contracts if ': '.encode('utf-16-le') in packet]), 3)
        self.assertIn('!party create'.encode('utf-16-le'), contracts[-1])
        self.assertIn('!party create'.encode('utf-16-le'), group[0])
        self.assertIsNone(self.service.member(self.sessions[0]))
        for session in self.sessions[1:]:
            self.assertFalse(self.hub.queues[self.hub.identities[session]])

    def test_city_group_query_reports_actions_without_mutating_roster_or_readiness(self):
        self.send(0, '!party create')
        before = self.service.parties.info('alice')
        replies = self.send(0, '!party status')
        self.assertEqual(before, self.service.parties.info('alice'))
        self.assertIn('!party invite'.encode('utf-16-le'), replies[-1])

    def test_departure_checks_every_live_member_battle(self):
        import struct
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!party ready'); self.send(1, '!party ready')
        self.sessions[1].arena._fields[1] = object()
        with self.assertRaises(ValueError):
            self.service.travel_map(self.sessions[0], b'\x1b'+struct.pack('<ii', -280, -235))
        self.assertEqual(self.service.parties.info('alice')['state'], 'city')

    def test_pending_invitation_cannot_change_accepted_contract_roster(self):
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!party invite Carol')
        pending = self.service.parties.invitations('carol')[0]['id']
        self.send(0, '!contracts take camp')
        self.send(2, f'!party accept {pending}')
        party = self.service.parties.info('alice')
        self.assertEqual(len(party['members']), 2)
        self.assertIsNone(self.service.parties.info('carol'))
        self.assertFalse(self.service.parties.invitations('carol'))
        with self.assertRaises(ValueError):
            self.service.parties.select('alice', (1,))

    def test_disconnected_leader_grace_allows_group_to_return(self):
        import struct
        from tio.locations import center
        from tio.db_transaction import transaction
        now = [1000.0]
        self.service.clock = self.service.parties.clock = self.service.contracts.clock = self.service.travel.clock = lambda: now[0]
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!contracts take camp')
        self.send(0, '!party ready'); self.send(1, '!party ready')
        self.service.travel_map(self.sessions[0], b'\x1b'+struct.pack('<ii', -280, -235))
        self.service.disconnect(self.sessions[0])
        party = self.service.parties.info('bob')
        self.assertEqual(self.service.parties.recover_leader(party['id'])['leader'], 'alice')
        now[0] += 61
        recovered = self.service.parties.recover_leader(party['id'])
        self.assertEqual(recovered['leader'], 'bob')
        self.assertFalse(any(member['ready'] for member in recovered['members']))
        self.service.travel_map(self.sessions[1], b'\x1b'+struct.pack('<ii', *center(3)))
        now[0] += 1000; self.service.travel.arrive('bob')
        self.assertEqual(self.service.parties.info('bob')['state'], 'city')

    def test_group_cannot_be_stranded_at_non_city_entry(self):
        import struct
        from tio.locations import center
        self.send(0, '!party create'); self.send(0, '!party invite Bob')
        self.send(1, f"!party accept {self.service.parties.invitations('bob')[0]['id']}")
        self.send(0, '!party ready'); self.send(1, '!party ready')
        for town in (11, 13, 17):
            with self.assertRaises(ValueError):
                self.service.travel_map(self.sessions[0], b'\x1b'+struct.pack('<ii', *center(town)))
        party = self.service.parties.info('alice')
        self.assertEqual(party['state'], 'city')
        self.assertTrue(all(member['ready'] for member in party['members']))

    def test_config_feature_off_by_default_and_requires_multiplayer(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse(ServerConfig.load(root/'config/server.toml').contracts_enabled)
        config = ServerConfig.load(root/'config/contracts-local.toml')
        self.assertTrue(config.contracts_enabled)
        self.assertEqual(config.bind_address, '127.0.0.1')
        self.assertEqual(config.data_directory, root/'data/contracts-local')
        source = (root/'config/contracts-local.toml').read_text().replace('multi_account = true', 'multi_account = false')
        bad = Path(self.temp.name)/'bad.toml'; bad.write_text(source)
        with self.assertRaises(ValueError): ServerConfig.load(bad)
