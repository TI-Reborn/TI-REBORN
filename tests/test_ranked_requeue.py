"""A repeated TrueSkill "Continue" updates the queued squad instead of dropping it."""
import unittest

import test_ranked_bots as fixture
from test_ranked_squads import join

CANCELLED = b'\xc6\x06'


class RankedRequeueTests(unittest.TestCase):
    setUp = fixture.RankedBotsTests.setUp

    def owner(self, index):
        return self.hub.identities[self.case.sessions[index]]

    def test_changed_selection_replaces_ticket_and_keeps_queue_position(self):
        self.case.send(0, join((1,)))
        first = self.hub.ranked_waiting[self.owner(0)]
        self.case.now += 30
        replies = self.case.send(0, join((2,)))
        self.assertFalse([p for p in replies if p[0] == 0xf0], replies)
        self.assertNotIn(CANCELLED, replies)
        ticket = self.hub.ranked_waiting[self.owner(0)]
        self.assertEqual((ticket.actors, ticket.joined_at), ((2,), first.joined_at))

    def test_opponent_after_a_changed_selection_starts_with_the_latest_squad(self):
        self.case.send(0, join((1,)))
        self.case.send(0, join((1, 2)))
        self.case.send(1, join((1,)))
        battle = self.hub.battles[self.owner(0)]
        self.assertIs(battle, self.hub.battles[self.owner(1)])
        self.assertEqual(len(battle['field'].actor_ids(self.owner(0))), 2)
        self.assertFalse(self.hub.ranked_waiting)

    def test_identical_repeat_is_harmless(self):
        self.case.send(0, join((1,)))
        before = dict(self.hub.ranked_waiting)
        replies = self.case.send(0, join((1,)))
        self.assertNotIn(CANCELLED, replies)
        self.assertEqual(self.hub.ranked_waiting, before)

    def test_invalid_repeat_still_cancels_with_an_explicit_reason(self):
        self.case.send(0, join((1,)))
        replies = self.case.send(0, join((99,)))
        self.assertTrue([p for p in replies if p[0] == 0xf0])
        self.assertIn(CANCELLED, replies)
        self.assertFalse(self.hub.ranked_waiting)

    def test_unmatched_search_is_logged_with_skip_reasons(self):
        with self.assertLogs('tio.server', level='INFO') as logs:
            self.case.send(0, join((1,)))
        self.assertTrue(any('ranked_search_waiting' in line for line in logs.output), logs.output)


if __name__ == '__main__':
    unittest.main()
