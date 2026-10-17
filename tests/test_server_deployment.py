"""Deployment boundary: real sockets and SQLite, no Windows client/hooks."""
from collections import deque
from contextlib import closing
from dataclasses import replace
import importlib
import json
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest

from server.config import ServerConfig
from server.runtime import Server, preflight, ROOT
from tio.protocol.transport import (InitialCipher, InitialFrameReader, InitialReply,
    encode_initial_reply, encode_initial_frame, decode_initial_challenge,
    decode_initial_completion, expected_reply_fields)
from tio.protocol.login import BasicLoginRequest, encode_basic_login_request, transform_auth_value
from tio.protocol.server_list import ServerListRequest, encode_server_list_request, decode_server_list
from tio.protocol.server_login import ServerLoginRequest, encode_server_login_request
from tio.protocol.mode1 import derive_mode1_key, Mode1Reply, encode_mode1_reply
from tio.protocol.character_create import CharacterCreateRequest, encode_character_create
from tio.protocol.character_select import decode_character_list
from tio.protocol.shop_purchase import ShopPurchase, encode_shop_purchase


class Peer:
    def __init__(self, sock, key=None):
        self.sock = sock
        self.reader = InitialFrameReader(InitialCipher('S2C', key) if key else InitialCipher('S2C'))
        self.outbound = InitialCipher('C2S', key) if key else InitialCipher('C2S')
        self.pending = deque()

    def receive(self):
        while not self.pending:
            data = self.sock.recv(65535)
            if not data:
                raise EOFError('Server disconnected')
            self.pending.extend(self.reader.feed(data))
        return self.pending.popleft()

    def send(self, packet):
        self.sock.sendall(encode_initial_frame(packet, self.outbound))

    def until(self, prefix, *, max_packets=100):
        for _ in range(max_packets):
            packet = self.receive()
            if packet.startswith(prefix):
                return packet
        raise AssertionError('Missing reply ' + prefix.hex())


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.config = ServerConfig('0.0.0.0', '203.0.113.17', port, self.root / 'players', 'ERROR')
        self.errors = []

    def start(self):
        self.server = Server(self.config)
        def run():
            try:self.server.serve()
            except BaseException as error:self.errors.append(error)
        self.thread = threading.Thread(target=run)
        self.thread.start()
        deadline = time.monotonic() + 5
        while self.server.exchange is None and not self.errors:
            if time.monotonic() > deadline:raise AssertionError('Startup timeout')
            time.sleep(.01)
        self.assertFalse(self.errors)
        self.addCleanup(self.stop)

    def stop(self):
        self.server.stop()
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive(), 'Shutdown hung')
        self.assertFalse(self.errors)

    def login(self, delayed_choice=False):
        login_socket = socket.create_connection(('127.0.0.1', self.config.game_port), timeout=5)
        self.addCleanup(login_socket.close)
        peer = Peer(login_socket)
        challenge = decode_initial_challenge(peer.receive())
        fields = expected_reply_fields(challenge)
        peer.send(encode_initial_reply(InitialReply(*fields, 0, b'\0'*3)))
        token = decode_initial_completion(peer.receive()).unknown_u32_01
        peer.send(encode_basic_login_request(BasicLoginRequest(b'probe_user', b'probe_password', transform_auth_value(token))))
        self.assertEqual(peer.receive(), b'\x04\0')
        peer.send(encode_server_list_request(ServerListRequest(0, 0, b'')))
        entry = decode_server_list(peer.receive()).entries[0]
        self.assertEqual(entry.address_octets, socket.inet_aton(self.config.advertised_address))
        self.assertEqual(entry.unknown_u16_01, self.config.game_port)
        peer.send(encode_server_login_request(ServerLoginRequest(1, b'\0'*8)))
        self.assertEqual(peer.receive(), b'\x08\0')
        login_socket.close()  # Native client ends login before mode1 connects.
        game_socket = socket.create_connection(('127.0.0.1', self.config.game_port), timeout=5)
        self.addCleanup(game_socket.close)
        raw = bytearray()
        while len(raw) < 11:raw.extend(game_socket.recv(11-len(raw)))
        self.assertEqual(raw[:3], b'\x0b\0\x09')
        game = Peer(game_socket, derive_mode1_key(bytes(raw[3:])))
        game.send(encode_mode1_reply(Mode1Reply(fields[1], token)))
        self.assertEqual(game.receive(), b'\x0b\0')
        game.send(b'\x0c0.21:63\0\0')
        self.assertEqual(game.receive(), b'\x0d\0')
        for name in (b'items', b'skills', b'zones'):
            self.assertTrue(game.receive().startswith(b'\xb9\x01'))
            game.send(b'\xb9\x02' + name + b'\0')
            self.assertTrue(game.receive().startswith(b'\xb9\x03'))
            game.send(b'\xb9\x04')
        records = decode_character_list(game.receive())
        if not records:
            game.send(encode_character_create(CharacterCreateRequest(b'ProbeNew', 0, (0,0,0,0))))
            self.assertEqual(game.receive(), b'\x12\0')
            records = decode_character_list(game.receive())
        self.assertEqual(records[0].record_id, 1)
        if delayed_choice:
            time.sleep(5.5)  # Old automatic-probe deadline disconnected here.
            game.send(b'\x70')
            self.assertEqual(game.receive(), b'\x9e')
        game.send(bytes.fromhex('1701000000'))
        self.assertTrue(game.receive().startswith(b'\x18'))
        game.send(b'\x19')
        game.until(b'\x66')
        game.send(b'\x70')
        self.assertEqual(game.until(b'\x9e'), b'\x9e')
        return login_socket, game

    def test_full_tcp_login_purchase_shutdown_restart_preserves_save(self):
        self.start()
        self.assertEqual(self.server.listener.getsockname()[0], '0.0.0.0')
        _, game = self.login(delayed_choice=True)
        game.send(encode_shop_purchase(ShopPurchase(1, 0, 81, 2)))
        game.until(b'\xc8\x39')
        # First purchase earns a real 100-credit achievement on the next tick.
        # Wait for that existing game behavior before comparing restart state.
        game.until(b'\xb5\x03')
        game.until(b'\xc8\x39')
        with closing(sqlite3.connect(self.config.database)) as db:
            before = db.execute('SELECT credits,gold FROM wallets WHERE account=?', ('probe_user',)).fetchone()
            inventory = db.execute('SELECT inventory_packet FROM owned_pets WHERE pet_id=1').fetchone()[0]
        self.assertEqual(before, (2800, 0))
        self.stop()  # Includes closing an active game socket and waiting for worker.
        self.start()
        self.login()
        with closing(sqlite3.connect(self.config.database)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT credits,gold FROM wallets WHERE account=?', ('probe_user',)).fetchone(), before)
            self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets WHERE pet_id=1').fetchone()[0], inventory)

    def test_disconnect_reaccepts_on_same_port_and_idle_stop(self):
        self.start()
        for _ in range(2):
            with socket.create_connection(('127.0.0.1', self.config.game_port), timeout=5) as conn:
                decode_initial_challenge(Peer(conn).receive())
        self.stop()

    def test_sigint_and_sigterm_request_orderly_stop(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            server = Server(self.config)
            old = signal.signal(sig, server.stop)
            try:
                signal.raise_signal(sig)
                self.assertTrue(server.stopping.is_set())
            finally:signal.signal(sig, old)

    def test_config_relative_paths_validation_and_readonly_preflight(self):
        path = self.root / 'server.toml'
        values = dict(bind_address='0.0.0.0', advertised_address='203.0.113.17', game_port=28512,
                      data_directory='players', log_level='INFO')
        def write():path.write_text('\n'.join(f'{k} = {json.dumps(v)}' for k,v in values.items()), encoding='utf-8')
        write()
        config = ServerConfig.load(path)
        self.assertEqual(config.data_directory, self.root / 'players')
        preflight(config)
        self.assertFalse(config.data_directory.exists())
        for key, value in [('advertised_address','0.0.0.0'), ('advertised_address','127.0.0.1'), ('game_port',0)]:
            original = values[key];values[key] = value;write()
            with self.assertRaises(ValueError):ServerConfig.load(path)
            values[key] = original

    def test_runtime_package_imports_without_workspace_or_research_modules(self):
        from deploy.package_server import package
        bundle = self.root / 'server.tar.gz'
        package(bundle)
        destination = self.root / 'release'
        with tarfile.open(bundle) as archive:
            names = archive.getnames()
            self.assertFalse(any(n.startswith('data/') or n.endswith(('.dll','.exe','.sqlite3')) for n in names))
            archive.extractall(destination, filter='data')
        result = subprocess.run([sys.executable, '-S', '-m', 'server', '--check'], cwd=destination,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Preflight OK', result.stderr)

    def test_backup_preserves_source_and_refuses_overwrite(self):
        from deploy.backup import backup
        source = self.root / 'original.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE marker (value TEXT)')
            db.execute("INSERT INTO marker VALUES ('keep')");db.commit()
        before = source.read_bytes()
        target = self.root / 'backup.sqlite3'
        backup(source, target)
        self.assertEqual(source.read_bytes(), before)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('SELECT value FROM marker').fetchone()[0], 'keep')
        with self.assertRaises(FileExistsError):backup(source, target)
