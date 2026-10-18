"""Permanent training registration, shared lobby changes and real match clocks."""
from unittest.mock import patch
import unittest

import test_training_arena as training
from server.battle_journal import BattleJournal
from tio.protocol.assault import encode_request, CREATE_ROOM, JOIN_ROOM, SET_READY, START_ROOM, DISBAND_ROOM


class OnDemandTests(training.TrainingArenaTests):
    # Reuse fixture/actions, not the scheduled-mode expectations.
    def setUp(self):
        super().setUp()
        self.hub.training_schedule='on_demand'

    def enter(self):
        self.register()
        return self.hub.battles[self.owners[0]]

    def test_pair_starts_immediately_with_full_battle_clock(self):
        before=self.fixture.now
        battle=self.enter()
        self.assertEqual(self.fixture.now,before)
        self.assertEqual(len(battle['humans']),8)
        self.assertEqual(battle['bots'],set())
        self.assertEqual(battle['training_ends'],before+900)
        self.assertTrue(battle['training_event']['on_demand'])
        self.assertEqual(battle['field'].scene_metadata['training_policy']['schedule'],'on_demand')

    def test_map_tooltip_preserves_training_state_for_every_base(self):
        from pathlib import Path
        from unittest.mock import Mock
        from server.contracts_service import ContractsService
        service=ContractsService.__new__(ContractsService)
        service.hub=self.hub;service.path=Path(self.path);service.clock=lambda:self.fixture.now
        service.contracts=Mock();service.contracts.catalog.return_value=[]
        for town in (19,20,21,22):
            expected=self.hub.training_town_packet(town)
            for _ in range(3):
                self.assertEqual(service.map_query(self.sessions[0],bytes((0x79,town))),(expected,))

    def test_registration_stays_open_across_old_pauses_and_days(self):
        event=self.hub._training_event(19)
        for seconds in (1800,3601,3901,7801,86401,604801):
            self.fixture.now=event['starts']+seconds
            current=self.hub._training_event(19)
            self.assertEqual((current['id'],current['phase'],current['phase_ends']),(event['id'],'REGISTRATION',0))
        battle=self.enter()
        self.assertEqual(battle['training_ends'],self.fixture.now+900)

    def test_one_ready_group_waits_for_second_group_without_bot(self):
        self.send(0,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[0])
        for i in (1,2,3):self.send(i,encode_request(JOIN_ROOM,group['id']))
        for i in range(4):self.send(i,encode_request(SET_READY,1))
        self.send(0,encode_request(START_ROOM))
        self.fixture.now+=86400;self.mono+=2;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertEqual(group['status'],'ready')

    def test_visitors_receive_creation_join_and_disband_lists(self):
        self.send(0,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[0])
        self.assertTrue(any(p[:2]==b'\xc8\x26' for p in self.hub.queues[self.owners[7]]))
        for q in self.hub.queues.values():q.clear()
        self.send(1,encode_request(JOIN_ROOM,group['id']))
        self.assertIn(self.hub._training_list(19),self.hub.queues[self.owners[7]])
        self.send(0,encode_request(DISBAND_ROOM))
        self.assertIn(b'\xc8\x26\0\0\0\0',self.hub.queues[self.owners[7]])

    def test_failed_birth_does_not_lose_groups_or_publish_a_field(self):
        with patch.object(self.hub,'send_scene',side_effect=ValueError('scene projection')):
            self.register()
        self.assertFalse(self.hub.battles)
        self.assertFalse(self.rows('battle_checkpoints'))
        self.assertEqual(len(self.hub.training_groups),2)
        self.assertTrue(all(not m['ready'] for g in self.hub.training_groups.values() for m in g['members'].values()))

    def test_recovery_preserves_deadline_without_reintroducing_schedule(self):
        battle=self.loaded()
        self.hub.disconnect(self.sessions[0])
        clone=training.TrainingHub(clock=lambda:self.mono);clone.init_training(self.path,wall=lambda:self.fixture.now)
        clone.journal=BattleJournal(clone,self.path,wall=lambda:self.fixture.now)
        self.assertEqual(clone.journal.recover(),[battle['match_id']])
        clone.recover_training_events()
        self.assertTrue(clone._training_event(19)['on_demand'])
        self.assertEqual(clone.battles[self.owners[0]]['training_ends'],battle['training_ends'])


# The inherited scheduled-only cases stay in test_training_arena. Run the
# remaining core admission/action/settlement cases against the on-demand mode.
for name in ('test_three_actual_tours_keep_cycles_separate_and_no_new_pairs_in_pause',
             'test_native_registration_eight_real_accounts_one_authoritative_scene',
             'test_native_zone_schedule_pushes_only_phase_changes_to_idle_accounts',
             'test_failed_pair_birth_rolls_back_field_and_clears_readiness',
             'test_crash_recover_same_score_map_tour_deadline_and_native_reconnect_flags'):
    setattr(OnDemandTests,name,None)


if __name__=='__main__':unittest.main()
