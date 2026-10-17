"""Shared native PvP admission/rewards against actual SQLite/journal authority.

Damage is produced by accepted attack49; direct fixture positioning/wounding
only bounds the action scenario. No hosted or graphical acceptance is implied.
"""
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
import json
import random
import sqlite3
import unittest
from unittest.mock import patch

import test_shared_team_arena as shared
from server.battle_journal import BattleJournal
from server.team_arena import TeamArena
from tio import battle_rewards,world_completion as world
from tio.clans import ClansStore
from tio.db_transaction import transaction
from tio.level_progression import FLOORS,XP,LEVEL
from tio.locations import LocationStore,center
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_ground import decode_battle_ground
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.wallets import WalletStore


class WorldRewardIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case=shared.SharedTeamTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.path=self.case.path;self.hub=self.case.hub;self.wall=3599
        with transaction(self.path) as db:
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER,name BLOB,name_key TEXT UNIQUE)')
            for session in self.case.sessions:
                db.execute('INSERT INTO characters VALUES (?,1,?,?)',(session.account,session.probe_character_name,session.account))
                raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(session.account,)).fetchone()[0]
                pet=decode_pet_info(raw,human_equipment=True)
                fields={**pet.fields,LEVEL:4,XP:FLOORS[3],'0x8c4bbc':1,'0x8c4bd0':0,'0x8c4a07':100,'0x8c4ab1':100}
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields=fields)),session.account))
        self.clans=ClansStore(self.path);self.clan=self.clans.create('alice',b'Actual city rewards')
        for session in self.case.sessions:
            session.locations=LocationStore(self.path,clock=lambda:self.wall)
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.wall)

    def read(self,sql,args=()):
        with closing(sqlite3.connect(self.path)) as db:return db.execute(sql,args).fetchall()

    def table(self,name):
        if not self.read("SELECT 1 FROM sqlite_master WHERE name=?",(name,)):return ()
        return tuple(self.read('SELECT * FROM '+name+' ORDER BY 1,2'))

    def start(self,town=2):
        with transaction(self.path) as db:
            for session in self.case.sessions[:2]:LocationStore._save(db,session.account,town,*center(town))
        for index in (0,1):self.case.send(index,b'\xba\x03\0\1')
        owners=tuple(self.hub.identities[s] for s in self.case.sessions[:2])
        self.assertIn(owners[0],self.hub.battles,'Saved healthy accounts must enter this public city through the native survival route')
        battle=self.hub.battles[owners[0]]
        self.assertIs(battle,self.hub.battles[owners[1]]);self.assertFalse(battle['bots'])
        self.assertEqual(battle['humans'],set(owners));self.assertEqual(battle['city_id'],town)
        return owners,battle

    def action_ready(self,town=2):
        owners,battle=self.start(town);field=battle['field']
        actors=tuple(field.actor_ids(o)[0] for o in owners)
        with self.hub.journal.unit(battle):
            field.blocked=frozenset();field.doors.states={};field.combat.rng=random.Random(1)
            for n,identity in enumerate(actors):
                field._actors[identity]=replace(field.actor(identity),x=10+n,y=10,sight_radius=30,
                    health=10 if n else field.actor(identity).health)
            for view in battle['views'].values():view.refresh()
        for index in (0,1):self.case.send(index,b'\x36')
        self.hub.tick()
        if battle['arena']._turns[battle['room'].room_id][0]!=owners[0]:
            self.case.send(1,encode_end_turn());self.hub.tick()
        for queue in self.hub.queues.values():queue.clear()
        return owners,battle,actors

    def kill(self,battle,actors):
        packets=self.case.send(0,encode_attack_request(AttackRequest(actors[0],11,10)))
        result=decode_attack_result(next(p for p in packets if p[:1]==b'\x4b'))
        self.assertEqual(tuple((h.actor_id,h.damage,h.left_hp) for h in result.hits),((actors[1],10,0),))
        self.assertEqual(battle['field'].combat.statistics[self.hub.identities[self.case.sessions[0]]]['kills'],1)
        return result

    def test_native_shared_admission_freezes_before_hour_change_and_crash_reconnect(self):
        owners,battle=self.start();saved=world.city_coefficients(2,now=3599)
        self.assertEqual(battle['city_coefficients'],saved)
        self.assertEqual(battle['field'].combat.city_kill_bonus,saved['kill_bonus'])
        self.wall=3601
        self.assertNotEqual(world.city_coefficients(2,now=self.wall)['profit'],saved['profit'])
        restored=TeamArena(clock=lambda:self.case.now)
        restored.journal=BattleJournal(restored,self.path,wall=lambda:self.wall)
        self.assertEqual(restored.journal.recover(),[battle['match_id']])
        for owner in owners:self.assertIs(restored.battles[owner],restored.battles[owners[0]])
        clone=restored.battles[owners[0]]
        self.assertEqual(clone['city_coefficients'],saved);self.assertEqual(clone['field'].combat.city_kill_bonus,10)
        with transaction(self.path) as db:self.assertEqual(world.frozen_city(db,battle['match_id']),saved)
        self.assertTrue(restored.resume(self.case.sessions[0]))

    def test_detroit_native_entry_admits_actual_roster_and_original_whole_map(self):
        owners,battle=self.start(18)
        mapped=decode_battle_ground(battle['ground'])
        self.assertEqual((mapped.width,mapped.height),(38,38))
        self.assertEqual(battle['field'].scene_metadata['profile'],'detroit')
        self.assertEqual(battle['city_coefficients'],world.city_coefficients(18,now=self.wall))
        self.assertEqual(set(battle['reward_roster']),set(owners))

    def test_actual_damage_xp_profit_and_clan_influence_use_admitted_hour_once(self):
        owners,battle,actors=self.action_ready();saved=dict(battle['city_coefficients'])
        self.wall=3601
        self.assertNotEqual(world.city_coefficients(2,now=self.wall)['experience'],saved['experience'])
        balances={s.account:WalletStore(self.path).ensure(s.account).credits for s in self.case.sessions[:2]}
        self.kill(battle,actors);self.hub.tick();self.assertTrue(battle['finished'])
        gains=dict(self.read('SELECT account,gain FROM experience_battle_audit WHERE match_id=?',(battle['match_id'],)))
        self.assertEqual(gains,{'alice':32,'bob':16})
        self.assertEqual(self.clans.info('alice')['contribution'],1)
        audit=json.loads(self.read("SELECT calculation FROM battle_rewards WHERE match_id=? AND account='alice'",(battle['match_id'],))[0][0])
        self.assertEqual(audit['city_coefficients'],saved);self.assertEqual(audit['experience_factor'],'4/5')
        gross=battle_rewards.receipt(self.path,'alice',battle['match_id'])[0]
        self.assertEqual(gross,int(Fraction(109)*Fraction(saved['profit'])))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,balances['alice']+gross)
        before={n:self.table(n) for n in ('experience_battle_audit','rank_battle_audit','clan_benefit_receipts','battle_rewards','player_battle_statistics')}
        for owner in owners:self.hub.settle(battle,owner,int(owner==owners[0]))
        self.assertEqual({n:self.table(n) for n in before},before)
        recovered=TeamArena(clock=lambda:self.case.now);recovered.journal=BattleJournal(recovered,self.path,wall=lambda:self.wall+1)
        self.assertEqual(recovered.journal.recover(),[battle['match_id']])
        for index,owner in enumerate(owners):
            self.assertTrue(recovered.resume(self.case.sessions[index]));recovered.queues[owner].clear()
            self.assertTrue(recovered.handle(self.case.sessions[index],b'\x36'))
            self.assertEqual(tuple(recovered.queues[owner]),battle['result_packets'][owner])
        self.assertEqual({n:self.table(n) for n in before},before)
        self.assertEqual(self.clans.info('alice')['contribution'],1)

    def test_outpost_actual_kill_has_reduced_xp_and_no_positive_or_death_rank(self):
        owners,battle,actors=self.action_ready(4)
        self.assertEqual(battle['city_coefficients']['experience'],'3/4')
        self.assertEqual(battle['field'].combat.city_kill_bonus,0)
        before_points=self.read('SELECT account,points FROM soldier_ranks ORDER BY account')
        self.assertTrue(all(points==0 for account,points in before_points))
        self.kill(battle,actors);self.hub.tick();self.assertTrue(battle['finished'])
        self.assertEqual(dict(self.read('SELECT account,gain FROM experience_battle_audit WHERE match_id=?',(battle['match_id'],))),{'alice':30,'bob':15})
        self.assertEqual(self.clans.info('alice')['contribution'],0)
        self.assertEqual(self.read('SELECT account,points FROM soldier_ranks ORDER BY account'),before_points)
        self.assertEqual(self.table('rank_battle_audit'),())
        self.assertEqual(battle_rewards.receipt(self.path,'alice',battle['match_id']), (109,0))

    def test_failed_shared_birth_rolls_back_coefficients_bindings_and_queued_scene(self):
        with transaction(self.path) as db:
            for session in self.case.sessions[:2]:LocationStore._save(db,session.account,2,*center(2))
        self.case.send(0,b'\xba\x03\0\1')
        before={s.account:WalletStore(self.path).ensure(s.account) for s in self.case.sessions[:2]}
        from server import world_runtime
        original=world_runtime.admit
        def reject(db,battle,**kwargs):
            original(db,battle,**kwargs)
            raise ValueError('injected after real city freeze')
        with patch.object(world_runtime,'admit',side_effect=reject):packets=self.case.send(1,b'\xba\x03\0\1')
        self.assertTrue(any(p[:1]==b'\xf0' for p in packets))
        self.assertFalse(self.hub.battles);self.assertFalse(self.hub.account_owners)
        self.assertEqual(self.table('world_city_matches'),());self.assertEqual(self.table('battle_checkpoints'),())
        self.assertEqual({s.account:WalletStore(self.path).ensure(s.account) for s in self.case.sessions[:2]},before)
        self.assertFalse(any(p[:1] in (b'\x35',b'\x41') for q in self.hub.queues.values() for p in q))
        self.case.send(1,b'\xba\x07\x01');self.hub.tick()
        self.assertEqual(len({id(b) for b in self.hub.battles.values()}),1)
        self.assertEqual(len(self.table('world_city_matches')),1)

    def test_postreward_error_rolls_back_wallet_xp_rank_influence_and_outbox_then_retry(self):
        owners,battle,actors=self.action_ready();self.kill(battle,actors)
        tables=('experience_battle_audit','rank_battle_audit','clan_benefit_receipts','battle_rewards','player_battle_statistics','owned_pets','wallets','clans','clan_members','battle_settlement_jobs')
        before={n:self.table(n) for n in tables};queued={o:tuple(q) for o,q in self.hub.queues.items()}
        from tio import clans
        original=clans.settle_influence
        def reject(*args,**kwargs):
            result=original(*args,**kwargs)
            raise ValueError('injected after real clan credit')
        with patch.object(clans,'settle_influence',side_effect=reject):
            from server.battle_failures import BattleSettlementError
            with self.assertRaises(BattleSettlementError):self.hub.finish(battle)
        self.assertFalse(battle['finished']);self.assertFalse(battle['settled'])
        self.assertEqual({n:self.table(n) for n in tables},before)
        self.assertEqual({o:tuple(q) for o,q in self.hub.queues.items()},queued)
        self.hub.finish(battle);self.assertTrue(battle['finished'])
        self.assertEqual(len(self.table('battle_rewards')),2);self.assertEqual(len(self.table('experience_battle_audit')),2)
        self.assertEqual(self.clans.info('alice')['contribution'],1)
        settled={n:self.table(n) for n in tables}
        for owner in owners:self.hub.settle(battle,owner,int(owner==owners[0]))
        self.assertEqual({n:self.table(n) for n in tables},settled)


if __name__=='__main__':unittest.main()
