"""Native practice escape must tear down the scene before reopening Range."""
from dataclasses import replace
import socket
import threading
import unittest


class RangeExitTransportTests(unittest.TestCase):
    def test_escape_and_repeat_reopen_range_without_charging_or_reusing_map(self):
        from test_shooting_range import RangeTests
        from tio.locations import SHOOTING_RANGE
        from tio.owned_pets import OwnedPetStore
        from tio.avatars import ensure
        from tio.db_transaction import transaction
        from tio.protocol.pet_info import decode_pet_info
        from tio.protocol.system_message import (
            encode_current_town, encode_finish_battle_view,
            encode_open_town_view)
        from tio.protocol.transport import (
            InitialCipher, InitialFrameReader, encode_initial_frame)
        from tools.loopback_exchange import LoopbackExchange

        fixture = RangeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with transaction(fixture.path) as db:
            ensure(db)
            db.execute('INSERT INTO pet_avatars VALUES (?,?,?)', ('alice', 1, 10007))
        fixture.start()
        actor = fixture.field.actor(fixture.identity)
        fixture.field._actors[fixture.identity] = replace(actor, x=25, y=36)
        self.assertTrue(fixture.field.can_exit(42))
        saved = OwnedPetStore(fixture.path).list('alice')
        money = fixture.service.admission.assets('alice')
        exchange = LoopbackExchange(
            fixture.path.with_suffix('.json'), database=fixture.path,
            open_town_probe=True, observation_seconds=0)
        exchange.account = 'alice'
        exchange.probe_character_id = 42
        exchange.probe_character_name = b'Alice'
        exchange.arena = fixture.arena
        exchange.locations = None
        exchange.encounters = None
        exchange.quiet = True
        server, client = socket.socketpair()
        client.settimeout(3)
        errors = []

        def observe():
            try:
                exchange.observe_game(
                    server, InitialFrameReader(InitialCipher('C2S')),
                    InitialCipher('S2C'))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=observe)
        thread.start()
        try:
            cipher = InitialCipher('C2S')
            reader = InitialFrameReader(InitialCipher('S2C'))
            for _ in range(2):
                client.sendall(encode_initial_frame(b'\x2a\x01', cipher)
                               + encode_initial_frame(b'\x70', cipher))
                packets = []
                while b'\x9e' not in packets:
                    chunk = client.recv(65535)
                    self.assertTrue(chunk, errors)
                    packets.extend(reader.feed(chunk))
                finish = encode_finish_battle_view()
                self.assertIn(finish, packets)
                index = packets.index(finish)
                self.assertEqual(packets[index:index+3], [
                    finish, encode_current_town(SHOOTING_RANGE),
                    encode_open_town_view()])
            self.assertTrue(any(p[:1] == b'\x66' for p in packets))
            for packet in packets:
                if packet[:1] == b'\x66' and int.from_bytes(packet[1:5], 'little') == 1:
                    self.assertEqual(decode_pet_info(
                        packet, human_equipment=True).fields['0x8c4ba9'], 10007)
            self.assertEqual(fixture.arena.rooms.snapshot(), ())
            self.assertEqual(OwnedPetStore(fixture.path).list('alice'), saved)
            self.assertEqual(fixture.service.admission.assets('alice'), money)
        finally:
            client.close()
            thread.join(3)
            exchange.stop()
            server.close()
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)
