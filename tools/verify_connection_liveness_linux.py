"""Run only inside a disposable Linux network namespace (unshare -n).

Uses throwaway accounts/SQLite and loopback listeners. No hosted saves are read.
"""
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_multi_account import MultiAccountTests


class DeadPeerTests(MultiAccountTests):
    def test_blackhole(self):
        self.start()
        alice = self.handoff(self.begin('alice')); self.enter(alice, 'Alice')
        bob = self.handoff(self.begin('bob')); self.enter(bob, 'Bob')
        multi = self.server.multi
        with multi.lock:
            exchange = multi.active_accounts['alice']
        game = exchange.connections[-1]
        self.assertEqual(game.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
        self.assertEqual(game.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE), 60)
        self.assertEqual(game.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL), 15)
        self.assertEqual(game.getsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT), 4)
        self.assertEqual(game.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT), 120000)
        # Speed up this test socket only; production values were checked above.
        game.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 2)
        game.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 1)
        game.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 2)
        game.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, 4000)
        # A healthy, quiet client still ACKs TCP probes without game packets.
        time.sleep(5)
        self.ping(alice)
        rule = ['INPUT', '-i', 'lo', '-p', 'tcp', '--sport',
                str(alice.sock.getsockname()[1]), '--dport',
                str(self.config.session_port), '-j', 'DROP']
        subprocess.run(['iptables', '-A', *rule], check=True)
        started = time.monotonic()
        try:
            exchange.thread.join(12)
            self.assertFalse(exchange.thread.is_alive(), 'Blackholed peer retained account')
            with multi.lock:
                self.assertNotIn('alice', multi.active_accounts)
                self.assertIn('bob', multi.active_accounts)
            self.ping(bob)
        finally:
            subprocess.run(['iptables', '-D', *rule], check=True)
        print(f'Kernel detected blackhole and released account in {time.monotonic()-started:.2f}s')
        restored = self.handoff(self.begin('alice')); self.enter(restored, 'Alice')
        self.ping(restored)


if __name__ == '__main__':
    # Prevent accidentally installing packet-drop rules in the host namespace.
    import os
    if os.readlink('/proc/self/ns/net') == os.readlink('/proc/1/ns/net'):
        raise SystemExit('Requires a disposable network namespace: unshare -n')
    subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True)
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestSuite([DeadPeerTests('test_blackhole')]))
    raise SystemExit(not result.wasSuccessful())
