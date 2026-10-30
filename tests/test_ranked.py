from wallet_fixture import fund_wallet
from battle_exit_fixture import place_squad_at_edge
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

from tio import ranked,battle_settlement,battle_snapshot
from tio.control_points import ControlPoints
from tio.battle_state import BattleActor,BattleField
from tio.protocol.ranked import decode_join
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.wallets import WalletStore
from tio.locations import LocationStore
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
import test_shared_team_arena as fixture


def join_packet(identity=1):
    return b'\xc6\x21'+bytes(2)+struct.pack('<III',1,identity,0)+b'\0'


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'ratings.db'
        for name in ('alice','bob','carol','dave'):fund_wallet(self.path, name, credits=10_000, gold=10_000)

    def report(self,winner=0,teams=(('alice',),('bob',))):
        return dict(winner=winner,teams=tuple(tuple((name,*ranked.snapshot(self.path,name)) for name in team) for team in teams))

    def apply(self,match,report):
        with closing(sqlite3.connect(self.path)) as db,db:ranked.settle(db,match,report,now=1)

    def test_true_skill_reference_and_upset(self):
        result=ranked.infer((((25,25/3),),((25,25/3),)),0)
        self.assertAlmostEqual(result[0][0][0],29.205473,places=5)
        self.assertAlmostEqual(result[0][0][1],7.194817,places=5)
        self.assertAlmostEqual(result[1][0][0],20.794527,places=5)
        favored=ranked.infer((((35,4),),((20,4),)),0)
        upset=ranked.infer((((35,4),),((20,4),)),1)
        self.assertGreater(upset[1][0][0]-20,favored[0][0][0]-35)

    def test_all_accounts_once_and_conflicting_retry(self):
        report=self.report();self.apply('one',report)
        self.assertGreater(ranked.snapshot(self.path,'alice')[0],25)
        self.assertLess(ranked.snapshot(self.path,'bob')[0],25)
        before=ranked.snapshot(self.path,'alice');self.apply('one',report)
        self.assertEqual(ranked.snapshot(self.path,'alice'),before)
        with self.assertRaisesRegex(ValueError,'Conflicting'):self.apply('one',{**report,'winner':1})

    def test_draw_resets_series_and_keeps_rating(self):
        self.apply('one',self.report());before=ranked.snapshot(self.path,'alice')
        self.apply('two',self.report(None))
        self.assertEqual(ranked.snapshot(self.path,'alice'),before)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT streak,draws FROM ranked_players WHERE account='alice'").fetchone(),(0,1))

    def test_league_promotion_and_four_loss_demotion_boundaries(self):
        self.assertEqual([ranked.league_for(p) for p in (0,100,101,200,201,300,301,400)], [3,3,2,2,1,1,0,0])
        for match in ('one','two'):self.apply(match,self.report())
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT league FROM ranked_players WHERE account='alice'").fetchone()[0],3)
        self.apply('three',self.report())
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT league,streak FROM ranked_players WHERE account='alice'").fetchone(),(2,3))
        for match in ('four','five'):self.apply(match,self.report(1))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT league FROM ranked_players WHERE account='alice'").fetchone()[0],2)
        self.apply('six',self.report(1))
        # The hosted May3 rules require four losses for demotion.
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT league,loss_streak FROM ranked_players WHERE account='alice'").fetchone(),(2,3))
        self.apply('seven',self.report(1))
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute("SELECT league,loss_streak FROM ranked_players WHERE account='alice'").fetchone(),(3,4))

    def test_team_outcome_and_public_place_ties(self):
        self.apply('teams',self.report(0,(('alice','carol'),('bob','dave'))))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(ranked.profile(db,'alice'),ranked.profile(db,'carol'))
            self.assertEqual(ranked.profile(db,'bob')[2],3)
            self.assertEqual(ranked.profile(db,'outsider'),(0,3,0,0))

    def test_outbox_rating_and_wallet_rollback_together(self):
        report=self.report()
        battle_settlement.initialise(self.path)
        battle_settlement.enqueue(self.path,'one',[('alice',1,dict(ranked_report=report))])
        with patch('tio.ranked.settle',side_effect=ValueError('fail')):
            with self.assertRaises(ValueError):battle_settlement.apply(self.path,'one','alice')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='battle_rewards'").fetchone())
        battle_settlement.apply(self.path,'one','alice');before=ranked.snapshot(self.path,'alice')
        battle_settlement.apply(self.path,'one','alice')
        self.assertEqual(ranked.snapshot(self.path,'alice'),before)


