"""Real journaled three-account mining retirement and failed isolation paths."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import Mock,patch

from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import battle_checkpoints,battle_snapshot
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info
import test_shared_mine_arena as mine_fixtures


class SharedMineDisconnectTests(unittest.TestCase):
    def setUp(self):
        self.case=mine_fixtures.SharedMineArenaTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path;self.hub=self.case.hub;self.owners=self.case.owners[:3]
        self.sessions=self.case.case.sessions[:3];self.names=tuple(s.account for s in self.sessions)
        for session in self.sessions:session.stop=Mock()
        self.battle=self.case.enter()

    def rows(self,sql,params=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,params).fetchall()

    def checkpoint(self):
        return next(row for row in battle_checkpoints.read(self.path) if row[0]==self.battle['match_id'])

    def pets(self):
        return {name:OwnedPetStore(self.path).list(name) for name in self.names}

    def progress(self):
        # Escape legitimately changes rank/derived combat fields. HP, level,
        # cumulative XP and committed inventory must retain their exact state.
        return {name:tuple((identity,tuple(decode_pet_info(raw,human_equipment=True).fields[key]
                                         for key in ('0x8c4ab1','0x8c4a07','0x8c4aef','0x8c4b05')),inventory)
                          for identity,raw,inventory in OwnedPetStore(self.path).list(name))
                for name in self.names}

    def disconnect_all(self):
        for session in self.sessions:self.assertTrue(self.hub.disconnect(session))

    def expire(self):
        self.case.case.now=max(self.hub.offline.values())+1
        self.hub.tick()

    def test_each_live_join_updates_metadata_used_after_session_retirement(self):
        metadata=self.battle['durable_sessions']
        self.assertEqual(set(metadata),set(self.owners))
        for owner,session in zip(self.owners,self.sessions):
            self.assertEqual(metadata[owner],dict(account=session.account,name=session.probe_character_name,
                                                 character=session.probe_character_id))
        data,_=battle_snapshot.loads(self.checkpoint()[1])
        self.assertEqual(data['battle']['durable_sessions'],data['sessions'])
        # Joined escort retires first while the frozen roster keeps its identity.
        owner=self.owners[2];self.hub.settle(self.battle,owner,0,escaped=True)
        self.hub.remove_from_battle(self.battle,owner);self.hub.forget(owner)
        self.assertNotIn(owner,self.hub.players)
        self.assertEqual(set(self.hub.journal.data(self.battle)['sessions']),set(self.owners))
        self.assertEqual(len(self.checkpoint()[4]),2)

    def test_all_three_disconnected_expire_once_without_crystal_or_state_loss(self):
        progress=self.progress();self.disconnect_all();self.expire()
        self.assertFalse(self.hub.battles);self.assertFalse(self.hub.offline)
        self.assertFalse(battle_checkpoints.read(self.path))
        self.assertEqual(self.rows('SELECT COUNT(*) FROM battle_checkpoint_members'),[(0,)])
        self.assertEqual(self.rows('SELECT account,result,credits FROM battle_rewards ORDER BY account'),
                         [(name,0,0) for name in sorted(self.names)])
        self.assertEqual(self.rows('SELECT gross,tax FROM mine_crystal_extractions'),[(0,0)]*3)
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])
        self.assertEqual(self.progress(),progress)
        paid=self.rows('SELECT * FROM battle_rewards')
        self.hub.tick();self.hub.shutdown_battles()
        self.assertEqual(self.rows('SELECT * FROM battle_rewards'),paid)
        restored=TeamArena(clock=lambda:0);restored.journal=BattleJournal(restored,self.path)
        self.assertEqual(restored.journal.recover(),[])
        self.assertFalse(restored.completed)

    def test_retired_joined_owner_metadata_survives_recovery_then_remaining_expiry(self):
        owner=self.owners[2];self.hub.settle(self.battle,owner,0,escaped=True)
        self.hub.remove_from_battle(self.battle,owner);self.hub.forget(owner)
        self.hub.disconnect(self.sessions[0]);self.hub.disconnect(self.sessions[1])
        before=self.checkpoint();data,_=battle_snapshot.loads(before[1])
        ids=set(self.battle['field']._actors);progress=self.progress()
        self.case.wall+=181
        clone=TeamArena(clock=lambda:0)
        clone.journal=BattleJournal(clone,self.path,wall=lambda:self.case.wall)
        self.assertEqual(clone.journal.recover(),[self.battle['match_id']])
        b=clone.battles[self.owners[0]]
        self.assertEqual(set(b['durable_sessions']),set(self.owners))
        self.assertEqual(set(b['field']._actors),ids)
        self.assertEqual(b['ground'],self.battle['ground'])
        self.assertEqual(b['mine_claim'],data['battle']['mine_claim'])
        self.assertEqual(b['field'].mining.lift_blocked_until,5)
        clone.expire_reconnects();clone.expire_reconnects();clone.shutdown_battles()
        self.assertFalse(battle_checkpoints.read(self.path))
        self.assertEqual(self.rows('SELECT COUNT(*) FROM battle_checkpoint_members'),[(0,)])
        self.assertEqual(self.rows('SELECT COUNT(*) FROM battle_rewards'),[(3,)])
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])
        self.assertEqual(self.progress(),progress)

    def test_metadata_cache_rolls_back_if_snapshot_fails(self):
        # Every accepted journaled change must restore the cache as well.
        before=dict(self.battle['durable_sessions']);persisted=self.checkpoint()
        with patch('server.battle_journal.store.save',side_effect=RuntimeError('Injected snapshot failure')):
            with self.assertRaises(RuntimeError):
                with self.hub.journal.unit(self.battle):
                    self.battle['durable_sessions']={}
        self.assertEqual(self.battle['durable_sessions'],before)
        self.assertEqual(self.checkpoint(),persisted)

    def test_failed_quarantine_snapshot_keeps_last_commit_and_blocks_only_its_members(self):
        # An independent actual mine remains available throughout isolation.
        self.case.send(3,b'\xb0\x14\1');self.case.send(3,b'\x36')
        good_owner=self.case.owners[3];good=self.hub.battles[good_owner]
        good_checkpoint=next(row for row in battle_checkpoints.read(self.path) if row[0]==good['match_id'])
        committed=self.checkpoint();pets=self.pets();wallets=self.rows('SELECT * FROM wallets')
        self.sessions[0].stop.side_effect=RuntimeError('Injected close callback failure')
        # Corrupt only in-memory metadata as the hosted bug did. Force a
        # snapshot failure in the quarantine path itself, before settlement.
        with patch.object(self.hub.journal,'data',side_effect=KeyError('Injected missing journal metadata')):
            self.hub.quarantine(self.battle,ValueError('Injected match failure'))
        self.assertEqual(set(self.hub.battles),{good_owner});self.assertFalse(self.hub.completed)
        self.assertIs(self.hub.battles[good_owner],good)
        self.assertEqual(next(row for row in battle_checkpoints.read(self.path) if row[0]==good['match_id']),good_checkpoint)
        kept=self.checkpoint()
        self.assertEqual(kept[:3],committed[:3]);self.assertEqual(kept[3],'quarantined')
        self.assertEqual(kept[4],committed[4])
        self.assertEqual(self.pets(),pets);self.assertEqual(self.rows('SELECT * FROM wallets'),wallets)
        self.assertEqual(self.rows('SELECT * FROM battle_settlement_jobs'),[])
        self.assertEqual(self.rows('SELECT account,resolved FROM battle_failure_audit ORDER BY account'),
                         [(name,0) for name in sorted(self.names)])
        for session in self.sessions:
            session.stop.assert_called_once()
            self.assertTrue(battle_checkpoints.blocked(self.path,session.account))
        self.assertFalse(battle_checkpoints.blocked(self.path,'dave'))
        self.hub.tick();self.hub.shutdown_battles()
        restored=TeamArena(clock=lambda:0);restored.journal=BattleJournal(restored,self.path)
        self.assertEqual(restored.journal.recover(),[])
        self.assertEqual(self.checkpoint(),kept)

    def test_storage_failure_during_quarantine_is_not_swallowed(self):
        before=self.checkpoint()
        with patch.object(self.hub.journal,'data',side_effect=PermissionError('Injected storage failure')):
            with self.assertRaises(PermissionError):self.hub.quarantine(self.battle,ValueError('Match failure'))
        self.assertEqual(self.checkpoint(),before)
        self.assertEqual(set(self.hub.battles),set(self.owners))
        for session in self.sessions:session.stop.assert_not_called()


if __name__=='__main__':unittest.main()
