"""Eight independent humans through unchanged native Wall join/ready/attack/exit."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import patch

from wallet_fixture import fund_wallet
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import rating_completion
from tio.arena_service import ArenaService
from tio.locations import LocationStore
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import encode_item_list
from tio.survival_service import SurvivalService
import test_shared_team_arena as shared
import test_team_ranked as fixture


class NativeWallRatingTests(unittest.TestCase):
    def setUp(self):
        self.base=fixture.NativeTeamSeasonTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.case=self.base.case;self.path=self.base.path;self.hub=self.base.hub
        for name in ('eve','fred','gina','hank'):
            session=shared.Session();session.account=name;session.database=self.path
            session.probe_character_id=1;session.probe_character_name=name.encode()
            session.arena=ArenaService();session.survival=SurvivalService();session.locations=LocationStore(self.path)
            fund_wallet(self.path,name,credits=10_000,gold=10_000)
            pet=OwnedPetStore(self.path).list('alice')[0][1]
            OwnedPetStore(self.path).ensure(name,pet,encode_item_list(1,()),human=True)
            with closing(sqlite3.connect(self.path)) as db,db:session.locations._save(db,name,2,-367,-424)
            self.case.sessions.append(session)

    def start(self,full=True,load=True):
        for index in (0,1):self.case.send(index,b'\xba\x03\x04\x01')
        if full:
            for index in range(2,8):
                captain=index%2
                room=self.hub.lobbies.room(self.hub.identities[self.case.sessions[captain]])
                self.case.send(index,b'\xba\x04'+room.identity.to_bytes(4,'little'))
            for index in range(2,8):self.case.send(index,b'\x2c\x01')
        replies=()
        for index in (0,1):replies=self.case.send(index,b'\x2e')
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:8 if full else 2])
        self.assertIn(owners[0],self.hub.battles,[p[13:-2].decode('utf-16-le',errors='replace') for p in replies if p[:5]==b'\xf0\x8a\x01\x00\x00'])
        battle=self.hub.battles[owners[0]]
        if load:
            for index in range(8 if full else 2):self.case.send(index,b'\x36')
            self.hub.tick()
        return owners,battle

    def standings(self):
        with closing(sqlite3.connect(self.path)) as db:return rating_completion.standings(db,scope='2026-10')

    def finish(self):
        for index in (1,3,5,7):self.case.send(index,b'\x2a\x01')
        self.hub.tick();self.hub.tick()

    def test_eight_humans_native_attacks_exits_settle_fixed_four_squads_once(self):
        owners,battle=self.start();self.assertFalse(battle['bots'])
        self.assertEqual(len(battle['humans']),8);self.assertEqual(battle['team_rating_frozen']['format'],'wall')
        self.base.contested(owners,battle);self.finish()
        self.assertTrue(battle['finished']);rows=self.standings();self.assertEqual(len(rows),2)
        self.assertEqual(next(r for r in rows if r['wins'])['members'],['alice','carol','eve','gina'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_rewards').fetchone(),(8,))
            self.assertEqual(db.execute('SELECT count(*) FROM wall_ranked_matches WHERE rated=1').fetchone(),(1,))
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_players'").fetchone())
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='team_rating_values'").fetchone())
        self.hub.tick();self.assertEqual(rows,self.standings())

    def test_incomplete_bot_wall_never_admitted_and_shutdown_voids_full_match(self):
        _,battle=self.start(full=False);self.assertTrue(battle['bots']);self.assertNotIn('team_rating_frozen',battle)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='wall_ranked_matches'").fetchone())

    def test_restart_after_early_exit_across_month_archives_original_season(self):
        self.base.wall=fixture.utc(day=31,hour=23,minute=59)
        owners,battle=self.start();self.base.contested(owners,battle);frozen=battle['team_rating_frozen']
        self.case.send(1,b'\x2a\x01');self.base.wall=fixture.utc(month=11,day=1,hour=0)+1
        rating_completion.status(self.path,now=self.base.wall)
        restored=TeamArena(clock=lambda:self.case.now);restored.journal=BattleJournal(restored,self.path,wall=lambda:self.base.wall)
        self.assertEqual(restored.journal.recover(),[battle['match_id']])
        active=restored.battles[owners[0]];self.assertEqual(active['team_rating_frozen'],frozen)
        self.hub=restored;self.case.hub=restored
        for index in (0,2,3,4,5,6,7):
            self.assertTrue(restored.resume(self.case.sessions[index]));self.case.send(index,b'\x36')
        for index in (3,5,7):self.case.send(index,b'\x2a\x01')
        with patch('server.team_arena.time.time',return_value=self.base.wall):restored.tick()
        self.assertTrue(active['finished'])
        rows=self.standings();self.assertEqual(len(rows),2);self.assertTrue(all(r['archived'] for r in rows))
        restored.tick();self.assertEqual(rows,self.standings())

    def test_loading_timeout_voids_without_rating_or_prize(self):
        _,battle=self.start(load=False);self.case.now=61;self.hub.tick()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT state,rated FROM wall_ranked_matches').fetchall(),[('void',0)])
            self.assertFalse(db.execute('SELECT 1 FROM wall_rating_values').fetchone())
            self.assertEqual(set(db.execute('SELECT credits,gold FROM wallets')),{(10_000,10_000)})


if __name__=='__main__':unittest.main()
