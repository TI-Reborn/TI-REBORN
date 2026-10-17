"""Offline observer validation; these tests never open a hosted connection."""
import unittest

from tools.observe_legacy_server_list_tls import observe_lists
from tio.protocol.server_list import ServerEntry,ServerList,encode_server_list


class Peer:
    def __init__(self,responses):
        self.responses=iter(responses)
        self.sent=[]

    def send(self,packet):
        self.sent.append(packet)

    def receive(self):
        return next(self.responses)


def listing(online,*,available=1,trailing=b'',identity=1,port=28513):
    return encode_server_list(ServerList(0,(ServerEntry(identity,b'\x7f\0\0\x01',port,online,15,available),),trailing))


class ServerListObserverTests(unittest.TestCase):
    def observe(self,peer,expected):
        return observe_lists(peer,expected,interval=0,sleep=lambda seconds:None)

    def test_zero_one_two_game_counts_use_only_same_original05(self):
        for expected in (0,1,2,3,65535):
            with self.subTest(expected=expected):
                peer=Peer([listing(expected)]*3)
                observations=self.observe(peer,expected)
                self.assertEqual([x['online'] for x in observations],[expected]*3)
                self.assertEqual(peer.sent,[b'\x05'+bytes(6)]*3)

    def test_count_outside_wire_u16_is_refused(self):
        for count in (-1,65536):
            with self.subTest(count=count):
                with self.assertRaises(AssertionError):
                    self.observe(Peer([]),count)

    def test_offline_flag_is_not_accepted_with_cached_online(self):
        with self.assertRaises(AssertionError):
            self.observe(Peer([listing(2,available=0)]),2)

    def test_changed_count_during_repeat_is_detected(self):
        with self.assertRaises(AssertionError):
            self.observe(Peer([listing(2),listing(1)]),2)

    def test_nonempty_auth2_echo_refused(self):
        with self.assertRaises(AssertionError):
            self.observe(Peer([listing(2,trailing=b'changed')]),2)

    def test_wrong_server_or_route_refused(self):
        for raw in (listing(2,identity=2),listing(2,port=29513)):
            with self.subTest(raw=raw):
                with self.assertRaises(AssertionError):
                    self.observe(Peer([raw]),2)

    def test_token_rotation_or_server_handoff_reply_refused(self):
        for raw in (b'\x03'+bytes(12),b'\x08\0'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    self.observe(Peer([listing(2),raw]),2)


if __name__=='__main__':
    unittest.main()
