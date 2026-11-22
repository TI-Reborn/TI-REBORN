"""TLS uses the actual shared TCP/account backend and nonproduction certificates."""
from dataclasses import replace
from pathlib import Path
import socket
import ssl
import os
import tempfile
import time
import unittest

import test_multi_account as fixture
from test_server_deployment import Peer
from server.config import ServerConfig,TLSConfig
from server.tls import bridge_preface,read_bridge_preface,TLSContexts,build_context
from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,
    InitialReply,encode_initial_reply,decode_initial_completion)
from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
from tio.protocol.mode1 import Mode1Reply,encode_mode1_reply,derive_mode1_key

FIXTURES=Path(__file__).parent/'fixtures/game_tls'


def free_ports(count):
    sockets=[socket.socket() for _ in range(count)]
    try:
        for connection in sockets:connection.bind(('127.0.0.1',0))
        return [connection.getsockname()[1] for connection in sockets]
    finally:
        for connection in sockets:connection.close()


class TLSConfigTests(unittest.TestCase):
    def test_disabled_default_and_strict_enabled_config(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'server.toml'
            basic='bind_address="127.0.0.1"\nadvertised_address="127.0.0.1"\ngame_port=28512\ndata_directory="data"\nlog_level="ERROR"\n'
            path.write_text(basic)
            self.assertFalse(ServerConfig.load(path).tls.enabled)
            valid='multi_account=true\n[tls]\nenabled=true\ncertificate="cert.pem"\nprivate_key="key.pem"\n'
            path.write_text(basic+valid)
            config=ServerConfig.load(path)
            self.assertEqual(config.tls.certificate,Path(root)/'cert.pem')
            self.assertTrue(config.tls.enabled)
            for fragment in ('[tls]\nenabled=true\ncertificate="cert"\nprivate_key="key"\n',
                    valid+'login_port=28512\n',valid+'max_handshakes=9\n',
                    valid+'handshake_timeout_seconds=0\n',valid+'unknown=true\n',
                    'multi_account=true\n[tls]\nenabled=true\n'):
                with self.subTest(fragment=fragment):
                    path.write_text(basic+fragment)
                    with self.assertRaises(ValueError):ServerConfig.load(path)

    def test_versioned_exact_preface_validates_and_does_not_consume_game_bytes(self):
        self.assertEqual(bridge_preface(28513),b'TIOT\x01\x00\x6f\x61')
        source,target=socket.socketpair()
        with source,target:
            source.sendall(bridge_preface(31001)+b'native')
            self.assertEqual(read_bridge_preface(target,time.monotonic()+1),31001)
            self.assertEqual(target.recv(6),b'native')
        for port in (0,80,65536,True):
            with self.assertRaises(ValueError):bridge_preface(port)

    def test_context_rejects_missing_mismatched_and_expired_credentials(self):
        config=TLSConfig(True,29512,29513,FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem')
        context=build_context(config)
        self.assertEqual(context.minimum_version,ssl.TLSVersion.TLSv1_2)
        for certificate,key in (('missing.pem','valid-key.pem'),('valid-chain.pem','rotated-key.pem'),
                ('expired-chain.pem','expired-key.pem')):
            with self.subTest(certificate=certificate):
                with self.assertRaises((OSError,ValueError)):
                    build_context(replace(config,certificate=FIXTURES/certificate,private_key=FIXTURES/key))

    def test_renewal_directory_symlink_is_resolved_again_for_each_context(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            for name in ('valid','rotated'):
                directory=root/name;directory.mkdir()
                (directory/'cert.pem').write_bytes((FIXTURES/(name+'-chain.pem')).read_bytes())
                (directory/'key.pem').write_bytes((FIXTURES/(name+'-key.pem')).read_bytes())
            current=root/'current'
            try:current.symlink_to(root/'valid',target_is_directory=True)
            except OSError:self.skipTest('Directory symlinks unavailable without host privileges')
            config=TLSConfig.load(dict(enabled=True,certificate='current/cert.pem',private_key='current/key.pem'),root)
            self.assertEqual(config.certificate,current/'cert.pem')
            contexts=TLSContexts(config)
            first=contexts.current()
            replacement=root/'next'
            replacement.symlink_to(root/'rotated',target_is_directory=True)
            os.replace(replacement,current)
            contexts.reload()
            self.assertIsNot(first,contexts.current())
            self.assertEqual(contexts.generation,2)


class GameTLSTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.MultiAccountTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        login,game=free_ports(2)
        self.cert=Path(self.case.temp.name)/'tls-cert.pem'
        self.key=Path(self.case.temp.name)/'tls-key.pem'
        self.cert.write_bytes((FIXTURES/'valid-chain.pem').read_bytes())
        self.key.write_bytes((FIXTURES/'valid-key.pem').read_bytes())
        self.case.config=replace(self.case.config,tls=TLSConfig(True,login,game,self.cert,self.key,1,4))
        self.context=ssl.create_default_context(cafile=str(FIXTURES/'ca.pem'))

    def connect(self,kind,*,preface=None,context=None):
        port=getattr(self.case.config.tls,kind+'_port')
        raw=self.case.connect(port)
        connection=(context or self.context).wrap_socket(raw,server_hostname='127.0.0.1')
        self.case.clients.append(connection)
        if kind=='login' and preface is not None:connection.sendall(preface)
        return connection

    def begin(self,account,bridge_port,*,password=fixture.PASSWORD,denied=None,language='russian'):
        preface=bytearray(bridge_preface(bridge_port));preface[5]=int(language=='english')
        peer=Peer(self.connect('login',preface=preface))
        self.assertIn(peer.sock.version(),('TLSv1.2','TLSv1.3'))
        challenge=decode_initial_challenge(peer.receive())
        previous=expected_reply_fields(challenge)
        peer.send(encode_initial_reply(InitialReply(*previous,0,b'\0'*3)))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        peer.send(encode_basic_login_request(BasicLoginRequest(account.encode(),password.encode(),transform_auth_value(token))))
        if denied is not None:
            self.assertEqual(peer.receive(),denied)
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
            return
        self.assertEqual(peer.receive(),b'\x04\0')
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
        entry=decode_server_list(peer.receive()).entries[0]
        self.assertEqual(entry.address_octets,socket.inet_aton('127.0.0.1'))
        self.assertEqual(entry.unknown_u16_01,bridge_port)
        peer.send(encode_server_login_request(ServerLoginRequest(1,b'\0'*8)))
        self.assertEqual(peer.receive(),b'\x08\0')
        peer.sock.close()
        return previous[1],token

    def handoff(self,key,*,denied=False):
        connection=self.connect('session')
        data=bytearray()
        while len(data)<11:
            part=connection.recv(11-len(data))
            if not part:raise EOFError('No mode1 challenge')
            data.extend(part)
        peer=Peer(connection,derive_mode1_key(bytes(data[3:])))
        peer.send(encode_mode1_reply(Mode1Reply(*key)))
        if denied:
            with self.assertRaises((EOFError,ConnectionResetError)):peer.receive()
            return
        self.assertEqual(peer.receive(),b'\x0b\0')
        return peer

    def until(self,predicate):
        deadline=time.monotonic()+5
        while not predicate():
            if time.monotonic()>=deadline:self.fail('Condition timed out')
            time.sleep(.02)

    def test_mixed_language_accounts_receive_private_translations_and_keep_chat(self):
        from tio.localization import english
        from contextlib import closing
        import sqlite3
        self.case.start()
        alice=self.handoff(self.begin('alice',31001,language='russian'));self.case.enter(alice,'Alice')
        bob=self.handoff(self.begin('bob',31002,language='english'));self.case.enter(bob,'Bob')
        for peer in (alice,bob):peer.send(b'\x21\0'+'!bank unknown'.encode('utf-16-le')+b'\0\0')
        russian=alice.until(b'\x22');translated=bob.until(b'\x22')
        raw_text=russian[russian.index(b'\0',6)+1:-2].decode('utf-16-le')
        self.assertIn(english(raw_text).encode('utf-16-le'),translated)
        self.assertNotEqual(russian,translated)
        self.assertEqual(self.case.server.multi.active_accounts['alice'].language,'russian')
        self.assertEqual(self.case.server.multi.active_accounts['bob'].language,'english')
        chat='Боец не принадлежит вашему аккаунту'
        alice.send(b'\x21\0'+chat.encode('utf-16-le')+b'\0\0')
        self.assertIn(chat.encode('utf-16-le'),bob.until(b'\x22'))
        with closing(sqlite3.connect(self.case.config.database)) as db:
            self.assertEqual(dict(db.execute('SELECT account,credits FROM wallets')),{'alice':10000,'bob':10000})

    def test_two_tls_accounts_same_ip_reordered_handoffs_and_direct_mixing(self):
        self.case.start()
        alice=self.begin('alice',31001)
        bob=self.begin('bob',31002)
        self.case.handoff(alice,denied=True)
        self.handoff((alice[0],bob[1]),denied=True)
        b=self.handoff(bob);self.case.enter(b,'Bob')
        a=self.handoff(alice);self.case.enter(a,'Alice')
        self.handoff(alice,denied=True)
        self.assertTrue(self.case.server.multi.active_accounts['alice'].login_tls)
        self.assertEqual(self.case.server.multi.active_accounts['alice'].login_peer_address,'127.0.0.1')
        self.case.ping(a);self.case.ping(b)
        exchange=self.case.server.multi.active_accounts['bob']
        b.sock.close();exchange.thread.join(5)
        direct=self.case.begin('bob')
        self.handoff(direct,denied=True)
        b=self.case.handoff(direct);self.case.enter(b,'Bob')
        self.case.ping(a);self.case.ping(b)

    def test_tls_native_denials_allow_valid_retry_and_preserve_other_account(self):
        from contextlib import closing
        import sqlite3
        self.case.start()
        bob=self.handoff(self.begin('bob',31001));self.case.enter(bob,'Bob')
        tables=('accounts','characters','owned_pets','wallets','character_locations')
        with closing(sqlite3.connect(self.case.config.database)) as db:
            before={name:db.execute('SELECT * FROM '+name).fetchall() for name in tables}
        with self.assertLogs('tio.server',level='WARNING') as logs:
            self.begin('alice',31002,password='wrong-password',denied=b'\x04\x03')
            self.begin('unknown',31003,denied=b'\x04\x03')
            self.begin('bob',31004,denied=b'\x04\x07')
        self.assertTrue(all('transport=tls' in line for line in logs.output))
        self.assertNotIn('wrong-password','\n'.join(logs.output))
        self.assertNotIn(fixture.PASSWORD,'\n'.join(logs.output))
        with closing(sqlite3.connect(self.case.config.database)) as db:
            self.assertEqual({name:db.execute('SELECT * FROM '+name).fetchall() for name in tables},before)
        self.case.ping(bob)
        alice=self.handoff(self.begin('alice',31005));self.case.enter(alice,'Alice')
        self.case.ping(alice);self.case.ping(bob)
        self.assertEqual(self.case.server.multi.server_population()[0],2)

    def test_bad_or_incomplete_preface_releases_reservation_without_account_state(self):
        self.case.start()
        for preface in (b'JUNK\1\0\x75\x30',b'TIOT\2\0\x75\x30',b'TIOT\1\4\x75\x30',
                b'TIOT\1\0\0\1',b'TIO',b''):
            with self.subTest(preface=preface):
                connection=self.connect('login',preface=preface)
                with self.assertRaises((EOFError,ConnectionResetError)):
                    if connection.recv(64)==b'':raise EOFError()
                self.until(lambda:not self.case.server.multi.tls_pending)
        self.assertEqual(self.case.server.multi.server_population()[0],0)
        self.case.ping(self.enter_alice())

    def enter_alice(self):
        peer=self.handoff(self.begin('alice',32001));self.case.enter(peer,'Alice')
        return peer

    def test_slow_handshakes_shared_admission_and_authenticated_account_survives(self):
        self.case.start()
        alice=self.enter_alice()
        for _ in range(4):self.case.connect(self.case.config.tls.login_port)
        self.until(lambda:len(self.case.server.multi.tls_pending)==4)
        denied=self.case.connect(self.case.config.game_port)
        self.assertEqual(denied.recv(64),b'')
        denied=self.case.connect(self.case.config.tls.session_port)
        self.assertEqual(denied.recv(64),b'')
        self.case.ping(alice)
        self.until(lambda:not self.case.server.multi.tls_pending)
        self.case.ping(alice)

    def test_shutdown_closes_and_joins_incomplete_tls_handshakes(self):
        self.case.start()
        self.case.connect(self.case.config.tls.login_port)
        self.case.connect(self.case.config.tls.session_port)
        self.until(lambda:len(self.case.server.multi.tls_pending)==2)
        workers=tuple(self.case.server.multi.tls_workers)
        self.case.stop()
        self.assertTrue(all(not thread.is_alive() for thread in workers))
        self.assertFalse(self.case.server.multi.tls_workers)
        self.assertFalse(self.case.server.multi.tls_pending)
        self.assertFalse(self.case.server.multi.tls_connections)

    def test_validated_reload_preserves_live_connection_and_failed_reload_retains_context(self):
        self.case.start()
        alice=self.enter_alice()
        multi=self.case.server.multi
        first=multi.tls.current()
        self.cert.write_bytes((FIXTURES/'rotated-chain.pem').read_bytes())
        self.key.write_bytes((FIXTURES/'rotated-key.pem').read_bytes())
        self.case.server.reload_tls()
        self.until(lambda:multi.tls.generation==2)
        self.assertIsNot(first,multi.tls.current())
        self.case.ping(alice)
        new=self.connect('session')
        self.assertEqual(new.getpeercert(binary_form=True),ssl.PEM_cert_to_DER_cert((FIXTURES/'rotated.pem').read_text()))
        new.close()
        working=multi.tls.current()
        self.key.write_text('invalid test-only key')
        self.case.server.reload_tls()
        self.until(lambda:not self.case.server.tls_reload_requested.is_set())
        time.sleep(.1)
        self.assertIs(multi.tls.current(),working)
        self.assertEqual(multi.tls.generation,2)
        self.case.ping(alice)
        good=self.connect('session')
        self.assertEqual(good.getpeercert(binary_form=True),ssl.PEM_cert_to_DER_cert((FIXTURES/'rotated.pem').read_text()))
        good.close()

    def test_tls12_and_unknown_issuer_fail_closed(self):
        self.case.start()
        tls12=ssl.create_default_context(cafile=str(FIXTURES/'ca.pem'))
        tls12.minimum_version=tls12.maximum_version=ssl.TLSVersion.TLSv1_2
        connection=self.connect('login',preface=bridge_preface(33001),context=tls12)
        self.assertEqual(connection.version(),'TLSv1.2')
        self.assertTrue(connection.recv(64));connection.close()
        unknown=ssl.create_default_context(cafile=str(FIXTURES/'localhost.pem'))
        with self.assertRaises(ssl.SSLCertVerificationError):self.connect('login',context=unknown)
        self.until(lambda:not self.case.server.multi.tls_pending)
        self.assertEqual(self.case.server.multi.server_population()[0],0)
