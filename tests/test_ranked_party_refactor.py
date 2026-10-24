"""Behavioural regressions for party state, failures and roster projection."""
from dataclasses import replace
import unittest
from unittest.mock import patch

from server import ranked_party
from tio.owned_pets import OwnedPetStore
import test_ranked_party as fixture
from test_ranked_squads import join


class RankedPartyRefactorTests(unittest.TestCase):
    setUp = fixture.RankedPartyTests.setUp
    send = fixture.RankedPartyTests.send
    request = fixture.RankedPartyTests.request
    accept = fixture.RankedPartyTests.accept

    def test_party_state_exists_before_first_packet(self):
        self.assertEqual(self.hub.ranked_parties, {})
        self.assertEqual(self.hub.ranked_invitations, {})

    def test_refresh_reads_each_members_roster_once(self):
        self.accept()
        self.case.now = 3
        self.accept(0, 2)
        self.case.now = 6
        self.accept(0, 3)
        reads = []
        original = OwnedPetStore.list

        def read(store, account):
            reads.append(account)
            return original(store, account)

        group = ranked_party.party(self.hub, self.owners[0])
        with patch.object(OwnedPetStore, 'list', read):
            ranked_party.notify(self.hub, group)
        self.assertCountEqual(reads, ['alice', 'bob', 'carol', 'dave'])
        for owner in self.owners:
            self.assertTrue(any(packet[:2] == b'\xc6\x36'
                                for packet in self.hub.queues[owner]))

    def test_internal_value_error_is_not_sent_as_player_rejection(self):
        with patch.object(OwnedPetStore, 'list', side_effect=ValueError('internal bug')):
            with self.assertRaisesRegex(ValueError, 'internal bug'):
                ranked_party.handle(self.hub, self.owners[0], b'\xc6\x38')

    def test_rejected_nonleader_submission_keeps_committed_ticket(self):
        self.accept()
        self.send(0, join((1,)))
        self.send(1, join((1,)))
        owner = self.owners[1]
        group = ranked_party.party(self.hub, owner)
        previous = group.tickets[owner]
        changed = replace(previous, joined_at=previous.joined_at + 1)
        with self.assertRaises(ValueError):
            ranked_party.submit(self.hub, owner, changed)
        self.assertIs(group.tickets[owner], previous)
        self.assertFalse(self.hub.ranked_waiting)

    def test_invitation_cooldown_is_not_written_to_session(self):
        self.request()
        self.assertFalse(hasattr(self.case.sessions[0], 'ranked_invite_after'))

    def test_bad_packet_does_not_consume_pending_invitation(self):
        self.request()
        self.send(1, b'\xc6\x37\x02')
        self.assertEqual(self.hub.ranked_invitations[self.owners[1]], self.owners[0])
        self.send(1, b'\xc6\x37\x01')
        self.assertIs(ranked_party.party(self.hub, self.owners[0]),
                      ranked_party.party(self.hub, self.owners[1]))

    def test_ranked_entry_does_not_mask_party_internal_errors(self):
        self.accept()
        self.send(0, join((1,)))
        self.send(1, join((1,)))
        group = ranked_party.party(self.hub, self.owners[0])
        before = dict(group.tickets)
        with patch.object(self.hub.ranked_party_service, 'read_roster',
                          side_effect=ValueError('internal party bug')):
            with self.assertRaisesRegex(ValueError, 'internal party bug'):
                self.hub.handle_ranked(self.owners[0], join((1,)))
        self.assertEqual(group.tickets, before)

    def test_disconnect_removes_departed_owners_cooldown(self):
        self.request()
        self.hub.disconnect(self.case.sessions[0])
        self.assertNotIn(self.owners[0], self.hub.ranked_party_service.invite_after)

    def test_leaving_group_does_not_bypass_invitation_cooldown(self):
        self.request()
        self.send(1, b'\xc6\x37\x00')
        self.send(0, b'\xc6\x33')
        replies = self.send(0, b'\xc6\x32carol\0\0\0')
        self.assertTrue(any(packet[:1] == b'\xf0' for packet in replies))
        self.assertNotIn(self.owners[2], self.hub.ranked_invitations)
        self.case.now = 3
        self.request(0, 2)
