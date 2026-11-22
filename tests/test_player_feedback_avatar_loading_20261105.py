"""Native scene loading must finish before portrait assignments are applied."""
from contextlib import closing
import socket
import sqlite3
import struct
import unittest


class AvatarLoadingTests(unittest.TestCase):
    def test_private_load_ack_and_reload_restore_saved_battle_portrait(self):
        from test_shooting_range import RangeTests
        from tio.avatars import ensure
        from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame
        from tools.loopback_exchange import LoopbackExchange

        f = RangeTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        with closing(sqlite3.connect(f.path)) as db, db:
            ensure(db)
            db.execute('INSERT INTO pet_avatars VALUES (?,?,?)', ('alice', f.identity, 10007))
        f.start()
        exchange = LoopbackExchange(f.path.with_suffix('.json'), database=f.path,
                                    open_town_probe=True, observation_seconds=0)
        exchange.account = 'alice'
        exchange.probe_character_id = 42
        exchange.probe_character_name = b'Alice'
        exchange.arena = f.arena
        exchange.locations = None
        exchange.encounters = None
        exchange.training_matches = {f.room.room_id: ()}
        exchange.quiet = True
        self.addCleanup(exchange.stop)
        turn = dict(f.arena._turns)
        for reconnect in (False, True):
            with self.subTest(reconnect=reconnect):
                server, client = socket.socketpair()
                with server, client:
                    client.settimeout(3)
                    cipher = InitialCipher('C2S')
                    client.sendall(encode_initial_frame(b'\x36', cipher)
                                   + encode_initial_frame(b'\x70', cipher))
                    client.shutdown(socket.SHUT_WR)
                    reader = InitialFrameReader(InitialCipher('C2S'))
                    outbound = InitialCipher('S2C')
                    if reconnect:
                        from server.team_arena import TeamArena
                        hub = TeamArena(clock=lambda: 0)
                        exchange.private_resume_loading = 5
                        hub.private_resume_pump(exchange, server, reader, outbound,
                                                encode_initial_frame)
                    else:
                        exchange.observe_game(server, reader, outbound)
                    packets = InitialFrameReader(InitialCipher('S2C')).feed(client.recv(65535))
                assignments = [p for p in packets if p[:2] == b'\xfc\x01']
                self.assertEqual(len(assignments), 1)
                selected = dict(struct.iter_unpack('<II', assignments[0][4:]))
                self.assertEqual(selected[f.identity], 10007)
                self.assertTrue(all(not avatar for actor, avatar in selected.items()
                                    if actor != f.identity))
                self.assertEqual(f.arena._turns, turn)

    def test_shared_load_ack_preserves_global_ids_and_hides_other_owners(self):
        from test_shared_team_arena import SharedTeamTests
        from tio.avatars import encode_assignments
        from tio.visibility import visible_actors

        f = SharedTeamTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        owners, battle = f.open_battle()
        field = battle['field']
        field.avatar_ids = {field.actor_ids(owner)[0]: avatar
                            for owner, avatar in zip(owners, (10007, 10003))}
        for index, owner in enumerate(owners):
            f.hub.queues[owner].clear()
            packets = f.send(index, b'\x36')
            expected = encode_assignments((i, field.avatar_ids.get(i, 0))
                                           for i in sorted(visible_actors(field, owner)))
            self.assertIn(expected, packets)
