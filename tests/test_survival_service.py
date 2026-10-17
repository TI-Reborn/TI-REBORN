import unittest
import test_matchmaking
from tio.survival_service import SurvivalService
from tio.protocol.arena import decode_member_list


class SurvivalServiceTests(unittest.TestCase):
    def test_admission_duplicate_and_authorized_cancel(self):
        now = [0]
        service = SurvivalService(clock=lambda: now[0])
        roster = test_matchmaking.SurvivalQueueTests().roster((2, 0, 1))
        reply = service.join(7, b'Player', b'\xba\x03\0\2', iter(roster))
        search_id, _, members = decode_member_list(reply)
        self.assertEqual(members[0].character_id, 7)
        self.assertEqual(len(members[0].pets), 2)
        self.assertEqual(members[0].unknown_flag_110, 1)
        self.assertEqual(service.queue.tickets[7].actors, (3, 1))
        now[0] = 10
        self.assertEqual(service.join(7, b'Player', b'\xba\x03\0\2', roster), reply)
        self.assertEqual(service.queue.tickets[7].joined_at, 0)
        self.assertEqual(service.set_ready(7, b'\xba\x07\0'), b'\xba\x08\1\0\0\0\7\0\0\0\0')
        self.assertTrue(service.searching(7))
        self.assertIsNone(service.queue.propose(7))
        service.set_ready(7, b'\xba\x07\1')
        self.assertEqual(service.queue.tickets[7].joined_at, 10)
        for packet in (b'\xba\x05\x08\0\0\0\0', b'\xba\x05\x07\0\0\0\1'):
            with self.assertRaises(ValueError): service.cancel(7, packet)
        self.assertTrue(service.searching(7))
        self.assertEqual(decode_member_list(service.cancel(7, b'\xba\x05\7\0\0\0\0')), (0xffffffff, 0, ()))
        self.assertFalse(service.searching(7))
        self.assertFalse(service.search_ids)

    def test_bad_request_never_admits_or_replaces_search(self):
        service = SurvivalService()
        roster = test_matchmaking.SurvivalQueueTests().roster((1, 2))
        for packet in (b'\xba\x03\0\1', b'\xba\x03\4\2', b'\xba\x03\0\2\0', b'\xba\x03'):
            with self.assertRaises(ValueError): service.join(1, b'Player', packet, roster)
            self.assertFalse(service.searching(1))
        with self.assertRaises(ValueError): service.join(1, b'bad\0name', b'\xba\x03\0\2', roster)
        self.assertFalse(service.searching(1))
        service.join(1, b'Player', b'\xba\x03\0\2', roster)
        with self.assertRaises(ValueError): service.join(1, b'Player', b'\xba\x03\0\1', test_matchmaking.SurvivalQueueTests().roster())
        self.assertEqual(service.queue.tickets[1].actors, (1, 2))
        service.disconnected(1)
        self.assertFalse(service.searching(1))
