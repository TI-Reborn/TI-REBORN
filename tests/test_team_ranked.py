"""Four persisted accounts through native Team packets and crash checkpoints.

The controlled fixture places normal, unarmed level-four soldiers in adjacent
open cells to make real native 49 attacks deterministic. No added damage,
action points, health, gear or client-reported winner is used. This is server
protocol verification, not a visual test of the original game client.
"""
from collections import deque
from contextlib import closing
from dataclasses import replace
from datetime import datetime,timezone
import random
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.battle_journal import BattleJournal
from server.presence import Presence
from server.team_arena import TeamArena
from tio import team_ratings,rating_seasons,battle_settlement
from tio.battle_checkpoints import read as read_checkpoints
from tio.db_transaction import connect
from tio.locations import LocationStore
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.presence import Player
import test_shared_team_arena as fixture


def utc(month=10,day=8,hour=12,minute=0):
    return datetime(2026,month,day,hour,minute,tzinfo=timezone.utc).timestamp()


class NativeTeamSeasonTests(unittest.TestCase):
    def setUp(self):
        self.case=fixture.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.hub=self.case.hub;self.path=self.case.path;self.wall=utc()
        for session in self.case.sessions:
            session.locations=LocationStore(self.path)
            with closing(sqlite3.connect(self.path)) as db,db:
                raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',(session.account,)).fetchone()[0]
                pet=decode_pet_info(raw,human_equipment=True)
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',
                           (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':4})),session.account))
                session.locations._save(db,session.account,2,-367,-424)
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)

    def start(self,*,full=True,level=4,mode=1,load=True):
        if level!=4:
            for session in self.case.sessions:
                with closing(sqlite3.connect(self.path)) as db,db:
                    raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=?',(session.account,)).fetchone()[0]
                    pet=decode_pet_info(raw,human_equipment=True)
                    db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',
                        (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':level})),session.account))
                    session.locations._save(db,session.account,3,-154,-318)
        for index in (0,1):self.case.send(index,b'\xba\x03'+bytes((mode,1)))
        if full:
            for index,captain in ((2,0),(3,1)):
                room=self.hub.lobbies.room(self.hub.identities[self.case.sessions[captain]])
                self.case.send(index,b'\xba\x04'+room.identity.to_bytes(4,'little'))
                self.case.send(index,b'\x2c\x01')
        for index in (0,1):self.case.send(index,b'\x2e')
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:4 if full else 2])
        battle=self.hub.battles[owners[0]]
        if load:
            for index in range(4 if full else 2):self.case.send(index,b'\x36')
            self.hub.tick()
        return owners,battle

    def arrange_combat(self,owners,battle):
        field=battle['field']
        cells=next((x,y) for x in range(2,field.width-2) for y in range(2,field.height-2)
                   if all((x+dx,y+dy) not in field.blocked for dx in (-1,0,1,2) for dy in (-1,0,1,2)))
        x,y=cells;positions=((x,y),(x+1,y),(x,y+1),(x+1,y+1))
        with self.hub.journal.unit(battle):
            for owner,(x,y) in zip(owners,positions):
                identity=field.actor_ids(owner)[0]
                field._actors[identity]=replace(field.actor(identity),x=x,y=y)
            field.combat.rng=random.Random(0)
            for view in battle['views'].values():view.refresh()

    def contested(self,owners,battle):
        self.arrange_combat(owners,battle);field=battle['field']
        first=field.actor_ids(owners[0])[0];second=field.actor_ids(owners[1])[0]
        for index,actor,target in ((0,first,second),(1,second,first)):
            current=field.actor(target)
            replies=self.case.send(index,encode_attack_request(AttackRequest(actor,current.x,current.y)))
            self.assertFalse(any(p[:1]==b'\xf0' for p in replies),replies)
            self.assertIn(owners[index],battle['reward_damage'])
            if index==0:
                self.case.send(0,encode_end_turn(first));self.hub.tick()
        return first,second

    def standings(self,scope='2026-10'):
        with closing(sqlite3.connect(self.path)) as db:return team_ratings.standings(db,scope=scope)

    def test_four_real_team_members_contested_normal_exits_settle_both_pairs_once(self):
        owners,battle=self.start();self.assertFalse(battle['bots']);self.assertEqual(len(battle['humans']),4)
        self.assertIn('team_rating_frozen',battle);self.contested(owners,battle)
        self.assertEqual(len(read_checkpoints(self.path)),1)
        self.case.send(1,b'\x2a\x01');self.case.send(3,b'\x2a\x01')
        self.assertIsNone(self.hub.team_rating_report(battle))
        counts=[];original=battle_settlement.apply
        def observe(path,match,account):
            result=original(path,match,account)
            with closing(connect(path)) as db:
                row=db.execute('SELECT state FROM team_ranked_matches WHERE match_id=?',(match,)).fetchone()
                if row and row[0]=='settled':counts.append(db.execute('SELECT count(*) FROM team_rating_values').fetchone()[0])
            return result
        with patch('tio.battle_settlement.apply',side_effect=observe):self.hub.tick()
        self.assertTrue(battle['finished']);self.assertEqual(counts,[4,4])
        rows=self.standings();winner=next(r for r in rows if r['wins']);loser=next(r for r in rows if r['losses'])
        self.assertEqual(winner['members'],['alice','carol']);self.assertEqual(loser['members'],['bob','dave'])
        self.hub.tick();self.assertEqual(rows,self.standings())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM team_ranked_matches WHERE rated=1').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT account,result FROM battle_rewards ORDER BY account').fetchall(),
                             [('alice',1),('bob',0),('carol',1),('dave',0)])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone())

    def test_incomplete_with_bots_and_starter_team_do_not_touch_rating(self):
        _,battle=self.start(full=False)
        self.assertTrue(battle['bots']);self.assertNotIn('team_rating_frozen',battle)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='team_ranked_matches'").fetchone())

    def test_starter_four_account_team_has_no_rating_admission(self):
        _,battle=self.start(level=1)
        self.assertNotIn('team_rating_frozen',battle)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='team_ranked_matches'").fetchone())

    def test_planned_stop_void_admission_without_wins(self):
        owners,battle=self.start();self.hub.shutdown_battles()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state,rated FROM team_ranked_matches').fetchall(),[('void',0)])
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_values').fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM team_ranked_opponents').fetchone())

    def test_native_loading_timeout_voids_admitted_team_without_outcome(self):
        _,battle=self.start(load=False);self.case.now=61;self.hub.tick()
        self.assertFalse(self.hub.battles)
        with closing(sqlite3.connect(self.path)) as db:
            state,value=db.execute('SELECT state,result FROM team_ranked_matches').fetchone()
            self.assertEqual(state,'void');self.assertIn('loading_timeout',value)
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_values').fetchone())

    def test_quarantined_server_failure_cannot_award_rating(self):
        _,battle=self.start()
        for session in self.case.sessions:session.stop=lambda:None
        self.hub.quarantine(battle,ValueError('Injected server failure'))
        with closing(sqlite3.connect(self.path)) as db:
            state,value=db.execute('SELECT state,result FROM team_ranked_matches').fetchone()
            self.assertEqual(state,'void');self.assertIn('server_fault',value)
            self.assertFalse(db.execute('SELECT 1 FROM team_rating_values').fetchone())

    def test_crash_after_early_escape_preserves_other_three_accounts_and_pair(self):
        owners,battle=self.start();self.contested(owners,battle)
        frozen=battle['team_rating_frozen'];self.case.send(1,b'\x2a\x01')
        restored=TeamArena(clock=lambda:self.case.now);restored.journal=BattleJournal(restored,self.path,wall=lambda:self.wall)
        self.assertEqual(restored.journal.recover(),[battle['match_id']])
        active=restored.battles[owners[0]];self.assertNotIn('faulted',active)
        self.assertEqual(active['team_rating_frozen'],frozen)
        self.assertEqual(active['humans'],{owners[0],owners[2],owners[3]})
        self.assertFalse(active['field'].actor_ids(owners[1]));self.assertEqual(active['reward_damage'],battle['reward_damage'])
        self.hub=restored;self.case.hub=restored
        for index in (0,2,3):
            session=self.case.sessions[index];self.assertTrue(restored.resume(session));self.case.send(index,b'\x36')
        self.case.send(3,b'\x2a\x01');restored.tick()
        self.assertTrue(active['finished']);self.assertEqual(len(self.standings()),2)

    def test_reconnect_across_month_boundary_keeps_old_season_and_archives_once(self):
        self.wall=utc(day=31,hour=23,minute=59)
        owners,battle=self.start();self.contested(owners,battle)
        frozen=battle['team_rating_frozen'];self.hub.disconnect(self.case.sessions[0])
        self.wall=utc(month=11,day=1,hour=0)+1
        # Opening the next calendar month cannot archive its unfinished battle.
        team_ratings.status(self.path,now=self.wall)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT state FROM team_rating_seasons WHERE season_id='2026-10'").fetchone(),('closing',))
        restored=TeamArena(clock=lambda:self.case.now);restored.journal=BattleJournal(restored,self.path,wall=lambda:self.wall)
        self.assertEqual(restored.journal.recover(),[battle['match_id']])
        active=restored.battles[owners[0]];self.assertEqual(active['team_rating_frozen'],frozen)
        self.hub=restored;self.case.hub=restored
        for index in range(4):
            self.assertTrue(restored.resume(self.case.sessions[index]));self.case.send(index,b'\x36')
        for index in (1,3):self.case.send(index,b'\x2a\x01')
        with patch('server.team_arena.time.time',return_value=self.wall):restored.tick()
        rows=self.standings();self.assertEqual(len(rows),2);self.assertTrue(all(r['archived'] for r in rows))
        self.assertFalse(self.standings('2026-11'))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM team_rating_archives').fetchone()[0],2)
        restored.tick();team_ratings.status(self.path,now=self.wall+1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM team_rating_archives').fetchone()[0],2)

    def test_native_presence_command_replies_only_to_requester(self):
        owners,battle=self.start();self.contested(owners,battle)
        for index in (1,3):self.case.send(index,b'\x2a\x01')
        self.hub.tick();presence=Presence()
        for index,session in enumerate(self.case.sessions):
            presence.players[session]=(2,Player(index+10,session.probe_character_name,4))
            presence.messages[session]=deque()
        packet=b'\x21\0'+'!teamrating'.encode('utf-16-le')+bytes(2)
        with patch('server.team_ranked.time.time',return_value=self.wall):
            self.assertTrue(presence.handle(self.case.sessions[0],packet))
        replies=tuple(presence.messages[self.case.sessions[0]])
        self.assertTrue(replies);self.assertTrue(all(p[:1]==b'\x22' for p in replies))
        self.assertTrue(all(not presence.messages[s] for s in self.case.sessions[1:]))
        self.assertTrue(any('alice + carol' in p.decode('utf-16-le',errors='ignore') for p in replies))


if __name__=='__main__':unittest.main()
