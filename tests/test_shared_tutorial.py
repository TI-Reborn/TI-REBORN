from contextlib import closing
from dataclasses import replace
import json,random,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server.accounts import Accounts
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from server.tutorial_arena import TutorialArena
from tio.characters import CharacterStore
from tio.db_transaction import transaction
from tio.onboarding import initialize_created,prepare,pending
from tio.roster_progression import tutorial_status
from tio.arena_service import ArenaService
from tio.survival_service import SurvivalService
from tio.locations import LocationStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import decode_item_list
from tio.protocol.quest_ack import decode_ack


class Hub(TeamArena):pass


class Session(SimpleNamespace):
    __hash__=object.__hash__
    __eq__=object.__eq__
    def stop(self):self.closed=True


class TutorialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.sqlite3';self.now=0;self.wall=1000
        accounts=Accounts(self.path)
        for name in ('alice','bob','legacy'):accounts.create(name,'StrongPassword-123')
        self.store=CharacterStore(self.path);self.hub=self.new_hub()
        self.sessions={name:self.session(name) for name in ('alice','bob','legacy')}

    def new_hub(self):
        hub=Hub(clock=lambda:self.now);hub.journal=BattleJournal(hub,self.path,wall=lambda:self.wall)
        return hub

    def session(self,name):
        return Session(account=name,database=self.path,probe_character_id=1,probe_character_name=name.capitalize().encode(),
            arena=ArenaService(clock=lambda:self.now),survival=SurvivalService(),locations=LocationStore(self.path),closed=False)

    def create(self,name):
        # Same outer unit as the pending CharacterStore integration diff.
        with transaction(self.path):
            self.store.create(name,CharacterCreateRequest(name.capitalize().encode(),0,(1,0,0,0)))
            result=initialize_created(self.path,name)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE character_onboarding SET completed=1 WHERE account=?',(name,))
        return result

    def profile(self,name):
        with closing(sqlite3.connect(self.path)) as db,db:
            return (db.execute('SELECT * FROM owned_pets WHERE account=? ORDER BY pet_id',(name,)).fetchall(),
                db.execute('SELECT * FROM wallets WHERE account=?',(name,)).fetchall())

    def rewards(self):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT * FROM battle_rewards').fetchall() if db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone() else []

    def send(self,name,packet):
        session=self.sessions[name];self.assertTrue(self.hub.handle(session,packet))
        owner=self.hub.identities[session];packets=tuple(self.hub.queues[owner]);self.hub.queues[owner].clear();return packets

    def start(self,name='alice',*,replay=False):
        battle=self.hub.start_tutorial(self.sessions[name],replay=replay)
        battle['field'].combat.rng=random.Random(7)
        self.send(name,b'\x36');self.hub.tick();return battle

    def move(self,battle,name='alice'):
        actor=battle['field'].actor(battle['tutorial_player'])
        return self.send(name,encode_move_request(BattleMove(actor.actor_id,((actor.x,actor.y+1),))))

    def defeat(self,battle,name='alice'):
        replies=[]
        for attempt in range(100):
            if battle['finished'] or battle['field'].actor(battle['tutorial_target']).health==0:return tuple(replies)
            player=battle['field'].actor(battle['tutorial_player']);target=battle['field'].actor(battle['tutorial_target'])
            if player.action_points<3:
                self.send(name,encode_end_turn());self.hub.tick();continue
            replies.extend(self.send(name,encode_attack_request(AttackRequest(player.actor_id,target.x,target.y))))
        self.fail('Tutorial target could not be defeated by real accepted attacks')

    def test_creation_exactly_two_starters_atomic_once_and_prepare_no_backfill(self):
        self.assertEqual(self.create('alice'),(2,3));self.assertEqual([r[0] for r in OwnedPetStore(self.path).list('alice')],[1,2,3])
        before=self.profile('alice')
        with transaction(self.path):self.assertEqual(initialize_created(self.path,'alice'),(2,3))
        prepare(self.path,'alice');self.assertEqual(self.profile('alice'),before)
        self.store.create('legacy',CharacterCreateRequest(b'Legacy',0,(0,0,0,0)));prepare(self.path,'legacy')
        self.assertEqual(len(OwnedPetStore(self.path).list('legacy')),1);self.assertIsNone(tutorial_status(self.path,'legacy'))
        with self.assertRaises(ValueError):initialize_created(self.path,'bob')

    def test_creation_fault_rolls_back_character_wallet_main_starters_tutorial(self):
        OwnedPetStore(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("CREATE TRIGGER fail_new_third BEFORE INSERT ON owned_pets WHEN NEW.account='bob' AND NEW.pet_id=3 BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.create('bob')
        with closing(sqlite3.connect(self.path)) as db,db:
            self.assertFalse(db.execute("SELECT 1 FROM characters WHERE account='bob'").fetchone())
            self.assertFalse(db.execute("SELECT 1 FROM owned_pets WHERE account='bob'").fetchone())
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='wallets'").fetchone():self.assertFalse(db.execute("SELECT 1 FROM wallets WHERE account='bob'").fetchone())
        self.assertIsNone(tutorial_status(self.path,'bob'))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('DROP TRIGGER fail_new_third')
        self.assertEqual(self.create('bob'),(2,3))

    def test_two_real_accounts_have_isolated_authoritative_tutorial_scenes(self):
        for name in ('alice','bob'):self.create(name)
        a=self.start('alice');b=self.start('bob')
        self.assertIsNot(a,b);self.assertNotEqual(a['match_id'],b['match_id']);self.assertEqual(a['field'].combat.persistence,{})
        self.hub.queues[self.hub.identities[self.sessions['bob']]].clear()
        packets=self.move(a);self.assertTrue(any(p[0]==0x3d for p in packets))
        self.assertFalse(self.hub.queues[self.hub.identities[self.sessions['bob']]])
        self.assertEqual(tutorial_status(self.path,'alice')['observed_events'],1)
        self.assertEqual(tutorial_status(self.path,'bob')['observed_events'],0)
        self.assertEqual(a['field'].actor(a['tutorial_target']).health,10)

    def test_native_move_attack_endturn_kill_finish_and_profile_preserved(self):
        self.create('alice');before=self.profile('alice');battle=self.start()
        self.move(battle);self.send('alice',encode_end_turn());self.hub.tick();replies=self.defeat(battle)
        self.assertTrue(battle['finished']);self.assertTrue(tutorial_status(self.path,'alice')['completed'])
        self.assertEqual(tutorial_status(self.path,'alice')['observed_events'],15)
        self.assertEqual(self.profile('alice'),before);self.assertEqual(self.rewards(),[])
        owner=self.hub.identities[self.sessions['alice']]
        self.assertTrue(any(p[0]==0x4c for p in replies))
        self.send('alice',b'\x2a\x01');self.assertFalse(self.hub.busy(self.sessions['alice']))
        self.assertIsNone(self.sessions['alice']._battle_treatment_ids)

    def test_early_kill_does_not_fake_endturn_or_leave_mission_stuck(self):
        self.create('alice');battle=self.start();self.defeat(battle)
        self.assertFalse(battle['finished']);self.assertFalse(tutorial_status(self.path,'alice')['completed'])
        self.move(battle);self.send('alice',encode_end_turn())
        self.assertTrue(battle['finished']);self.assertEqual(tutorial_status(self.path,'alice')['observed_events'],15)

    def test_original_dialogues_load_once_and_follow_authoritative_actions(self):
        self.create('alice');self.create('bob')
        a=self.hub.start_tutorial(self.sessions['alice'])
        b=self.hub.start_tutorial(self.sessions['bob'])
        ids=lambda packets:[decode_ack(p) for p in packets if p[:2]==b'\xb8\x10']
        alice=self.hub.identities[self.sessions['alice']];bob=self.hub.identities[self.sessions['bob']]
        self.assertEqual(ids(self.hub.queues[alice]),[])
        self.assertEqual(ids(self.send('alice',b'\x36')),[1000,1002])
        self.assertEqual(ids(self.hub.queues[bob]),[])
        self.assertEqual(ids(self.send('bob',b'\x36')),[1000,1002])
        self.hub.tick()
        self.assertEqual(ids(self.send('alice',b'\x36')),[])
        self.assertEqual(ids(self.move(a)),[1111,1004])
        self.assertEqual(b['tutorial_events'],0)
        self.hub.send_scene(alice,reconnect=True)
        self.assertEqual(ids(self.send('alice',b'\x36')),[1004])
        self.assertEqual(a['tutorial_events'],1)
        self.send('alice',encode_end_turn());self.hub.tick()
        replies=self.defeat(a)
        self.assertIn(1018,ids(replies))
        self.assertEqual(self.rewards(),[])

    def test_rejected_foreign_move_or_attack_advances_no_progress(self):
        self.create('alice');battle=self.start();before=tutorial_status(self.path,'alice')
        target=battle['field'].actor(battle['tutorial_target'])
        replies=self.send('alice',encode_move_request(BattleMove(target.actor_id,((target.x,target.y+1),))))
        self.assertTrue(any(p[0]==0xf0 for p in replies));self.assertEqual(tutorial_status(self.path,'alice'),before)
        replies=self.send('alice',encode_attack_request(AttackRequest(target.actor_id,target.x,target.y)))
        self.assertTrue(any(p[0]==0xf0 for p in replies));self.assertEqual(tutorial_status(self.path,'alice'),before)

    def test_early_leave_preserves_facts_then_continuation_not_replay(self):
        self.create('alice');before=self.profile('alice');battle=self.start();self.move(battle)
        self.send('alice',b'\x2a\x01');state=tutorial_status(self.path,'alice')
        self.assertEqual((state['step'],state['match_id'],state['completed']),(1,None,False))
        self.assertTrue(self.hub.tutorial_command(self.sessions['alice'],'/tutorial'))
        next_battle=self.hub.battles[self.hub.identities[self.sessions['alice']]]
        self.assertFalse(next_battle['tutorial_replay']);self.assertNotEqual(next_battle['match_id'],battle['match_id'])
        self.assertEqual(next_battle['tutorial_events'],1);self.assertEqual(self.profile('alice'),before);self.assertEqual(self.rewards(),[])

    def test_verified_early_kill_survives_closed_attempt_without_second_kill(self):
        self.create('alice');battle=self.start();self.defeat(battle)
        self.send('alice',b'\x2a\x01')
        self.assertEqual(tutorial_status(self.path,'alice')['observed_events'],10)
        self.assertTrue(self.hub.tutorial_command(self.sessions['alice'],'/tutorial'))
        resumed=self.hub.battles[self.hub.identities[self.sessions['alice']]]
        self.assertEqual(resumed['field'].actor(resumed['tutorial_target']).health,0)
        self.send('alice',b'\x36');self.hub.tick();self.move(resumed);self.send('alice',encode_end_turn())
        self.assertTrue(resumed['finished']);self.assertTrue(tutorial_status(self.path,'alice')['completed'])
        self.assertEqual(self.rewards(),[])

    def test_birth_checkpoint_failure_rolls_back_owned_binding_and_scene(self):
        self.create('alice');before=self.profile('alice');session=self.sessions['alice']
        owner=self.hub.identity(session)
        with patch('server.battle_journal.store.save',side_effect=sqlite3.IntegrityError('injected')):
            with self.assertRaises(sqlite3.IntegrityError):self.hub.start_tutorial(session)
        self.assertNotIn(owner,self.hub.battles);self.assertFalse(self.hub.queues[owner])
        self.assertIsNone(tutorial_status(self.path,'alice')['match_id'])
        self.assertEqual(self.profile('alice'),before)

    def test_disconnect_reconnect_and_process_restart_use_same_field_inventory_progress(self):
        self.create('alice');battle=self.start();self.move(battle)
        match=battle['match_id'];owner=self.hub.identities[self.sessions['alice']]
        position=(battle['field'].actor(battle['tutorial_player']).x,battle['field'].actor(battle['tutorial_player']).y)
        inventory=battle['field'].combat.inventories[battle['tutorial_player']]
        self.hub.disconnect(self.sessions['alice']);self.now=5;self.wall=1005
        self.hub=self.new_hub();self.assertIn(match,self.hub.journal.recover())
        self.sessions['alice']=self.session('alice');self.assertTrue(self.hub.resume(self.sessions['alice']))
        restored=self.hub.battles[owner];self.assertEqual(restored['match_id'],match)
        actor=restored['field'].actor(restored['tutorial_player']);self.assertEqual((actor.x,actor.y),position)
        self.assertEqual(restored['field'].combat.inventories[actor.actor_id],inventory)
        self.assertEqual(restored['tutorial_events'],1);self.send('alice',b'\x36')
        self.assertFalse(self.hub.returning)

    def test_expired_disconnect_and_shutdown_create_no_rewards_and_release_binding(self):
        for name in ('alice','bob'):self.create(name)
        before={name:self.profile(name) for name in ('alice','bob')}
        self.start('alice');self.hub.disconnect(self.sessions['alice']);self.now=181;self.hub.tick()
        self.assertIsNone(tutorial_status(self.path,'alice')['match_id'])
        self.start('bob');self.hub.shutdown_battles()
        self.assertEqual(self.rewards(),[])
        for name in ('alice','bob'):self.assertEqual(self.profile(name),before[name]);self.assertIsNone(tutorial_status(self.path,name)['match_id'])

    def test_explicit_replay_for_old_save_has_no_backfill_or_fresh_state(self):
        self.store.create('legacy',CharacterCreateRequest(b'Legacy',0,(0,0,0,0)));prepare(self.path,'legacy')
        before=self.profile('legacy');self.assertFalse(self.hub.tutorial_auto(self.sessions['legacy']))
        self.assertTrue(self.hub.tutorial_command(self.sessions['legacy'],'/tutorial'))
        self.assertIsNone(tutorial_status(self.path,'legacy'));self.send('legacy',b'\x36');self.hub.tick()
        battle=self.hub.battles[self.hub.identities[self.sessions['legacy']]]
        self.move(battle,'legacy');self.send('legacy',encode_end_turn());self.hub.tick();self.defeat(battle,'legacy')
        self.assertTrue(battle['finished']);self.assertIsNone(tutorial_status(self.path,'legacy'))
        self.assertEqual(self.profile('legacy'),before);self.assertEqual(self.rewards(),[])

    def test_action_progress_failure_rolls_back_scene_ap_inventory_and_packets(self):
        self.create('alice');battle=self.start();owner=self.hub.identities[self.sessions['alice']]
        self.hub.queues[owner].clear();before=dict(battle['field']._actors)
        actor=battle['field'].actor(battle['tutorial_player'])
        request=encode_move_request(BattleMove(actor.actor_id,((actor.x,actor.y+1),)))
        with patch('server.tutorial_arena.tutorial_progress',side_effect=sqlite3.IntegrityError('injected')):
            with self.assertRaises(sqlite3.IntegrityError):self.hub.perform_action(battle,owner,request)
        self.assertEqual(battle['field']._actors,before);self.assertEqual(tutorial_status(self.path,'alice')['observed_events'],0)
        self.assertFalse(self.hub.queues[owner])

    def test_automatic_start_waits_for_appearance_and_ordinary_battle_handlers_unchanged(self):
        self.create('alice')
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE character_onboarding SET completed=0 WHERE account='alice'")
        self.assertTrue(pending(self.path,'alice'));self.assertFalse(self.hub.tutorial_auto(self.sessions['alice']))
        with closing(sqlite3.connect(self.path)) as db,db:db.execute("UPDATE character_onboarding SET completed=1 WHERE account='alice'")
        self.assertTrue(self.hub.tutorial_auto(self.sessions['alice']))
        battle=self.hub.battles[self.hub.identities[self.sessions['alice']]]
        with patch.object(TeamArena,'perform_action',return_value='ordinary') as original:
            self.assertEqual(self.hub.perform_action({'kind':'ordinary'},1,b'\x3c'),'ordinary');original.assert_called_once()
        self.assertEqual(battle['kind'],'tutorial')


if __name__=='__main__':unittest.main()
