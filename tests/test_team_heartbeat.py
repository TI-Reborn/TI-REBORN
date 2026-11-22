"""Quiet shared battles must reset the original client's frame watchdog."""
from types import SimpleNamespace
from contextlib import closing
import socket
from threading import Event, Thread
import unittest
from unittest.mock import patch
import select
from server.team_arena import TeamArena
from tio.protocol.transport import InitialCipher, InitialFrameReader


class TeamHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.hub=TeamArena(clock=lambda:self.now)
        # TeamArena uses sessions as identity keys.
        class Session: database=None
        self.session=Session()
        self.owner=self.hub.identity(self.session)
        self.frames=[]
        self.socket=SimpleNamespace(sendall=self.frames.append,settimeout=lambda seconds: None)
        self.cipher=InitialCipher('S2C')
        self.reader=InitialFrameReader(InitialCipher('S2C'))

    def drain(self):
        self.hub.drain(self.session,self.socket,self.cipher)
        packets=[]
        for frame in self.frames:packets.extend(self.reader.feed(frame))
        self.frames.clear()
        return packets

    def test_quiet_wall_wait_gets_periodic_native_replies_without_client_ping(self):
        self.assertEqual(self.drain(),[])
        for second in (9,10,19,20,29,30,39,40,50,60):
            self.now=second
            self.assertEqual(self.drain(),[b'\x9e'] if second%10==0 else [])
        self.assertFalse(self.hub.queues[self.owner])

    def test_turn_events_do_not_replace_watchdog_reply_and_ping_resets_schedule(self):
        self.drain();self.now=10
        self.hub.put(self.owner,b'\x39')
        self.assertEqual(self.drain(),[b'\x39',b'\x9e'])
        self.now=15;self.hub.handle(self.session,b'\x70')
        self.assertEqual(self.drain(),[b'\x9e'])
        self.now=20;self.assertEqual(self.drain(),[])
        self.now=25;self.assertEqual(self.drain(),[b'\x9e'])

    def test_failed_send_does_not_claim_heartbeat_delivery(self):
        self.drain();self.now=10
        def fail(frame):raise ConnectionResetError('lost peer')
        self.socket.sendall=fail
        with self.assertRaises(ConnectionResetError):self.drain()
        self.assertEqual(self.session._team_heartbeat_at,0)

    def test_session_pump_delivers_pending_events_without_ticking_arena(self):
        def receive(_size):
            raise socket.timeout()

        self.socket.recv = receive
        self.hub.put(self.owner, b'\x39')
        with patch.object(self.hub, 'tick') as tick:
            self.hub.pump(self.session, self.socket, self.reader, self.cipher)
        tick.assert_not_called()
        self.assertEqual([packet for frame in self.frames for packet in self.reader.feed(frame)], [b'\x39'])

    def test_idle_peer_wakes_for_queued_packet_without_socket_input(self):
        waiting = Event()
        ready = []

        def select_wait(readers, writers, errors, timeout):
            waiting.set()
            result = select.select(readers, writers, errors, timeout)
            ready.extend(result[0])
            return result

        game, peer = socket.socketpair()
        with closing(game), closing(peer), self.hub.delivery_wakeup(self.session) as signal:
            with patch('server.team_arena.select', side_effect=select_wait):
                worker = Thread(target=self.hub.pump, args=(self.session, game, self.reader, self.cipher),
                                kwargs={'wakeup': signal})
                worker.start()
                try:
                    self.assertTrue(waiting.wait(2))
                    with self.hub.lock:
                        self.hub.put(self.owner, b'\x39')
                finally:
                    worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertIn(signal, ready)
            peer.settimeout(1)
            self.assertEqual(self.reader.feed(peer.recv(1024)), [b'\x39'])


if __name__=='__main__':unittest.main()
