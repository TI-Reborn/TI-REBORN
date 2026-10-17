"""Real saved accounts share wager scenes, escrow and restart outcomes."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest

import test_shared_team_arena as fixture
from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.wagers import encode_join
from tio.protocol.item_list import decode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.owned_pets import OwnedPetStore
from tio.wallets import WalletStore
from tio.wagers import WagerStore


class SharedWagerTests(unittest.TestCase):
    send=fixture.SharedTeamTests.send
    add_selected=fixture.SharedTeamTests.add_selected

    def setUp(self):
        fixture.SharedTeamTests.setUp(self)
        self.wall=1_800_000_000
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)

    def balance(self,index):
        return WalletStore(self.path).ensure(self.sessions[index].account).credits

    def open(self,*,mode=0,count=2,map_size=2,soldiers=1,delta=0,stake=100):
        request=ArenaCreateRequest(mode,map_size,count,2,20*soldiers+20,soldiers,soldiers,delta,stake)
        replies=self.send(0,encode_create_request(request))
        self.assertTrue(any(p[0]==0x6c for p in replies),replies)
        owner=self.hub.identities[self.sessions[0]]
        room=self.hub.wager_lobbies.room(owner)
        for index in range(1,count):
            replies=self.send(index,encode_join(room.identity))
            self.assertTrue(any(p[0]==0x6c for p in replies),replies)
        for index in range(1,count):self.send(index,b'\x2c\x01')
        self.send(0,b'\x2e')
        return room

    def launch(self,**kwargs):
        room=self.open(**kwargs)
        self.now=5;self.hub.tick()
        owners=[self.hub.identities[s] for s in self.sessions[:room.capacity]]
        self.assertTrue(all(o in self.hub.battles for o in owners))
        battle=self.hub.battles[owners[0]]
        for index in range(room.capacity):self.send(index,b'\x36')
        self.hub.tick()
        return owners,battle

    def escrow(self,match):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT status,pot FROM wager_matches WHERE match_id=?',(match,)).fetchone()

    def test_countdown_is_cancellable_and_reserves_whole_pot_atomically(self):
        room=self.open(count=4)
        self.assertEqual([self.balance(i) for i in range(4)],[9900]*4)
        match=room.match_id
        self.now=4.99;self.hub.tick();self.assertFalse(self.hub.battles)
        self.send(2,b'\x2c\x00')
        self.assertEqual([self.balance(i) for i in range(4)],[10000]*4)
        self.assertEqual(self.escrow(match),('refunded',400))
        self.now=6;self.hub.tick();self.assertFalse(self.hub.battles)

    def test_four_way_wager_pays_once_without_ordinary_progression(self):
        before=[OwnedPetStore(self.path).list(s.account)[0][1] for s in self.sessions]
        owners,battle=self.launch(count=4)
        self.assertEqual(self.escrow(battle['match_id']),('active',400))
        self.assertEqual(len(battle['field'].living_sides()),4)
        self.assertEqual((battle['field'].width,battle['field'].height),(47,47))
        self.assertTrue(battle['field'].combat.wager)
        self.assertEqual(battle['arena']._turns[battle['room'].room_id][2],self.now+40)
        for index in (1,2,3):self.send(index,b'\x2a\x01')
        self.hub.tick()
        self.assertTrue(battle['finished'])
        self.assertEqual([self.balance(i) for i in range(4)],[10300,9900,9900,9900])
        self.hub.finish(battle)
        self.assertEqual(self.balance(0),10300)
        self.assertEqual([OwnedPetStore(self.path).list(s.account)[0][1] for s in self.sessions],before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT sum(amount),count(*) FROM wager_receipts').fetchone(),(400,4))
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in ('battle_experience','battle_rank_rewards','team_ranked_matches','battle_statistics'):
                if name in tables:self.assertEqual(db.execute('SELECT count(*) FROM '+name).fetchone()[0],0)

    def test_team_winners_share_pot_and_forfeited_teammate_gets_no_share(self):
        owners,battle=self.launch(mode=1,count=4)
        self.assertEqual([battle['field'].teams[o] for o in owners],[0,1,0,1])
        self.send(2,b'\x2a\x01');self.send(1,b'\x2a\x01');self.send(3,b'\x2a\x01')
        self.hub.tick()
        self.assertEqual([self.balance(i) for i in range(4)],[10300,9900,9900,9900])
        self.assertIsNone(self.hub.team_rating_report(battle))

    def test_mixed_manual_bands_are_admitted_only_with_creator_level_delta(self):
        for index in range(2):
            packet=OwnedPetStore(self.path).list(self.sessions[index].account)[0][1]
            pet=decode_pet_info(packet,human_equipment=True)
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=?',
                    (encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':2+index})),self.sessions[index].account))
        owners,battle=self.launch(delta=1)
        self.assertEqual({level for _,levels,_ in battle['reward_roster'].values() for level in levels},{2,3})

    def test_loading_exit_refunds_every_participant_and_clears_checkpoint(self):
        room=self.open(count=3);match=room.match_id
        self.now=5;self.hub.tick()
        self.send(1,b'\x2a\x01')
        self.assertFalse(self.hub.battles)
        self.assertEqual([self.balance(i) for i in range(3)],[10000]*3)
        self.assertEqual(self.escrow(match),('refunded',300))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM battle_checkpoints').fetchone()[0],0)

    def test_loading_timeout_refunds_and_notifies_without_starting(self):
        room=self.open();match=room.match_id
        self.now=5;self.hub.tick();self.send(0,b'\x36')
        self.now=66;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertEqual([self.balance(i) for i in range(2)],[10000]*2)
        self.assertEqual(self.escrow(match),('refunded',200))

    def test_restart_restores_active_scene_and_retains_held_pot(self):
        owners,battle=self.launch(count=4,map_size=3);match=battle['match_id']
        other=TeamArena(clock=lambda:self.now)
        other.journal=BattleJournal(other,self.path,wall=lambda:self.wall)
        self.assertEqual(other.journal.recover(),[match])
        self.assertFalse(WagerStore(self.path).recover({match}))
        restored=other.battles[owners[0]]
        self.assertEqual(restored['kind'],'wager')
        self.assertTrue(restored['field'].combat.wager)
        self.assertEqual(restored['wager_request'].stake,100)
        self.assertEqual(self.escrow(match),('active',400))
        self.assertEqual([self.balance(i) for i in range(4)],[9900]*4)

    def test_planned_shutdown_returns_pot_and_preserves_no_pending_lease(self):
        owners,battle=self.launch();match=battle['match_id']
        self.hub.shutdown_battles()
        self.assertEqual([self.balance(i) for i in range(2)],[10000]*2)
        self.assertEqual(self.escrow(match),('refunded',200))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM wager_leases').fetchone()[0],0)

    def test_scene_birth_failure_rolls_back_checkpoint_and_refunds_full_pot(self):
        from unittest.mock import patch
        room=self.open();match=room.match_id
        with patch('tio.battle_checkpoints.save',side_effect=ValueError('write rejected')):
            self.now=5;self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertEqual(self.escrow(match),('refunded',200))
        self.assertEqual([self.balance(i) for i in range(2)],[10000]*2)


if __name__=='__main__':unittest.main()
