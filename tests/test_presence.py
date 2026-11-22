from collections import deque
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.presence import Presence
from tio.protocol.presence import Player,encode_players
from tio.protocol.chat import decode_send,encode_message


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.hub=Presence();self.sessions=[]
        class Session:pass
        for i,(name,town) in enumerate((('Alice',3),('Bob',3),('Carol',9))):
            s=Session();s.account=name.lower();s.probe_character_id=1
            self.sessions.append(s)
            self.hub.players[s]=(town,Player(100+i,name.encode()))
            self.hub.queues[s]=deque();self.hub.messages[s]=deque()

    def test_list_location_self_id_and_disconnect(self):
        a,b,c=self.sessions
        self.hub.handle(a,b'\xc7\1')
        packets=tuple(self.hub.queues[a])
        self.assertEqual([p[:2] for p in packets[:3]],[b'\xc7\4',b'\xc7\2',b'\x51'])
        self.assertIn(b'Carol',packets[1])
        result=packets[-1]
        self.assertIn(b'Alice',result);self.assertIn(b'Bob',result);self.assertNotIn(b'Carol',result)
        self.assertEqual(result[2:6],(1).to_bytes(4,'little'))
        self.hub.disconnect(b)
        self.assertNotIn(b'Bob',self.hub.queues[a][-1])
        self.assertNotIn(b'Bob',self.hub.queues[c][1])
        self.assertIn(b'Carol',self.hub.queues[c][-1])

    def test_unicode_local_and_global_chat_and_no_sender_spoof(self):
        a,b,c=self.sessions
        text='Привет другу'
        request=b'\x21\0'+text.encode('utf-16-le')+b'\0\0'
        self.assertEqual(decode_send(request),(0,text,b''))
        self.hub.handle(a,request)
        self.assertEqual(list(self.hub.messages[b]),[encode_message(0,b'Alice',text)])
        self.assertFalse(self.hub.messages[a])
        self.assertFalse(self.hub.messages[c])
        self.hub.messages[b].clear()
        self.hub.handle(a,b'\x21\x0c'+text.encode('utf-16-le')+b'\0\0')
        expected=encode_message(12,b'Alice',text)
        self.assertFalse(self.hub.messages[a])
        self.assertEqual(list(self.hub.messages[b]),[expected])
        self.assertEqual(list(self.hub.messages[c]),[expected])

    def test_private_message_not_broadcast(self):
        a,b,c=self.sessions
        self.hub.handle(a,b'\x21\1h\0i\0\0\0Bob\0')
        self.assertEqual(list(self.hub.private_messages[b]), [encode_message(1, b'Alice', 'hi')])
        self.assertNotIn(a, self.hub.private_messages)
        self.assertNotIn(c, self.hub.private_messages)

    def test_public_card_is_not_split_when_only_one_queue_slot_is_free(self):
        viewer = self.sessions[0]
        queue = self.hub.messages[viewer]
        queued = [b'\xc7\x01'] * 127
        queue.extend(queued)
        with patch.object(self.hub, '_character_profile', return_value=b'\xa7\x00card'):
            self.assertTrue(self.hub.handle(viewer, b'\x68\x00Bob\0'))
        self.assertEqual(list(queue), queued)

    def test_bad_requests_limits_and_refresh_preserves_messages(self):
        a,b,c=self.sessions
        for packet in (b'\x21',b'\x21\0x',b'\x21\0\0\0',b'\x21\0x\0\0\0fake'):
            self.hub.handle(a,packet)
        self.assertFalse(self.hub.messages[b])
        for _ in range(6):self.hub.handle(a,b'\x21\0x\0\0\0')
        self.assertEqual(len(self.hub.messages[b]),5)
        self.hub.refresh()
        self.assertEqual(len(self.hub.messages[b]),5)

    def test_live_sync_moves_location_and_battle_status(self):
        a,b,c=self.sessions
        a.database='unused';a.probe_character_name=b'Alice'
        a.locations=SimpleNamespace(current=lambda account:9)
        a.arena=SimpleNamespace(_fields={1:object()})
        with patch('server.public_profile.read_profile',return_value=SimpleNamespace(level=4)):
            self.hub.sync(a)
        self.assertNotIn(b'Alice',self.hub.queues[b][-1])
        self.assertIn(b'Alice',self.hub.queues[c][-1])
        self.assertEqual(self.hub.players[a][1].status,1)
        self.assertEqual(self.hub.players[a][1].level,4)

    def test_trade_help_share_location_audience(self):
        a,b,c=self.sessions
        for channel in (6,8):
            for messages in self.hub.messages.values():messages.clear()
            text='Привет, помощь?'
            self.hub.handle(a,bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0')
            self.assertEqual(list(self.hub.messages[b]),[encode_message(channel,b'Alice',text)])
            self.assertFalse(self.hub.messages[a])
            self.assertFalse(self.hub.messages[c])

    def test_clan_and_alliance_chat_do_not_echo_to_sender(self):
        class FakeDatabase:
            def execute(self,query,*_args):
                return [('alice',),('bob',)] if query.startswith('SELECT account FROM clan_members') else []
            def close(self):pass

        a,b,c=self.sessions;a.database='unused'
        with patch('tio.db_transaction.connect',return_value=FakeDatabase()), \
             patch('tio.clans.membership',return_value={'id':42}), \
             patch('tio.alliances.alliance_for_clan',return_value={'clans':(42,)}):
            for channel in (2,7):
                for messages in self.hub.messages.values():messages.clear()
                text='Клан, проверка!'
                self.hub.handle(a,bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0')
                self.assertFalse(self.hub.messages[a])
                self.assertEqual(list(self.hub.messages[b]),[encode_message(channel,b'Alice',text)])
                self.assertFalse(self.hub.messages[c])

    def test_world_map_has_global_players_and_empty_local_tabs(self):
        a,b,c=self.sessions
        self.hub.players[a]=(None,self.hub.players[a][1])
        self.hub.players[b]=(None,self.hub.players[b][1])
        for _ in range(10):self.hub.refresh()
        self.assertEqual(len(self.hub.queues[a]),4)
        self.assertEqual(self.hub.queues[a][-1],b'\x4f\0')
        self.assertIn(b'Bob',self.hub.queues[a][1])
        for channel in (0,6,8):self.hub.handle(a,bytes((0x21,channel))+b'x\0\0\0')
        self.assertFalse(self.hub.messages[b])

    def test_rosters_work_in_every_supported_location(self):
        from tio.locations import TOWNS
        a,b,c=self.sessions
        for town in TOWNS:
            with self.subTest(town=town):
                self.hub.players[a]=(town,self.hub.players[a][1])
                self.hub.players[b]=(town,self.hub.players[b][1])
                self.hub.players[c]=(None,self.hub.players[c][1])
                self.hub.refresh()
                self.assertIn(b'Bob',self.hub.queues[a][-1])
                self.assertNotIn(b'Carol',self.hub.queues[a][-1])
                self.assertIn(b'Carol',self.hub.queues[a][1])
