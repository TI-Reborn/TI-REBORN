"""Offline evidence for future native Contracts integration, not gameplay tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from contracts_native_probe import party_writer, party_states, quest_state, zone_visibility


class ContractsNativeResearchTests(unittest.TestCase):
    def test_original_party_writers_keep_distinct_semantics(self):
        self.assertEqual(party_writer(0x7f6f40), bytes.fromhex("c633"))
        self.assertEqual(party_writer(0x7f6efc, owner=0x12345678, slots=2),
                         bytes.fromhex("c6347856341202"))
        self.assertEqual(party_writer(0x7f6f6c, nonce=0x123456789abcdef0),
                         bytes.fromhex("c665f0debc9a78563412"))
        self.assertEqual(party_writer(0x7f71cc, accepted=1, nonce=0x123456789abcdef0),
                         bytes.fromhex("c66301f0debc9a78563412"))

    def test_party_is_player_members_with_nested_mercenaries(self):
        members = ((17, 2, 2, (1, 2)), (18, 1, 1, (6,)))
        self.assertEqual(party_states(17, members),
                         dict(i_am_ready=True, we_all_ready=False, my_slots=2, have_freak=True))
        self.assertEqual(party_states(18, members),
                         dict(i_am_ready=False, we_all_ready=False, my_slots=1, have_freak=True))
        self.assertEqual(party_states(19, members),
                         dict(i_am_ready=False, we_all_ready=False, my_slots=0, have_freak=True))

    def test_empty_party_never_reports_all_ready(self):
        self.assertFalse(party_states(17, ())['we_all_ready'])
        self.assertTrue(party_states(17, ((17, 2, 1, (1,)), (18, 2, 1, (1,))))['we_all_ready'])

    def test_quest_state_consumes_both_nested_lists_and_relative_timers(self):
        result = quest_state((991, 0x123456789abcdef0, 3, 60, 1, 90, 255, 0xffffffff),
                             ((10, 2, 1), (11, 3, 0)), ((12, 4, 1),), now_ms=42000)
        self.assertEqual(result['consumed'], result['expected_bytes'])
        self.assertEqual(result['state'], 3)
        self.assertEqual((result['deadline1'], result['deadline2']), (102, 132))

    def test_extra_contiguous_zone_ids_have_native_visibility_gates(self):
        for zone in (18, 19, 20):
            for enabled in (0, 1):
                with self.subTest(zone=zone, enabled=enabled):
                    result = zone_visibility(zone, enabled)
                    self.assertEqual(result['lookup'], zone)
                    self.assertEqual(result['enabled'], enabled)
                    self.assertEqual(result['consumed'], result['expected_bytes'])


if __name__ == '__main__':
    unittest.main()
