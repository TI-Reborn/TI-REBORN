"""Authoritative Survival admission for 2-4 independent queued identities."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from tio.battle_modes import mode_rules
from tio.matchmaking import MatchProposal, SurvivalQueue
from tio.protocol.pet_info import decode_pet_info, encode_pet_info, PetInfo


class SurvivalMultiplayerQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=json.loads((Path(__file__).resolve().parents[1]/'evidence/owned_pet_trial.json').read_text())
        cls.template=decode_pet_info(bytes.fromhex(source['packet_hex']),human_equipment=True)

    def setUp(self):
        self.now=0
        self.queue=SurvivalQueue(clock=lambda:self.now,group_wait=3)

    def roster(self, count=1, level=1):
        return tuple((i,encode_pet_info(PetInfo(True,{
            **self.template.fields,'0x8c43eb':i,'0x8c44a6':i,'0x8c4aef':level})),b'')
            for i in range(1,count+1))

    def join(self, identity, count=1, level=1, pool='starter', mode=0):
        return self.queue.join(identity,self.roster(count,level),pool=pool,mode=mode)

    def test_duel_waits_for_equal_squad_and_consumes_only_one_opponent(self):
        self.queue = SurvivalQueue(clock=lambda: self.now, duels=True)
        for count in (1, 2, 3):
            self.join(count, count)
        self.now = 10000
        for count in (1, 2, 3):
            self.assertIsNone(self.queue.propose(count))
        self.join(4, 3, level=4)
        self.join(5, 3, pool='other')
        self.assertIsNone(self.queue.propose(3))
        for count in (1, 2, 3):
            opponent = self.join(10 + count, count)
            self.join(20 + count, count)
            proposal = self.queue.propose(count)
            self.assertEqual(proposal.members, (self.queue.tickets[count], opponent))
            self.assertEqual(proposal.soldiers, count)
            self.queue.consume(proposal)
        self.assertEqual(set(self.queue.tickets), {4, 5, 21, 22, 23})

    def test_duel_consume_rejects_mixed_squads_and_third_player(self):
        self.queue = SurvivalQueue(clock=lambda: self.now, duels=True)
        first = self.join(1, 3)
        smaller = self.join(2, 2)
        second = self.join(3, 3)
        third = self.join(4, 3)
        for proposal in (MatchProposal(first, smaller), MatchProposal(first, second, (first, second, third)),
                         MatchProposal(first, None)):
            with self.assertRaisesRegex(ValueError, 'Incompatible'):
                self.queue.consume(proposal)
        self.assertEqual(set(self.queue.tickets), {1, 2, 3, 4})

    def test_pair_and_three_players_get_bounded_collection_window(self):
        self.join(10,3)
        self.now=1
        self.join(20,2)
        self.assertIsNone(self.queue.propose(10))
        self.now=2
        self.join(30,2)
        self.now=2.999
        self.assertIsNone(self.queue.propose(30))
        self.now=3
        proposal=self.queue.propose(10)
        self.assertEqual(tuple(t.character_id for t in proposal.members),(10,20,30))
        self.assertEqual(proposal.soldiers,2)
        self.assertEqual(proposal.first.actors,(1,2,3))
        self.assertFalse(proposal.uses_bot)
        self.queue.consume(proposal)
        self.assertFalse(self.queue.tickets)

    def test_four_players_start_immediately_and_keep_independent_sides(self):
        for owner in (1,2,3,4):self.join(owner,3)
        proposal=self.queue.propose(1)
        self.assertEqual(tuple(t.character_id for t in proposal.members),(1,2,3,4))
        self.assertEqual(proposal.soldiers,3)
        self.assertIs(proposal.second,proposal.members[1])
        self.queue.consume(proposal)
        self.assertFalse(self.queue.tickets)

    def test_lone_player_gets_bot_after_minute_but_real_opponent_has_priority(self):
        self.join(1)
        self.now=10_000
        self.assertTrue(self.queue.propose(1).uses_bot)
        self.join(2)
        proposal=self.queue.propose(2)
        self.assertEqual(len(proposal.members),2)
        self.assertFalse(proposal.uses_bot)

    def test_band_and_city_pool_remain_strict_for_four_player_search(self):
        self.join(1,level=3)
        self.join(2,level=4)
        self.join(3,level=3,pool='other')
        self.join(4,level=2)
        self.join(5,level=1)
        self.join(6,level=3)
        proposal=self.queue.propose(1)
        self.assertEqual(tuple(t.character_id for t in proposal.members),(1,4,5,6))
        self.queue.consume(proposal)
        self.assertEqual(set(self.queue.tickets),{2,3})

    def test_larger_common_squad_has_priority_over_more_small_squads(self):
        self.join(1,3)
        self.join(2,1)
        self.join(3,2)
        self.join(4,3)
        self.assertIsNone(self.queue.propose(1))
        self.now=3
        proposal=self.queue.propose(1)
        self.assertEqual(tuple(t.character_id for t in proposal.members),(1,4))
        self.assertEqual(proposal.soldiers,3)
        # With a one-actor requester all four squads have a common prefix.
        proposal=self.queue.propose(2)
        self.assertEqual(len(proposal.members),4)
        self.assertEqual(proposal.soldiers,1)

    def test_fifo_and_identity_tiebreak_limit_group_to_four(self):
        for owner in (99,4,3,2,1):self.join(owner)
        proposal=self.queue.propose(99)
        self.assertEqual(tuple(t.character_id for t in proposal.members),(99,1,2,3))
        self.queue.consume(proposal)
        self.assertEqual(set(self.queue.tickets),{4})

    def test_cancellation_or_rejoin_makes_whole_proposal_stale(self):
        for count in (3,4):
            with self.subTest(players=count):
                self.queue=SurvivalQueue(clock=lambda:self.now,group_wait=0)
                for owner in range(1,count+1):self.join(owner)
                proposal=self.queue.propose(1)
                self.queue.cancel(count)
                self.join(count)
                before=dict(self.queue.tickets)
                with self.assertRaisesRegex(ValueError,'Stale'):
                    self.queue.consume(proposal)
                self.assertEqual(self.queue.tickets,before)
                self.queue.consume(self.queue.propose(1))
                self.assertFalse(self.queue.tickets)

    def test_failed_scene_preparation_and_repeated_proposal_do_not_consume(self):
        for owner in (1,2,3,4):self.join(owner)
        proposal=self.queue.propose(1)
        before=dict(self.queue.tickets)
        self.assertEqual(self.queue.propose(1),proposal)
        self.assertEqual(self.queue.tickets,before)
        self.queue.consume(proposal)
        with self.assertRaisesRegex(ValueError,'Stale'):self.queue.consume(proposal)

    def test_rejects_forged_incompatible_or_duplicate_group_atomically(self):
        first=self.join(1)
        second=self.join(2)
        different=self.join(3,pool='other')
        before=dict(self.queue.tickets)
        proposal=MatchProposal(first,second,(first,second,different))
        with self.assertRaisesRegex(ValueError,'Incompatible'):self.queue.consume(proposal)
        self.assertEqual(self.queue.tickets,before)
        with self.assertRaisesRegex(ValueError,'Invalid match'):
            MatchProposal(first,second,(first,second,replace(second)))
        with self.assertRaises(ValueError):self.queue.consume(MatchProposal(first,None))
        self.assertEqual(self.queue.tickets,before)

    def test_legacy_pair_constructor_and_non_survival_training_still_work(self):
        first=self.join(1)
        second=self.join(2)
        pair=MatchProposal(first,second)
        self.assertEqual(pair.members,(first,second))
        self.queue.consume(pair)
        training=self.join(10,3,mode=1)
        self.now=5
        proposal=self.queue.propose(10)
        self.assertEqual(proposal.members,(training,))
        self.assertTrue(proposal.uses_bot)
        self.queue.consume(proposal)

    def test_player_limits_and_invalid_collection_policy(self):
        survival=mode_rules(0)
        self.assertEqual((survival.players,survival.min_players,survival.max_players),(2,2,4))
        for count in (2,3,4):survival.validate_players(count)
        for count in (0,1,5,True):
            with self.assertRaises(ValueError):survival.validate_players(count)
        for delay in (-1,float('inf'),float('nan'),True,'3'):
            with self.assertRaises(ValueError):SurvivalQueue(group_wait=delay)


if __name__=='__main__':unittest.main()
