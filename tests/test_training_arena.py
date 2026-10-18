"""Candidate mixin against the real hub/native actions; no VPS/GUI claim."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
import unittest
from unittest.mock import Mock,patch

from server.training_arena import TrainingArena,AssaultMapLoader
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
from tio.arena_service import ArenaService
from tio.survival_service import SurvivalService
from tio.locations import LocationStore,center
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,SET_READY,START_ROOM,REQUEST_ROOMS
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_ground import decode_battle_ground
from tio.wallets import WalletStore
import test_territories as fixtures


class TrainingHub(TeamArena):pass
class Session:pass


class TrainingArenaTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TerritoriesTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path;self.mono=0
        self.hub=TrainingHub(clock=lambda:self.mono);self.hub.init_training(self.path,wall=lambda:self.fixture.now,schedule='scheduled')
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.fixture.now)
        self.sessions=[]
        for account in self.fixture.accounts[:8]:
            session=Session();session.account=account;session.database=self.path;session.probe_character_id=1
            session.probe_character_name=account.encode();session.locations=LocationStore(self.path,clock=lambda:self.fixture.now)
            session.arena=ArenaService();session.survival=SurvivalService();session.stop=Mock()
            WalletStore(self.path).ensure(account)
            with closing(sqlite3.connect(self.path)) as db,db:
                LocationStore._save(db,account,19,*center(19))
                raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(account,)).fetchone()[0]
                f=decode_pet_info(raw,human_equipment=True)
                raw=encode_pet_info(replace(f,fields={**f.fields,'0x8c44a6':1}))
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(raw,account))
            self.hub.identity(session);self.sessions.append(session)
        self.owners=tuple(self.hub.identities[s] for s in self.sessions)

    def send(self,index,packet):
        self.assertTrue(self.hub.handle(self.sessions[index],packet))
        owner=self.owners[index];packets=tuple(self.hub.queues[owner]);self.hub.queues[owner].clear()
        return packets

    def rows(self,table):
        with closing(sqlite3.connect(self.path)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():return []
            return list(db.execute('SELECT * FROM '+table))

    def register(self):
        for offset in (0,4):
            self.send(offset,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[offset])
            for index in range(offset+1,offset+4):self.send(index,encode_request(JOIN_ROOM,group['id']))
            for index in range(offset,offset+4):self.send(index,encode_request(SET_READY,1))
            self.send(offset,encode_request(START_ROOM))

    def tour(self,number=1):
        event=self.hub._training_event(19);rules=event['rules']
        self.fixture.now=event['starts']+rules['registration_seconds']+(number-1)*(rules['tour_seconds']+rules['pause_seconds'])+1
        self.mono+=2;self.hub.tick()

    def enter(self):
        self.register();self.assertFalse(self.hub.battles);self.tour()
        return self.hub.battles[self.owners[0]]

    def loaded(self):
        battle=self.enter()
        for index in range(8):self.send(index,b'\x36')
        self.hub.tick();return battle

    def test_original_overview_distinct_from_five_native_combat_scenes(self):
        loader=AssaultMapLoader()
        self.assertEqual(loader.overview(19)['asset'],'assault\\mo.xml')
        self.assertEqual(loader.overview(21)['asset'],'assault\\denver.xml')
        resources=set()
        for seed in range(30):
            layout,overview=loader.load(21,seed=seed);resources.add(layout.resource)
            self.assertEqual(len(layout.flags),3);self.assertEqual(overview['kind'],'strategic_overview')
            self.assertEqual((layout.arena.ground.width,layout.arena.ground.height),(55,33))
        self.assertEqual(resources,{f'assault_map_{i:02}' for i in range(1,6)})
        with self.assertRaises(ValueError):loader.load(7)

    def test_native_registration_eight_real_accounts_one_authoritative_scene(self):
        before=self.rows('territory_claims'),self.rows('warfare_scores'),self.rows('warfare_matches')
        battle=self.enter()
        self.assertEqual(set(self.hub.battles),set(self.owners))
        self.assertTrue(all(self.hub.battles[o] is battle for o in self.owners))
        self.assertEqual((battle['kind'],len(battle['humans']),battle['bots']),('training',8,set()))
        self.assertEqual(len(battle['assault_points'].positions),3)
        self.assertEqual(set(battle['field'].teams.values()),{0,1})
        self.assertEqual(battle['room'].request.mode,21)
        self.assertEqual(decode_battle_ground(battle['ground']).width,55)
        self.assertFalse(self.hub.training_groups)
        self.assertEqual((self.rows('territory_claims'),self.rows('warfare_scores'),self.rows('warfare_matches')),before)
        for owner in self.owners:
            packets=tuple(self.hub.queues[owner])
            self.assertEqual(sum(p[:2]==b'\xc8\x2e' for p in packets),3)
            self.assertIn(b'\xc8\x38'+struct.pack('<II',1,0),packets)
            self.assertIn(b'\x41',packets)

    def test_three_actual_tours_keep_cycles_separate_and_no_new_pairs_in_pause(self):
        self.send(0,encode_request(REQUEST_ROOMS));event=self.hub._training_event(19);rules=event['rules']
        for tour in (1,2,3):
            self.fixture.now=event['starts']+rules['registration_seconds']+(tour-1)*(rules['tour_seconds']+rules['pause_seconds'])+1
            current=self.hub._training_event(19)
            self.assertEqual((current['phase'],current['tour']),(f'TOUR{tour}',tour))
            self.assertEqual(current['id'],event['id'])
        self.fixture.now=event['starts']+rules['registration_seconds']+rules['tour_seconds']+1
        self.assertEqual(self.hub._training_event(19)['phase'],'TOUR2_PAUSE')
        self.register();self.hub.tick();self.assertFalse(self.hub.battles)
        self.tour(2);battle=self.hub.battles[self.owners[0]]
        self.assertEqual(battle['training_event']['tour'],2)
        self.assertEqual(battle['assault_points'].round,0)
        self.assertIn(b'\xc8\x38'+struct.pack('<II',1,0),self.hub.queues[self.owners[0]])

    def test_native_zone_schedule_pushes_only_phase_changes_to_idle_accounts(self):
        self.hub.tick_training_events(force=True)
        packet=next(p for p in self.hub.queues[self.owners[0]] if p[:2]==b'\xc8\x2d')
        self.assertEqual(packet,self.hub.training_town_packet(19))
        for queue in self.hub.queues.values():queue.clear()
        self.hub.tick_training_events(force=True)
        self.assertTrue(all(not q for q in self.hub.queues.values()))
        event=self.hub._training_event(19)
        self.fixture.now=event['starts']+event['rules']['registration_seconds']+1
        self.hub.tick_training_events(force=True)
        update=next(p for p in self.hub.queues[self.owners[0]] if p[:2]==b'\xc8\x2d')
        self.assertNotEqual(update,packet);self.assertEqual(update,self.hub.training_town_packet(19))

    def test_score_advanced_once_per_complete_living_owner_cycle_not_per_tour(self):
        battle=self.loaded();field=battle['field'];points=battle['assault_points']
        points.owners[:]=[0,None,None]
        for actor in tuple(field._actors.values()):field._actors[actor.actor_id]=replace(actor,x=2+actor.owner_id%8,y=2)
        for _ in range(8):
            owner=battle['arena']._turns[battle['room'].room_id][0]
            self.send(self.owners.index(owner),encode_end_turn());self.hub.tick()
        self.assertEqual((points.round,points.scores),(1,[4,0]))
        for _ in range(10):self.hub.tick()
        self.assertEqual(points.scores,[4,0]);self.assertEqual(battle['training_event']['tour'],1)

    def test_idle_ticks_skip_writes_but_absolute_tour_end_is_journaled(self):
        battle=self.loaded()
        with patch.object(self.hub.journal,'unit',wraps=self.hub.journal.unit) as units:
            for _ in range(10):self.hub.tick_battle(battle)
            self.assertEqual(units.call_count,0)
            self.fixture.now=battle['training_ends']+1;self.hub.tick_battle(battle)
            self.assertGreater(units.call_count,0)
        self.assertTrue(battle['finished'])

    def test_idle_live_turn_expires_common_tactical_marks_authoritatively(self):
        from tio.protocol.tactical_marks import TacticalMark,PLACE,REMOVE,encode_tactical_mark
        battle=self.loaded();owner=self.owners[0]
        self.send(0,encode_tactical_mark(TacticalMark(PLACE,self.sessions[0].probe_character_id,2,2)))
        self.assertIn(owner,battle['tactical_marks'])
        for queue in self.hub.queues.values():queue.clear()
        self.fixture.now+=201
        with patch.object(self.hub.journal,'unit',wraps=self.hub.journal.unit) as units:self.hub.tick_battle(battle)
        self.assertGreater(units.call_count,0);self.assertFalse(battle['tactical_marks'])
        self.assertTrue(all(any(p[:3]==bytes((0xb2,7,REMOVE)) for p in self.hub.queues[o]) for o in self.owners[:4]))
        self.assertTrue(all(not any(p[:2]==b'\xb2\x07' for p in self.hub.queues[o]) for o in self.owners[4:]))

    def test_rejected_postmove_projection_rolls_back_action_points_score_and_packets(self):
        from tio.protocol.battle_move import BattleMove,encode_move_request
        battle=self.loaded();field=battle['field'];owner=self.owners[0];identity=field.actor_ids(owner)[0]
        field.blocked=frozenset();field.doors.states={}
        field._actors[identity]=replace(field.actor(identity),x=5,y=5)
        for view in battle['views'].values():view.refresh()
        before=field.actor(identity);queues={o:tuple(q) for o,q in self.hub.queues.items()}
        with patch.object(self.hub,'training_refresh',side_effect=RuntimeError('projection failure')):
            with self.assertRaises(RuntimeError):self.hub.perform_action(battle,owner,encode_move_request(BattleMove(identity,((5,6),))))
        self.assertEqual(battle['field'].actor(identity),before)
        self.assertEqual(battle['assault_points'].scores,[0,0])
        self.assertEqual({o:tuple(q) for o,q in self.hub.queues.items()},queues)

    def test_single_group_and_unready_or_forged_rosters_never_create_bots(self):
        self.send(0,encode_request(CREATE_ROOM));group=self.hub.training_group(self.sessions[0])
        self.send(0,encode_request(SET_READY,1));packets=self.send(0,encode_request(START_ROOM))
        self.assertTrue(any(p[:1]==b'\xf0' for p in packets));self.assertFalse(self.hub.battles)
        self.tour();self.assertFalse(self.hub.battles)
        self.send(1,encode_request(JOIN_ROOM,group['id']))
        self.send(1,encode_request(0x20,999))
        self.assertEqual(group['members'][self.owners[1]]['pet_ids'],(1,))
        self.assertFalse(self.hub.battles)

    def test_training_selection_enforces_actual_band_full_hp_and_equipped_upgrade(self):
        from test_combat import item
        from tio.level_progression import FLOORS
        from tio.protocol.item_list import encode_item_list
        owner=self.owners[0];session=self.sessions[0]
        with closing(sqlite3.connect(self.path)) as db:original=db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',(session.account,)).fetchone()[0]
        pet=decode_pet_info(original,human_equipment=True)
        for changes in ({'0x8c4aef':3,'0x8c4b05':FLOORS[2]},{'0x8c4ab1':1}):
            with self.subTest(changes=changes):
                raw=encode_pet_info(replace(pet,fields={**pet.fields,**changes}))
                with closing(sqlite3.connect(self.path)) as db,db:
                    db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(raw,session.account))
                with self.assertRaises(ValueError):self.hub._training_selection(owner,(1,))
                with closing(sqlite3.connect(self.path)) as db,db:
                    db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(original,session.account))
        gear=replace(item(900,301,equipped=True),unknown_bytes_03=b'\x0b\0\0')
        with closing(sqlite3.connect(self.path)) as db,db:db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(gear,)),session.account))
        with self.assertRaisesRegex(ValueError,'предел'):self.hub._training_selection(owner,(1,))

    def test_loading_timeout_returns_everyone_without_any_rewards_or_capture(self):
        battle=self.enter();balances={s.account:WalletStore(self.path).ensure(s.account) for s in self.sessions}
        self.mono=battle['deadline']+1;self.hub.tick()
        self.assertTrue(battle['finished']);self.assertFalse(self.hub.battles)
        self.assertFalse(self.rows('battle_rewards'));self.assertFalse(self.rows('warfare_scores'))
        self.assertEqual({s.account:WalletStore(self.path).ensure(s.account) for s in self.sessions},balances)
        self.assertFalse(self.hub.account_owners)

    def test_deadline_normal_pvp_settles_once_no_territory_or_weekly_awards(self):
        battle=self.loaded();before=self.rows('territory_claims')
        self.fixture.now=battle['training_ends']+1;self.mono+=1;self.hub.tick()
        self.assertTrue(battle['finished']);self.assertFalse(self.hub.battles)
        self.assertEqual(len(self.rows('battle_rewards')),8)
        self.assertFalse(self.rows('warfare_match_receipts'));self.assertFalse(self.rows('warfare_scores'))
        self.assertFalse(self.rows('clan_assault_medals'));self.assertEqual(self.rows('territory_claims'),before)
        self.hub.tick();self.assertEqual(len(self.rows('battle_rewards')),8)
        self.assertTrue(all(any(p[:2]==b'\xc8\x32' for p in battle['result_packets'][o]) for o in self.owners))
        completed=b'\xc8\x38'+struct.pack('<II',1,1)
        self.assertTrue(all(completed in battle['result_packets'][o] for o in self.owners))
        self.assertEqual(self.hub.assault_packets(battle,self.owners[0])[-1],completed)
        self.assertIn(b'\xc8\x38'+bytes(8),self.send(0,b'\x2a\x01'))

    def test_native_move_and_confirmed_enemy_kill_settle_actual_xp_and_rank_once(self):
        import random
        from tio.protocol.battle_move import BattleMove,encode_move_request
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
        battle=self.loaded();field=battle['field'];combat=field.combat
        attacker=field.actor_ids(self.owners[0])[0];victim=field.actor_ids(self.owners[4])[0]
        # Bounded action fixture on the real authoritative scene. Moves, HP,
        # damage/kill counters and XP are produced by native accepted requests.
        field.blocked=frozenset();field.doors.states={}
        for index,actor in enumerate(tuple(field._actors.values())):
            field._actors[actor.actor_id]=replace(actor,x=15+index,y=15,sight_radius=30)
        field._actors[attacker]=replace(field.actor(attacker),x=5,y=5)
        field._actors[victim]=replace(field.actor(victim),x=6,y=6,health=1)
        combat.rng=random.Random(1)
        for view in battle['views'].values():view.refresh()
        packets=self.send(0,encode_move_request(BattleMove(attacker,((6,5),))))
        self.assertTrue(any(p[:1]==b'\x3d' for p in packets));self.assertEqual((field.actor(attacker).x,field.actor(attacker).y),(6,5))
        packets=self.send(0,encode_attack_request(AttackRequest(attacker,6,6)))
        result=decode_attack_result(next(p for p in packets if p[:1]==b'\x4b'))
        self.assertEqual(result.hits[0].actor_id,victim);self.assertEqual(field.actor(victim).health,0)
        self.assertEqual(combat.statistics[self.owners[0]]['kills'],1)
        self.fixture.now=battle['training_ends']+1;self.mono+=1;self.hub.tick()
        audits=self.rows('experience_battle_audit')
        self.assertGreater(next(r[4] for r in audits if r[0]==self.sessions[0].account),0)
        self.assertTrue(self.rows('rank_battle_audit'))
        before=self.rows('experience_battle_audit'),self.rows('rank_battle_audit'),self.rows('battle_rewards')
        self.hub.finish_training(battle)
        self.assertEqual((self.rows('experience_battle_audit'),self.rows('rank_battle_audit'),self.rows('battle_rewards')),before)

    def test_crash_recover_same_score_map_tour_deadline_and_native_reconnect_flags(self):
        battle=self.loaded();battle['assault_points'].scores[:]=[4,10]
        with self.hub.journal.unit(battle):pass
        for session in self.sessions:self.hub.disconnect(session)
        clone=TrainingHub(clock=lambda:self.mono);clone.init_training(self.path,wall=lambda:self.fixture.now,schedule='scheduled')
        clone.journal=BattleJournal(clone,self.path,wall=lambda:self.fixture.now)
        self.assertEqual(clone.journal.recover(),[battle['match_id']])
        restored=clone.battles[self.owners[0]]
        self.assertEqual(restored['assault_points'].scores,[4,10])
        self.assertEqual(restored['training_event'],battle['training_event'])
        self.assertEqual(restored['training_ends'],battle['training_ends'])
        self.assertEqual(restored['ground'],battle['ground'])
        clone.recover_training_events()
        self.assertEqual(clone._training_event(19)['id'],battle['training_event']['id'])
        self.assertTrue(clone.resume(self.sessions[0]))
        self.assertEqual(sum(p[:2]==b'\xc8\x2e' for p in clone.queues[self.owners[0]]),3)

    def test_failed_pair_birth_rolls_back_field_and_clears_readiness(self):
        self.register();event=self.hub._training_event(19)
        self.fixture.now=event['starts']+event['rules']['registration_seconds']+1;self.mono=2
        with patch.object(self.hub,'send_scene',side_effect=ValueError('injected scene projection')):self.hub.tick()
        self.assertFalse(self.hub.battles);self.assertFalse(self.rows('battle_checkpoints'))
        self.assertEqual(len(self.hub.training_groups),2)
        self.assertTrue(all(g['status']=='forming' for g in self.hub.training_groups.values()))
        self.assertTrue(all(not m['ready'] for g in self.hub.training_groups.values() for m in g['members'].values()))

    def test_waiting_group_blocks_map_travel_and_disconnect_releases_members(self):
        self.send(0,encode_request(CREATE_ROOM));session=self.sessions[0]
        self.assertTrue(self.hub.busy(session))
        with self.assertRaises(ValueError):session.locations.travel(session.account,b'\x1b'+struct.pack('<ii',0,0),1,busy=self.hub.busy(session))
        self.hub.disconnect(session)
        self.assertFalse(self.hub.training_groups);self.assertFalse(self.hub.training_members)


if __name__=='__main__':unittest.main()
