"""Native refresh acknowledgements and live map population regressions."""
from collections import deque
from types import SimpleNamespace
import unittest

from server.presence import Presence
from tio.locations import town_packets
from tio.protocol.presence import Player


class PopulationTests(unittest.TestCase):
    def setUp(self):
        self.hub = Presence()
        class Session:
            pass
        self.sessions = [Session() for _ in range(3)]
        for i, session in enumerate(self.sessions):
            session.account = ('alice', 'bob', 'carol')[i]
            session.probe_character_id = 1
            self.hub.players[session] = (
                (13, 13, None)[i], Player(100+i, session.account.encode(), status=1))
            self.hub.queues[session] = deque()
            self.hub.messages[session] = deque()

    def test_online_mine_population_includes_battles_and_preserves_public_fields(self):
        packet = town_packets(13, clock=lambda: 100)[0] + b'public-extension'
        reply = self.hub.project_town(packet)
        self.assertEqual(int.from_bytes(reply[4:6], 'little'), 2)
        self.assertEqual(reply[:4] + reply[6:], packet[:4] + packet[6:])
        self.hub.refresh()
        self.assertIn(reply, self.hub.queues[self.sessions[2]])

    def test_disconnect_and_travel_update_every_viewer_without_stale_counts(self):
        packet = town_packets(13, clock=lambda: 100)[0]
        self.hub.project_town(packet)
        a, b, viewer = self.sessions
        self.hub.disconnect(b)
        self.assertEqual(self.hub.queues[viewer][-1][4:6], b'\1\0')
        self.hub.players[a] = (None, self.hub.players[a][1])
        self.hub.refresh()
        self.assertEqual(self.hub.queues[viewer][-1][4:6], b'\0\0')
        for _ in range(100):
            self.hub.refresh()
        self.assertEqual(len(self.hub.queues[viewer]), 5)

    def test_world_projection_keeps_population_after_training_schedule(self):
        from server.world_runtime import project_town
        packet = town_packets(19, clock=lambda: 100)[0]
        s = self.sessions[0]
        self.hub.players[s] = (19, self.hub.players[s][1])
        schedule = packet + b'schedule'
        class Arena:
            from threading import RLock
            lock = RLock()
            training_path = 'unused'
            def training_town_packet(self, town):
                return schedule
        s.router = SimpleNamespace(presence=self.hub, team_arena=Arena())
        s.locations = SimpleNamespace(current=lambda account: 19)
        reply = project_town(s, packet)
        self.assertEqual(reply[4:6], b'\1\0')
        self.assertTrue(reply.endswith(b'schedule'))

    def test_private_contract_markers_are_never_cached_or_broadcast(self):
        from dataclasses import replace
        from tio.protocol.town_info import diagnostic_town_info, encode_town_info
        packet = encode_town_info(replace(diagnostic_town_info(), town_id=23, final_bool=1))
        self.assertEqual(self.hub.project_town(packet), packet)
        self.assertNotIn(23, self.hub.towns)
        self.hub.refresh()
        self.assertTrue(all(packet not in queue for queue in self.hub.queues.values()))

    def test_native_tooltip_poll_keeps_the_live_mine_count(self):
        from test_contracts_service import ContractsServiceTests
        f = ContractsServiceTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        session = f.sessions[0]
        session.router = SimpleNamespace(presence=self.hub, team_arena=f.hub)
        (reply,) = f.service.map_query(session, b'\x79\x0d')
        self.assertEqual(reply[4:6], b'\2\0')
        self.assertGreater(len(reply), 39)

    def test_queued_public_town_updates_preserve_live_population_at_delivery(self):
        from test_team_heartbeat import TeamHeartbeatTests
        f = TeamHeartbeatTests()
        f.setUp()
        f.session.router = SimpleNamespace(presence=self.hub)
        f.hub.put(f.owner, town_packets(13, clock=lambda: 100)[0])
        (reply,) = f.drain()
        self.assertEqual(reply[4:6], b'\2\0')

    def test_private_tooltips_enable_only_the_accepted_party_target(self):
        from test_contracts_service import ContractsServiceTests
        f = ContractsServiceTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.send(0, '!party create')
        f.send(0, '!party invite Bob')
        invitation = f.service.parties.invitations('bob')[0]['id']
        f.send(1, f'!party accept {invitation}')
        f.send(0, '!contracts take camp')
        target = f.service.contracts.target_for('alice')['zone_id']
        slots = {t['zone_id'] for t in f.service.contracts.catalog()}
        for index, session in enumerate(f.sessions):
            session.router = SimpleNamespace(presence=self.hub, team_arena=f.hub)
            for town in slots:
                (packet,) = f.service.map_query(session, bytes((0x79, town)))
                self.assertEqual(packet[-1], int(index < 2 and town == target))
        self.assertTrue(slots.isdisjoint(self.hub.towns))


class MatchmakingRefreshTests(unittest.TestCase):
    def test_native_city_ack_after_global_refresh_keeps_search_and_equipment_guard(self):
        from test_shared_team_arena import SharedTeamTests
        f = SharedTeamTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.send(0, b'\xba\x03\0\1')
        session = f.sessions[0]
        from tio.locations import LocationStore
        session.locations = LocationStore(f.path)
        owner = f.hub.identities[session]
        before = dict(f.hub.survival_queue.tickets)
        town = session.locations.current(session.account)
        self.assertEqual(f.send(0, bytes((0x50, town))), ())
        self.assertEqual(f.hub.survival_queue.tickets, before)
        self.assertIn(owner, f.hub.survival_waiting)
        self.assertTrue(f.send(0, b'\xc8\x03\0'))
        self.assertEqual(f.hub.survival_queue.tickets, before)
