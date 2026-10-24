"""Party rules execute without sockets, databases or the arena hub."""
import unittest

from tio.matchmaking import SearchTicket
from tio.ranked_party import (
    MAX_FIGHTERS, Party, RankedRejection, allocation, can_join,
    closed_invitations, is_ranked_level, matchmaking_units, submission,
    validate_miner_count,
)


class PartyRuleTests(unittest.TestCase):
    def test_full_allocations_reject_another_member(self):
        with self.assertRaises(RankedRejection):
            can_join(2, MAX_FIGHTERS)

    def test_last_available_slot_accepts_one_member(self):
        can_join(3, MAX_FIGHTERS - 1)

    def test_allocation_keeps_original_slots_unchanged(self):
        group = Party(1, [1, 2], {1: 1, 2: 1})
        self.assertEqual(allocation(group, 1, 2, 3), {1: 1, 2: 3})
        self.assertEqual(group.slots, {1: 1, 2: 1})

    def test_member_cannot_allocate_leaders_slots(self):
        with self.assertRaises(RankedRejection):
            allocation(Party(1, [1, 2], {1: 1, 2: 1}), 2, 1, 2)

    def test_ranked_level_boundaries(self):
        self.assertEqual([is_ranked_level(level) for level in (3, 4, 20, 21)],
                         [False, True, True, False])

    def test_single_miner_is_allowed_but_two_are_rejected(self):
        validate_miner_count(1)
        with self.assertRaises(RankedRejection):
            validate_miner_count(2)

    def test_declining_removes_target_and_departed_sender_leaves_tombstone(self):
        self.assertEqual(closed_invitations({2: 1, 3: 2, 4: 5}, 2),
                         {3: 0, 4: 5})

    def test_first_readiness_does_not_start_search_or_mutate_tickets(self):
        group = Party(1, [1, 2], {1: 1, 2: 1})
        ticket = SearchTicket(1, (1,), (4,), 0)
        proposed, start = submission(group, 1, ticket)
        self.assertEqual(proposed, {1: ticket})
        self.assertFalse(start)
        self.assertFalse(group.tickets)

    def test_mixed_level_bands_cannot_start_search(self):
        first = SearchTicket(1, (1,), (4,), 0)
        second = SearchTicket(2, (1,), (7,), 0)
        group = Party(1, [1, 2], {1: 1, 2: 1}, {1: first, 2: second})
        with self.assertRaises(RankedRejection):
            submission(group, 1, first)
        self.assertEqual(group.tickets, {1: first, 2: second})

    def test_incomplete_party_is_never_exposed_as_a_solo_unit(self):
        ticket = SearchTicket(1, (1,), (4,), 0)
        group = Party(1, [1, 2], {1: 1, 2: 1})
        self.assertEqual(matchmaking_units({1: group, 2: group}, [ticket]), [])

    def test_party_unit_preserves_both_real_tickets_and_oldest_join(self):
        first = SearchTicket(1, (1,), (4,), 5)
        second = SearchTicket(2, (1,), (4,), 3)
        group = Party(1, [1, 2], {1: 1, 2: 1})
        units = matchmaking_units({1: group, 2: group}, [first, second])
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].members, (first, second))
        self.assertEqual(units[0].joined_at, 3)