class PointTests(unittest.TestCase):
    def setUp(self):
        self.field=BattleField(20,20,[BattleActor(1,1,2,2,40,100,100),BattleActor(2,2,17,17,40,100,100)],teams={1:0,2:1},step_cost=1)
        self.points=ControlPoints(((2,2),(17,17),(10,10)),[0,1,None],[0,0])

    def move(self,identity,x,y,hp=None):
        a=self.field.actor(identity);self.field._actors[identity]=replace(a,x=x,y=y,health=a.health if hp is None else hp)

    def test_capture_neutralize_contest_and_dead_guard(self):
        self.move(1,10,10);self.points.capture(self.field);self.assertEqual(self.points.owners[2],0)
        self.move(1,9,10);self.move(2,10,10);self.points.capture(self.field);self.assertEqual(self.points.owners[2],0)
        self.move(1,3,3);self.points.capture(self.field);self.assertIsNone(self.points.owners[2])
        self.points.capture(self.field);self.assertEqual(self.points.owners[2],1)
        self.move(2,10,10,0);self.move(1,10,10);self.points.capture(self.field);self.assertIsNone(self.points.owners[2])

    def test_both_scores_tick_and_clamp_for_draw(self):
        self.points.scores=[995,995];self.points.advance(self.field)
        self.assertEqual(self.points.scores,[1000,1000]);self.assertEqual(self.points.outcome(self.field),2)
        self.move(2,17,17,0);self.assertEqual(self.points.outcome(self.field),0)

    def test_hold_after_departure_and_contest(self):
        self.move(1,5,5);self.points.advance(self.field)
        self.assertEqual(self.points.scores,[5,5])
        self.move(1,10,10);self.points.advance(self.field)
        self.assertEqual(self.points.scores,[15,10])


class RankedServerTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path;self.hub=self.case.hub
        for s in self.case.sessions:
            s.locations=LocationStore(self.path)
            with closing(sqlite3.connect(self.path)) as db,db:
                raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',(s.account,)).fetchone()[0]
                pet=decode_pet_info(raw,human_equipment=True)
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4})),s.account))
                s.locations._save(db,s.account,2,*(-367,-424))

    def start(self,journal=False):
        # Rated cases require two full human squads; smaller sides now gain
        # transient bots and follow the Team/Wall unrated policy.
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.item_list import encode_item_list
        from test_ranked_squads import join
        for session in self.case.sessions[:2]:
            store=OwnedPetStore(self.path);pet=decode_pet_info(store.list(session.account)[0][1],human_equipment=True)
            for identity in (2,3,4):
                store.ensure(session.account,encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':identity,'0x8c44a6':0})),encode_item_list(identity,()),human=True)
        if journal:self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:1000)
        self.case.send(0,join((1,2,3,4)));self.assertFalse(self.hub.battles)
        self.assertTrue(self.hub.busy(self.case.sessions[0]))
        replies=self.case.send(1,join((1,2,3,4)))
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2]);b=self.hub.battles[owners[0]]
        self.assertFalse(b['bots']);self.assertEqual(len(b['field']._actors),8)
        self.assertTrue(any(p[:2]==b'\xc6\x16' for p in replies))
        for index in (0,1):self.case.send(index,b'\x36')
        self.hub.tick()
        return owners,b

    def test_queue_cancel_town_foreign_actor_and_band_guards(self):
        self.case.send(0,join_packet());self.case.send(0,b'\xc6\x23');self.assertFalse(self.hub.ranked_waiting)
        self.assertTrue(any(p[0]==0xf0 for p in self.case.send(0,join_packet(20))))
        with closing(sqlite3.connect(self.path)) as db,db:self.case.sessions[0].locations._save(db,'alice',3,-154,-318)
        self.assertTrue(any(p[0]==0xf0 for p in self.case.send(0,join_packet())))
        self.assertFalse(self.hub.ranked_waiting)

    def test_saved_equipment_is_admitted_without_overrides(self):
        from tio.protocol.item_list import ItemRecord,encode_item_list
        item=ItemRecord(1001,301,bytes(2),1,1,16,(100,100,100),bytes(4),None,bytes(3))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',(encode_item_list(1,(item,)),'alice'))
        self.case.send(0,join_packet())
        self.assertIn(self.hub.identities[self.case.sessions[0]],self.hub.ranked_waiting)

    def test_score_win_with_both_fighters_alive_once(self):
        owners,b=self.start();b['points'].scores=[995,0]
        self.case.send(0,encode_end_turn());self.hub.tick()
        self.assertTrue(b['finished']);self.assertEqual(len(b['field'].living_sides()),2)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,result FROM battle_rewards ORDER BY account').fetchall(),[('alice',1),('bob',0)])
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone()[0],1)
        before=ranked.snapshot(self.path,'alice');self.hub.tick();self.assertEqual(ranked.snapshot(self.path,'alice'),before)

    def test_score_ticks_once_on_skip_and_expiration(self):
        owners,b=self.start();self.hub.tick();self.assertEqual(b['points'].scores,[0,0])
        self.case.send(0,encode_end_turn());self.hub.tick();self.hub.tick();self.assertEqual(b['points'].scores,[5,5])
        self.case.now=41;self.hub.tick();self.assertEqual(b['points'].scores,[10,10])

    def test_elimination_precedes_point_draw(self):
        owners,b=self.start();b['points'].scores=[1000,1000]
        for i in b['field'].actor_ids(owners[1]):b['field']._actors[i]=replace(b['field'].actor(i),health=0)
        self.hub.tick();self.assertEqual(b['ranked_winner'],0)

    def test_server_point_draw_is_unrated_and_shared_place(self):
        owners,b=self.start();b['points'].scores=[995,995]
        self.case.send(0,encode_end_turn());self.hub.tick()
        self.assertEqual(b['ranked_winner'],2)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT result FROM battle_rewards').fetchall(),[(2,),(2,)])
            for account in ('alice','bob'):
                self.assertEqual(ranked.profile(db,account),(0,3,1,0))
                self.assertEqual(ranked.snapshot(self.path,account),(ranked.MU,ranked.SIGMA))

    def test_reconnect_expiry_awards_opponent_once(self):
        owners,b=self.start();self.hub.disconnect(self.case.sessions[0])
        self.assertFalse(b['finished']);self.case.now=181;self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,wins,losses FROM ranked_players ORDER BY account').fetchall(),[('alice',0,1),('bob',1,0)])
            self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone()[0],1)

    def test_escape_winner_and_city_and_no_ordinary_rating(self):
        owners,b=self.start();place_squad_at_edge(b['field'],owners[0])
        self.case.send(0,b'\x2a\1');self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT account,wins,losses FROM ranked_players ORDER BY account').fetchall(),[('alice',0,1),('bob',1,0)])
        self.assertEqual(self.case.sessions[0].locations.current('alice'),2)

    def test_crash_restores_points_pending_turn_and_no_duplicate_rating(self):
        owners,b=self.start(journal=True)
        with self.hub.journal.unit(b):b['points'].scores=[995,0]
        restored=TeamArena(clock=lambda:0);restored.journal=BattleJournal(restored,self.path,wall=lambda:1000)
        restored.journal.recover();new=restored.battles[owners[0]]
        self.assertEqual(new['points'].scores,[995,0]);self.assertTrue(new['point_turn_pending'])
        restored.clock=lambda:41;new['arena']._clock=restored.clock;restored.tick()
        self.assertTrue(new['finished'])
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone()[0],1)

    def test_server_shutdown_voids_ranked_result(self):
        self.start();self.hub.shutdown_battles()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone())

    def test_completed_offline_result_expires_durably(self):
        from tio.battle_checkpoints import read
        owners,b=self.start(journal=True);b['points'].scores=[995,0]
        self.case.send(0,encode_end_turn());self.hub.tick()
        for s in self.case.sessions[:2]:self.hub.disconnect(s)
        self.assertTrue(read(self.path));self.case.now=181;self.hub.tick()
        self.assertEqual(read(self.path),[])
        self.assertFalse(self.hub.completed)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM ranked_matches').fetchone()[0],1)


class RankedWireTests(unittest.TestCase):
    def test_bounded_native_join(self):
        packet=join_packet();self.assertEqual(decode_join(packet)[1],((1,(),0),))
        for end in range(len(packet)):
            with self.assertRaises(ValueError):decode_join(packet[:end])
        with self.assertRaises(ValueError):decode_join(packet+b'\0')
