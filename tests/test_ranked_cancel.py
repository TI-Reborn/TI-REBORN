"""Cancel a native search without cancelling an already matched battle."""
import unittest
from unittest.mock import patch

import test_ranked as fixture


class RankedCancelTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.RankedServerTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.case = self.base.case
        self.hub = self.base.hub
        self.owner = self.hub.identity(self.case.sessions[0])

    def test_opening_selector_idle_cancel_does_not_reset_native_selection(self):
        # ShowTrueSkillWindow sends C6/23 before requesting C6/20. A spurious
        # C6/06 invokes 9537a8 -> 9e58a8 and clears the selected fighters.
        self.assertFalse(self.case.send(0, b'\xc6\x23'))
        self.assertFalse(self.hub.busy(self.case.sessions[0]))

    def test_cancel_releases_queue_and_retry_cancels_again(self):
        for _ in range(3):
            self.case.send(0, fixture.join_packet())
            self.assertTrue(self.hub.busy(self.case.sessions[0]))
            replies = self.case.send(0, b'\xc6\x23')
            self.assertIn(b'\xc6\x06', replies)
            self.assertFalse(any(p[:1] == b'\xf0' for p in replies))
            self.assertNotIn(self.owner, self.hub.ranked_waiting)
            self.assertFalse(self.hub.busy(self.case.sessions[0]))
            self.assertFalse(self.case.send(0, b'\xc6\x23'))

    def test_cancelled_account_is_not_matched_to_next_account(self):
        self.case.send(0, fixture.join_packet())
        self.case.send(0, b'\xc6\x23')
        self.case.send(1, fixture.join_packet())
        other = self.hub.identities[self.case.sessions[1]]
        self.assertEqual(set(self.hub.ranked_waiting), {other})
        self.assertFalse(self.hub.battles)
        self.case.send(0, b'\xc6\x23')
        self.assertEqual(set(self.hub.ranked_waiting), {other})

    def test_cancel_after_match_does_not_forfeit_or_reset_battle(self):
        owners, battle = self.base.start(journal=True)
        before = (battle['match_id'], dict(battle['field']._actors))
        for i in (0, 1):
            replies = self.case.send(i, b'\xc6\x23')
            self.assertNotIn(b'\xc6\x06', replies)
            self.assertFalse(any(p[:1] == b'\xf0' for p in replies))
        self.assertFalse(battle['finished'])
        self.assertEqual(before, (battle['match_id'], dict(battle['field']._actors)))
        self.assertEqual(set(self.hub.battles), set(owners))

    def test_reserved_qa_search_does_not_match_an_ordinary_player(self):
        # Hosted verification must never drag a real player's queued squad
        # into a disposable test match. Use authenticated roots, not aliases.
        with patch('tio.character_identity.auth_account',
                   side_effect=lambda path, account: 'qt00000000a' if account == 'alice' else account):
            self.case.send(0, fixture.join_packet())
            self.case.send(1, fixture.join_packet())
        other = self.hub.identities[self.case.sessions[1]]
        self.assertFalse(self.hub.battles)
        self.assertEqual(set(self.hub.ranked_waiting), {self.owner, other})
        self.case.send(0, b'\xc6\x23')
        self.assertEqual(set(self.hub.ranked_waiting), {other})

    def test_two_reserved_qa_roots_can_match_each_other(self):
        with patch('tio.character_identity.auth_account',
                   side_effect=lambda path, account: {'alice': 'qt00000000a', 'bob': 'qt00000000b'}.get(account, account)):
            self.base.start()


if __name__ == '__main__':
    unittest.main()
