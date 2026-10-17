"""Native list06 reports live game accounts and explicit backend availability."""
import socket
import threading
import time
import unittest
from types import SimpleNamespace

from server.multi import MultiServer,MAX_SESSIONS
import test_multi_account as fixture


class ServerStatusTests(unittest.TestCase):
    def setUp(self):
        self.router=object.__new__(MultiServer)
        self.router.lock=threading.Lock();self.router.active_accounts={}
        self.router.server=SimpleNamespace(stopping=threading.Event())
        listener=socket.socket();self.addCleanup(listener.close)
        self.router.game_listeners=(listener,)

    def account(self,name,*,game=False,stopped=False):
        exchange=SimpleNamespace(authenticated_account=name,game_authenticated=game,stopping=threading.Event())
        if stopped:exchange.stopping.set()
        self.router.active_accounts[name]=exchange
        return exchange

    def test_live_empty_backend_is_available_with_zero_players(self):
        self.assertEqual(self.router.server_status(),(0,MAX_SESSIONS,True))

    def test_login_and_pending_handoffs_do_not_count_before_game_auth2(self):
        alice=self.account('alice');self.account('bob')
        self.assertEqual(self.router.server_population(),(0,MAX_SESSIONS))
        self.router.game_authenticated(alice)
        self.assertEqual(self.router.server_status(),(1,MAX_SESSIONS,True))

    def test_unique_login_identity_counts_once_even_with_character_aliases(self):
        alice=self.account('alice',game=True);self.account('bob',game=True)
        self.router.active_accounts['@character:alice:2']=alice
        self.assertEqual(self.router.server_population(),(2,MAX_SESSIONS))

    def test_disconnected_game_excluded_while_account_claim_waits_for_settlement(self):
        self.account('alice',game=True);self.account('bob',game=True,stopped=True)
        self.assertEqual(self.router.server_population()[0],1)
        self.assertIn('bob',self.router.active_accounts)

    def test_unready_closed_listener_and_shutdown_cannot_reuse_live_count(self):
        self.account('alice',game=True)
        listener=self.router.game_listeners[0]
        self.router.game_listeners=()
        self.assertEqual(self.router.server_status(),(0,MAX_SESSIONS,False))
        self.router.game_listeners=(listener,);listener.close()
        self.assertEqual(self.router.server_status(),(0,MAX_SESSIONS,False))
        self.router.server.stopping.set()
        self.assertEqual(self.router.server_status(),(0,MAX_SESSIONS,False))

    def test_game_authentication_requires_live_claimed_account(self):
        alice=self.account('alice');self.router.active_accounts.pop('alice')
        with self.assertRaises(ValueError):self.router.game_authenticated(alice)
        self.assertFalse(alice.game_authenticated)
        self.router.active_accounts['alice']=alice;self.router.server.stopping.set()
        with self.assertRaises(ValueError):self.router.game_authenticated(alice)
        self.assertFalse(alice.game_authenticated)


class NativeServerStatusTcpTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.MultiAccountTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_wire_counts_after_auth2_then_updates_on_disconnect(self):
        self.case.start();router=self.case.server.multi
        alice=self.case.handoff(self.case.begin('alice'))
        entry=self.case.last_server_entry
        self.assertEqual((entry.unknown_u16_02,entry.unknown_u8_02),(0,1))
        self.assertEqual(router.server_population()[0],0)
        self.case.character_screen(alice)
        self.assertEqual(router.server_population()[0],1)
        bob=self.case.handoff(self.case.begin('bob'))
        entry=self.case.last_server_entry
        self.assertEqual((entry.unknown_u16_02,entry.unknown_u8_02),(1,1))
        self.assertEqual(router.server_population()[0],1)
        self.case.character_screen(bob)
        self.assertEqual(router.server_population()[0],2)
        bob.sock.close();deadline=time.monotonic()+5
        while router.server_population()[0]!=1:
            if time.monotonic()>deadline:self.fail('Disconnected game retained in online count')
            time.sleep(.01)
        self.assertEqual(router.server_status(),(1,MAX_SESSIONS,True))

    def wait_at_server_list(self,name):
        from test_server_deployment import Peer
        from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,
            InitialReply,encode_initial_reply,decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
        peer=Peer(self.case.connect(self.case.config.game_port))
        fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        peer.send(encode_basic_login_request(BasicLoginRequest(name.encode(),fixture.PASSWORD.encode(),transform_auth_value(token))))
        self.assertEqual(peer.receive(),b'\x04\0')
        return peer,(fields[1],token)

    def refresh(self,peer):
        from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
        reply=decode_server_list(peer.receive())
        self.assertEqual(reply.trailing_bytes,b'')
        return reply.entries[0]

    def test_repeat05_refreshes_population_and_reuses_the_same_handoff(self):
        from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
        self.case.start();router=self.case.server.multi
        alice=self.case.handoff(self.case.begin('alice'));self.case.character_screen(alice)
        bob,key=self.wait_at_server_list('bob')
        self.assertEqual(self.refresh(bob).unknown_u16_02,1)
        self.assertFalse(router.pending)
        alice.sock.close();deadline=time.monotonic()+5
        while router.server_population()[0]:
            if time.monotonic()>deadline:self.fail('Closed game retained in repeated list')
            time.sleep(.01)
        entry=self.refresh(bob)
        self.assertEqual((entry.unknown_u16_02,entry.unknown_u8_02),(0,1))
        self.assertFalse(router.pending)
        bob.send(encode_server_login_request(ServerLoginRequest(1,bytes(8))))
        self.assertEqual(bob.receive(),b'\x08\0');bob.sock.close()
        game=self.case.handoff(key);self.case.character_screen(game)
        self.assertEqual(router.server_population()[0],1)

    def test_refresh_and_native_selection_in_one_tcp_read_do_not_lose_choice(self):
        from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
        from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
        from tio.protocol.transport import encode_initial_frame
        self.case.start();peer,key=self.wait_at_server_list('alice')
        self.assertEqual(self.refresh(peer).unknown_u8_02,1)
        packets=(encode_server_list_request(ServerListRequest(0,0,b'')),
                 encode_server_login_request(ServerLoginRequest(1,bytes(8))))
        peer.sock.sendall(b''.join(encode_initial_frame(packet,peer.outbound) for packet in packets))
        self.assertEqual(decode_server_list(peer.receive()).entries[0].unknown_u16_02,0)
        self.assertEqual(peer.receive(),b'\x08\0');peer.sock.close()
        game=self.case.handoff(key);self.case.character_screen(game)
        self.assertEqual(self.case.server.multi.server_population()[0],1)

    def test_backend_shutdown_closes_preselection_and_cannot_report_available(self):
        self.case.start();peer,_=self.wait_at_server_list('alice')
        self.assertEqual(self.refresh(peer).unknown_u8_02,1)
        self.case.server.stop()
        with self.assertRaises((EOFError,OSError)):peer.receive()
        self.assertEqual(self.case.server.multi.server_status(),(0,MAX_SESSIONS,False))
