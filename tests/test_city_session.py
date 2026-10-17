import socket
import tempfile
import threading
import unittest
from pathlib import Path

from tools.loopback_exchange import LoopbackExchange
from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame


class CitySessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.exchange = LoopbackExchange(Path(self.temp.name) / 'events.json',
                                         open_town_probe=True, observation_seconds=0)
        self.server, self.client = socket.socketpair()
        self.exchange.connections.append(self.server)
        self.exchange.thread = threading.Thread(target=self.exchange.observe_game, args=(
            self.server, InitialFrameReader(InitialCipher('C2S')), InitialCipher('S2C')))

    def tearDown(self):
        self.exchange.stop()
        self.exchange.finish()
        self.server.close()
        self.client.close()
        self.temp.cleanup()

    def test_unlimited_survives_idle_and_replies_to_ping_then_eof(self):
        self.exchange.start()
        self.exchange.thread.join(0.7)
        self.assertTrue(self.exchange.thread.is_alive())
        self.client.sendall(encode_initial_frame(b'\x70', InitialCipher('C2S')))
        self.client.settimeout(2)
        reader = InitialFrameReader(InitialCipher('S2C'))
        packets = []
        while not packets:
            packets += reader.feed(self.client.recv(1024))
        self.assertEqual(packets, [b'\x9e'])
        self.client.close()
        self.exchange.thread.join(2)
        self.assertFalse(self.exchange.thread.is_alive())
        self.assertEqual(self.exchange.events[-1]['event'], 'client_disconnected')

    def test_explicit_stop_ends_unlimited_session(self):
        self.exchange.start()
        self.exchange.stop()
        self.exchange.thread.join(2)
        self.assertFalse(self.exchange.thread.is_alive())

    def test_finite_session_records_timeout(self):
        self.exchange.observation_seconds = 1
        self.exchange.start()
        self.exchange.thread.join(2)
        self.assertFalse(self.exchange.thread.is_alive())
        self.assertEqual(self.exchange.events[-1], {
            'event': 'auth2_observation_window_complete', 'seconds': 1})

    def test_duration_validation(self):
        for value in (-1, 3601, True, 1.5):
            with self.assertRaises(ValueError):
                LoopbackExchange(Path(self.temp.name) / 'invalid.json', observation_seconds=value)
