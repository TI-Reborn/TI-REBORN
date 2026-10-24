"""Real socket backpressure must not inherit the battle's short read poll."""
from collections import deque
from contextlib import closing
import socket
import threading
import unittest
from unittest.mock import patch

from server.team_arena import TeamArena
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.protocol.transport import InitialCipher, InitialFrameReader


class Session:
    database = None
    account = 'delivery-fixture'


class BattleDeliveryTests(unittest.TestCase):
    @staticmethod
    def burst() -> tuple[bytes, ...]:
        items = tuple(ItemRecord(n + 1, 52, bytes(2), 1, 0, 0,
                                 (0, 0, 0), bytes(4), None, bytes(3))
                      for n in range(32))
        return tuple(encode_item_list(n + 1, items) for n in range(600))

    def test_turn_burst_survives_receiver_pause_and_keeps_frame_order(self):
        hub = TeamArena(clock=lambda: 0)
        session = Session()
        owner = hub.identity(session)
        # Inventory-sized frames force cross-platform backpressure. This is
        # a delivery stress fixture, not a reproduction of player item data.
        packets = self.burst()
        hub.queues[owner] = deque(packets)
        received = []
        errors = []
        sender, receiver = socket.socketpair()
        with closing(sender), closing(receiver):
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            sender.settimeout(.1)
            receiver.settimeout(3)
            reader = InitialFrameReader(InitialCipher('S2C'))
            release = threading.Event()

            def read() -> None:
                try:
                    release.wait(.3)
                    while len(received) < len(packets):
                        data = receiver.recv(65535)
                        if not data:
                            raise EOFError('Delivery ended before the turn completed')
                        received.extend(reader.feed(data))
                    reader.finish()
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=read)
            worker.start()
            try:
                hub.drain(session, sender, InitialCipher('S2C'))
            finally:
                release.set()
                sender.shutdown(socket.SHUT_WR)
                worker.join(4)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(tuple(received), packets)
            self.assertFalse(hub.queues[owner])

    def test_stalled_peer_times_out_without_retrying_or_blocking_other_account(self):
        hub = TeamArena(clock=lambda: 0)
        stalled, healthy = Session(), Session()
        stalled_owner, healthy_owner = hub.identity(stalled), hub.identity(healthy)
        hub.put(stalled_owner, *self.burst())
        hub.put(healthy_owner, b'\x39', b'\x38\x28\0\0\0')
        sender, receiver = socket.socketpair()
        with closing(sender), closing(receiver):
            sender.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            # Substitute only the duration; exercise an actual socket timeout.
            with patch('server.team_arena.TEAM_SEND_TIMEOUT_SECONDS', .1):
                with self.assertLogs('tio.server', level='WARNING') as logs:
                    with self.assertRaises(TimeoutError):
                        hub.drain(stalled, sender, InitialCipher('S2C'))
            self.assertIn('battle_delivery_failed', logs.output[0])
            self.assertFalse(hub.queues[stalled_owner])
        sender, receiver = socket.socketpair()
        with closing(sender), closing(receiver):
            receiver.settimeout(2)
            hub.drain(healthy, sender, InitialCipher('S2C'))
            reader = InitialFrameReader(InitialCipher('S2C'))
            replies = []
            while len(replies) < 2:
                replies.extend(reader.feed(receiver.recv(65535)))
            reader.finish()
            self.assertEqual(replies, [b'\x39', b'\x38\x28\0\0\0'])

    def test_write_budget_does_not_lengthen_the_input_poll(self):
        hub = TeamArena(clock=lambda: 0)
        session = Session()
        owner = hub.identity(session)
        hub.put(owner, b'\x39')
        sender, receiver = socket.socketpair()
        with closing(sender), closing(receiver):
            sender.settimeout(.1)
            # Isolate the transport poll from unrelated world/SQL maintenance.
            with patch.object(hub, 'tick'):
                hub.pump(session, sender, InitialFrameReader(InitialCipher('C2S')),
                         InitialCipher('S2C'))
            self.assertAlmostEqual(sender.gettimeout(), .1)
            receiver.settimeout(2)
            reader = InitialFrameReader(InitialCipher('S2C'))
            self.assertEqual(reader.feed(receiver.recv(65535)), [b'\x39'])


if __name__ == '__main__':
    unittest.main()
