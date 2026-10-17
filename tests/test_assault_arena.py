"""Eight separate accounts, original maps and journaled server decisions."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import Mock

from server.team_arena import TeamArena
from server.battle_journal import BattleJournal
from tio.arena_service import ArenaService
from tio.survival_service import SurvivalService
from tio.locations import LocationStore,center
from tio.wallets import WalletStore
from tio.protocol.assault import encode_request,CREATE_ROOM,JOIN_ROOM,SET_READY,START_ROOM
from tio.protocol.battle_turn import encode_end_turn
from tio import battle_checkpoints
import test_territories as fixtures


class Session:pass


class AssaultArenaTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TerritoriesTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.path=self.fixture.path;self.mono=0;self.hub=TeamArena(clock=lambda:self.mono)
        self.hub.init_assault(self.path,wall=lambda:self.fixture.now)
        self.hub.journal=BattleJournal(self.hub,self.path,wall=lambda:self.fixture.now)
        self.sessions=[]
        for account in self.fixture.accounts[:8]:
            s=Session();s.account=account;s.database=self.path;s.probe_character_id=1;s.probe_character_name=account.encode()
            s.locations=LocationStore(self.path,clock=lambda:self.fixture.now)
            s.arena=ArenaService();s.survival=SurvivalService();s.stop=Mock()
            WalletStore(self.path).ensure(account)
            with closing(sqlite3.connect(self.path)) as db,db:LocationStore._save(db,account,11,*center(11))
            self.hub.identity(s);self.sessions.append(s)
        self.owners=tuple(self.hub.identities[s] for s in self.sessions)

    def send(self,i,packet):
        self.assertTrue(self.hub.handle(self.sessions[i],packet))
        owner=self.hub.identities[self.sessions[i]];rows=tuple(self.hub.queues[owner]);self.hub.queues[owner].clear()
        return rows

    def enter(self):
        for offset in (0,4):
            replies=self.send(offset,encode_request(CREATE_ROOM))
            self.assertTrue(any(p[:2]==b'\xc8\x24' for p in replies),replies)
            group=self.hub.assault_group(self.sessions[offset])
            for i in range(offset+1,offset+4):self.send(i,encode_request(JOIN_ROOM,group['id']))
            for i in range(offset,offset+4):self.send(i,encode_request(SET_READY,1))
            self.send(offset,encode_request(START_ROOM))
        self.assertFalse(self.hub.battles)
        self.fixture.tour();self.mono+=2;self.hub.tick()
        self.assertEqual(set(self.hub.battles),set(self.owners))
        return self.hub.battles[self.owners[0]]

    def loaded(self):
        b=self.enter()
        for i in range(8):self.send(i,b'\x36')
        self.hub.tick();return b

    def rows(self,table):
        with closing(sqlite3.connect(self.path)) as db:return list(db.execute('SELECT * FROM '+table))

    def test_native_groups_pair_once_into_shared_original_three_flags(self):
        b=self.enter()
        self.assertEqual((len(b['humans']),len(b['field']._actors),b['bots']),(8,8,set()))
        self.assertEqual((b['field'].width,b['field'].height),(55,33))
        self.assertEqual(len(b['assault_points'].positions),3)
        self.assertEqual(b['room'].request.mode,21)
        self.assertTrue(all(self.hub.battles[o] is b for o in self.owners))
        self.assertEqual(len(battle_checkpoints.read(self.path)),1)
        self.assertEqual(len(self.rows('warfare_matches')),1)
        for o in self.owners:
            packets=self.hub.queues[o]
            self.assertEqual(sum(p[:2]==b'\xc8\x2e' for p in packets),3)
            self.assertIn(b'\x41',packets)

    def test_round_scores_once_not_per_player_or_keepalive(self):
        b=self.loaded();points=b['assault_points'];field=b['field']
        # Pure server-state fixture for the round algorithm; no real-client
        # flag capture is claimed by this test.
        points.owners[:]=[0,None,None]
        for actor in tuple(field._actors.values()):
            field._actors[actor.actor_id]=replace(actor,x=2+actor.owner_id%8,y=2)
        for _ in range(8):
            turn=b['arena']._turns[b['room'].room_id][0]
            index=self.owners.index(turn);self.send(index,encode_end_turn());self.hub.tick()
        self.assertEqual(points.round,1);self.assertEqual(points.scores,[4,0])
        for _ in range(10):self.hub.tick()
        self.assertEqual(points.scores,[4,0])

    def test_deadline_draw_no_capture_no_money_and_exactly_once(self):
        b=self.loaded();balances={s.account:WalletStore(self.path).ensure(s.account) for s in self.sessions}
        self.fixture.now=b['assault_ends']+1;self.mono+=1;self.hub.tick()
        self.assertTrue(b['finished']);self.assertFalse(self.hub.battles)
        self.assertEqual(len(self.rows('warfare_match_receipts')),1)
        self.assertEqual(len(self.rows('battle_rewards')),8)
        self.assertEqual({s.account:WalletStore(self.path).ensure(s.account) for s in self.sessions},balances)
        self.assertTrue(all(any(p[:2]==b'\xc8\x32' for p in b['result_packets'][o]) for o in self.owners))
        self.hub.tick();self.assertEqual(len(self.rows('warfare_match_receipts')),1)
        self.fixture.now=self.fixture.event['ends']+1;self.mono+=2;self.hub.tick()
        self.assertIsNone(self.hub.assault_store.info(11)['claim']['owner_clan'])

    def test_disconnect_crash_reload_retains_map_scores_actors_and_deadline(self):
        b=self.loaded();b['assault_points'].scores[:]=[4,10]
        with self.hub.journal.unit(b):pass
        for s in self.sessions:self.hub.disconnect(s)
        self.fixture.now+=1
        clone=TeamArena(clock=lambda:0);clone.init_assault(self.path,wall=lambda:self.fixture.now)
        clone.journal=BattleJournal(clone,self.path,wall=lambda:self.fixture.now)
        self.assertEqual(clone.journal.recover(),[b['match_id']])
        restored=clone.battles[self.owners[0]]
        self.assertEqual(restored['assault_points'].scores,[4,10])
        self.assertEqual(restored['assault_ends'],b['assault_ends'])
        self.assertEqual(restored['ground'],b['ground'])
        self.assertEqual(set(restored['field']._actors),set(b['field']._actors))
        self.assertTrue(clone.resume(self.sessions[0]))
        self.assertEqual(sum(p[:2]==b'\xc8\x2e' for p in clone.queues[self.owners[0]]),3)

    def test_loading_timeout_aborts_no_territory_scores_and_clears_binding(self):
        b=self.enter();self.mono=b['deadline']+1;self.hub.tick()
        self.assertTrue(b['finished']);self.assertFalse(self.hub.battles)
        self.assertEqual(self.hub.assault_store.matches(b['assault_event'])[0]['status'],'aborted')
        self.assertFalse(self.rows('warfare_scores'))

    def test_group_rejects_travel_and_forged_pet_or_wrong_town(self):
        self.send(0,encode_request(CREATE_ROOM));s=self.sessions[0]
        self.assertTrue(self.hub.busy(s))
        with self.assertRaises(ValueError):s.locations.travel(s.account,b'\x1b'+bytes(8),1,busy=self.hub.busy(s))
        group=self.hub.assault_group(s)
        self.send(0,encode_request(0x20,999))
        self.assertEqual(self.hub.assault_group(s)['members'][0]['pet_ids'],(1,))
        with closing(sqlite3.connect(self.path)) as db,db:LocationStore._save(db,self.sessions[1].account,3,*center(3))
        self.send(1,encode_request(JOIN_ROOM,group['id']))
        self.assertEqual(len(self.hub.assault_group(s)['members']),1)

    def register_both_groups(self):
        for offset in (0,4):
            self.send(offset,encode_request(CREATE_ROOM))
            group=self.hub.assault_group(self.sessions[offset])
            for i in range(offset+1,offset+4):self.send(i,encode_request(JOIN_ROOM,group['id']))
            for i in range(offset,offset+4):self.send(i,encode_request(SET_READY,1))
            self.send(offset,encode_request(START_ROOM))

    def restored_hub(self):
        hub=TeamArena(clock=lambda:self.mono)
        hub.init_assault(self.path,wall=lambda:self.fixture.now)
        hub.journal=BattleJournal(hub,self.path,wall=lambda:self.fixture.now)
        return hub

    def account_progress(self):
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info
        result={}
        for session in self.sessions:
            _,packet,inventory=OwnedPetStore(self.path).list(session.account)[0]
            fields=decode_pet_info(packet,human_equipment=True).fields
            stable={k:fields[k] for k in ('0x8c446f','0x8c4489','0x8c4aef','0x8c4b05','0x8c4ab1','0x8c4a07')}
            # Rank/army counters and AP normalization are normal settlement;
            # unchanged health/XP/gear and balances are the preservation claim.
            result[session.account]=(WalletStore(self.path).ensure(session.account),stable,inventory)
        return result

    def test_deployment_startup_missing_checkpoint_aborts_orphan_without_capture(self):
        battle=self.loaded();match=battle['match_id']
        with closing(sqlite3.connect(self.path)) as db,db:battle_checkpoints.delete(db,match)
        hub=self.restored_hub()
        self.assertEqual(hub.journal.recover(),[])
        hub.recover_assault_bindings();hub.recover_assault_bindings()
        self.assertEqual(hub.assault_store.matches(battle['assault_event'])[0]['status'],'aborted')
        self.assertEqual(len(self.rows('warfare_match_receipts')),1)
        self.assertFalse(self.rows('warfare_scores'))
        self.fixture.now=self.fixture.event['ends']+1;self.mono+=2;hub.tick()
        self.assertFalse(self.rows('warfare_clan_locks'))
        self.assertIsNone(hub.assault_store.info(11)['claim']['owner_clan'])

    def test_deployment_quarantined_checkpoint_preserved_while_orphan_binding_aborted(self):
        battle=self.loaded();match=battle['match_id']
        payload=self.rows('battle_checkpoints')[0][2]
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("UPDATE battle_checkpoints SET checksum=? WHERE match_id=?",('0'*64,match))
        hub=self.restored_hub()
        self.assertEqual(hub.journal.recover(),[])
        hub.recover_assault_bindings()
        saved=self.rows('battle_checkpoints')[0]
        self.assertEqual(saved[2],payload)
        self.assertEqual(saved[5],'quarantined')
        self.assertEqual(len(self.rows('battle_checkpoint_members')),8)
        self.assertTrue(all(battle_checkpoints.blocked(self.path,s.account) for s in self.sessions))
        self.assertFalse(hub.battles)
        self.assertEqual(hub.assault_store.matches(battle['assault_event'])[0]['status'],'aborted')
        self.fixture.now=self.fixture.event['ends']+1;self.mono+=2;hub.tick()
        self.assertFalse(self.rows('warfare_clan_locks'))
        self.assertEqual(self.rows('battle_checkpoints')[0][2],payload)
        self.assertIsNone(hub.assault_store.info(11)['claim']['owner_clan'])

    def test_all_eight_disconnected_grace_expiry_durable_bindings_and_jobs_zero(self):
        from server.battle_reconnect import RECONNECT_SECONDS
        from tio.owned_pets import OwnedPetStore
        battle=self.loaded()
        before=self.account_progress()
        for session in self.sessions:self.hub.disconnect(session)
        self.assertEqual(len(self.hub.offline),8)
        self.assertEqual(len(self.rows('battle_checkpoint_members')),8)
        self.mono+=RECONNECT_SECONDS+1;self.fixture.now+=RECONNECT_SECONDS+1
        self.hub.tick()
        for table in ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs','warfare_scores'):
            self.assertEqual(self.rows(table),[],table)
        self.assertFalse(self.hub.battles);self.assertFalse(self.hub.completed)
        self.assertFalse(self.hub.offline);self.assertFalse(self.hub.players)
        self.assertEqual(len(self.rows('battle_rewards')),8)
        self.assertEqual(self.hub.assault_store.matches(battle['assault_event'])[0]['status'],'aborted')
        self.assertEqual(self.account_progress(),before)
        self.hub.tick();self.assertEqual(len(self.rows('battle_rewards')),8)
        self.fixture.now=self.fixture.event['ends']+1;self.mono+=2;self.hub.tick()
        self.assertFalse(self.rows('warfare_clan_locks'))
        self.assertIsNone(self.hub.assault_store.info(11)['claim']['owner_clan'])

    def test_birth_failure_rolls_back_bound_match_scene_and_preserves_accounts(self):
        from unittest.mock import patch
        from tio.owned_pets import OwnedPetStore
        self.register_both_groups()
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.sessions}
        self.fixture.tour();self.mono+=2
        with patch.object(self.hub,'send_scene',side_effect=ValueError('isolated scene serialization failure')):
            self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.assertEqual(self.rows('battle_checkpoints'),[])
        self.assertEqual(self.rows('battle_checkpoint_members'),[])
        match=self.hub.assault_store.matches(self.fixture.event['id'])[0]
        self.assertEqual(match['status'],'cancelled');self.assertIsNone(match['match_id'])
        self.assertEqual(self.rows('warfare_match_receipts'),[])
        self.assertTrue(all(self.hub.assault_group(s)['status']=='open' for s in self.sessions))
        self.assertEqual({s.account:OwnedPetStore(self.path).list(s.account) for s in self.sessions},before)

    def test_no_journal_rejects_birth_before_binding_any_real_match(self):
        self.register_both_groups();self.hub.journal=None
        self.fixture.tour();self.mono+=2;self.hub.tick()
        self.assertFalse(self.hub.battles)
        matches=self.hub.assault_store.matches(self.fixture.event['id'])
        self.assertEqual(len(matches),1)
        self.assertEqual((matches[0]['status'],matches[0]['match_id']),('cancelled',None))
        self.assertEqual(self.rows('battle_checkpoints'),[])

    def test_retired_owner_native_damage_survives_forget_recovery_and_final_report(self):
        from random import Random
        from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
        battle=self.loaded();field=battle['field']
        owner=battle['arena']._turns[battle['room'].room_id][0]
        index=self.owners.index(owner);attacker=field.actor(field.actor_ids(owner)[0])
        enemy=next(o for o in self.owners if not field.allied(o,owner))
        victim=field.actor(field.actor_ids(enemy)[0])
        occupied={(a.x,a.y) for a in field._actors.values()
                  if a.actor_id not in (attacker.actor_id,victim.actor_id)}
        unavailable=field.blocked|occupied
        cells=next(((x,y),(x+dx,y+dy))
                   for y in range(field.height) for x in range(field.width)
                   for dx,dy in ((0,1),(1,0))
                   if (x,y) not in unavailable and field.inside(x+dx,y+dy)
                   and (x+dx,y+dy) not in unavailable)
        origin,near=cells
        # Position both actors in free adjacent cells of this isolated fixture;
        # authored spawn neighbours may all be blocked or occupied. Normal
        # health, unarmed weapon, AP and damage code remain unchanged.
        with self.hub.journal.unit(battle):
            field._actors[attacker.actor_id]=replace(attacker,x=origin[0],y=origin[1])
            field._actors[victim.actor_id]=replace(victim,x=near[0],y=near[1])
            field.combat.rng=Random(1)
            for view in battle['views'].values():view.refresh()
        replies=self.send(index,encode_attack_request(AttackRequest(attacker.actor_id,*near)))
        result=decode_attack_result(next(p for p in replies if p[:1]==b'\x4b'))
        self.assertTrue(any(h.damage>0 for h in result.hits))
        damage=field.combat.statistics[owner]['damage_dealt'];self.assertGreater(damage,0)
        account=self.sessions[index].account
        self.send(index,b'\x2a\x01');self.hub.forget(owner)
        with self.hub.journal.unit(battle):pass
        self.assertNotIn(owner,self.hub.players)
        self.assertEqual(len(self.rows('battle_checkpoint_members')),7)
        restored=self.restored_hub();self.assertEqual(restored.journal.recover(),[battle['match_id']])
        restored.recover_assault_bindings()
        clone=next(iter(restored.battles.values()))
        self.assertEqual(clone['field'].combat.statistics[owner]['damage_dealt'],damage)
        self.assertEqual(len(clone['reward_roster']),8)
        self.assertEqual(clone['durable_sessions'][owner]['account'],account)
        self.fixture.now=clone['assault_ends']+1
        restored.tick()
        receipt=clone['assault_receipt']
        self.assertEqual(receipt['accounts'][account]['damage_dealt'],damage)
        self.assertEqual(set(receipt['accounts']),{s.account for s in self.sessions})
        self.assertEqual(len(self.rows('battle_rewards')),8)
        restored.tick();self.assertEqual(len(self.rows('warfare_match_receipts')),1)

    def test_finish_then_treat_in_persisted_group(self):
        import struct
        from tio.battle_recovery import CREDITS_PER_HP
        from tio.matchmaking import SearchTicket
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.asset_count import decode_asset_count
        from tio.protocol.pet_info import decode_pet_info
        battle=self.loaded();field=battle['field'];owner=self.owners[0]
        session=self.sessions[0];identity=field.actor_ids(owner)[0]
        actor=field.actor(identity)
        # An isolated journaled wound, without changing maximum HP or AP.
        with self.hub.journal.unit(battle):
            field._actors[identity]=replace(actor,health=actor.health-10)
        self.fixture.now=battle['assault_ends']+1;self.hub.tick()
        self.send(0,b'\x2a\x01')
        group=self.hub.assault_group(session);self.assertEqual(group['status'],'open')
        self.assertTrue(self.hub.busy(session));self.assertNotIn(owner,self.hub.battles)
        self.assertEqual(session._battle_treatment_ids[identity],1)
        request=b'\x7c\x01'+struct.pack('<I',identity)
        def progress():
            pet=decode_pet_info(OwnedPetStore(self.path).list(session.account)[0][1],human_equipment=True)
            return pet.fields['0x8c4ab1'],pet.fields['0x8c4a07'],WalletStore(self.path).ensure(session.account).credits
        before=progress();self.assertEqual(before[0],before[1]-10)
        for status in ('paired','running'):
            with self.subTest(blocked_group=status):
                with closing(sqlite3.connect(self.path)) as db,db:
                    db.execute('UPDATE warfare_groups SET status=? WHERE id=?',(status,group['id']))
                try:
                    self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(0,request)))
                    self.assertEqual(progress(),before)
                finally:
                    with closing(sqlite3.connect(self.path)) as db,db:
                        db.execute("UPDATE warfare_groups SET status='open' WHERE id=?",(group['id'],))
        self.hub.lobbies.create(owner,1,1,1)
        try:
            self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(0,request)))
            self.assertEqual(progress(),before)
        finally:self.hub.lobbies.leave(owner)
        self.hub.ranked_waiting[owner]=SearchTicket(owner,(1,),(4,),self.mono)
        try:
            self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(0,request)))
            self.assertEqual(progress(),before)
        finally:self.hub.ranked_waiting.pop(owner,None)
        replies=self.send(0,request);cost=10*CREDITS_PER_HP
        self.assertEqual(progress(),(before[1],before[1],before[2]-cost))
        self.assertEqual(decode_asset_count(next(p for p in replies if p[:2]==b'\xc8\x39')).credits,before[2]-cost)
        self.send(0,request);self.assertEqual(progress(),(before[1],before[1],before[2]-cost))
        self.assertEqual(self.hub.assault_group(session)['id'],group['id'])
        self.assertEqual(self.hub.assault_group(session)['status'],'open')

    def test_native_move_from_authored_spawn_captures_flag_at_accepted_endpoint(self):
        from collections import deque
        from unittest.mock import patch
        import struct
        from tio.assault_map import generate
        from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
        # A fixed original scene makes this local regression reproducible;
        # actors are never teleported or given extra AP/HP/equipment.
        with patch('tio.assault_map.generate',side_effect=lambda **kw:generate(0,**kw)):
            battle=self.loaded()
        field=battle['field'];points=battle['assault_points']
        owner=battle['arena']._turns[battle['room'].room_id][0]
        index=self.owners.index(owner);identity=field.actor_ids(owner)[0]
        origin=field.actor(identity);move_replies=0
        def route():
            actor=field.actor(identity);start=(actor.x,actor.y)
            blocked=field.blocked|{(a.x,a.y) for a in field._actors.values() if a.actor_id!=identity and a.health}
            parents={start:None};queue=deque([start])
            while queue:
                x,y=queue.popleft()
                target=next((i for i,(fx,fy) in enumerate(points.positions) if abs(x-fx)+abs(y-fy)<=2),None)
                if target is not None:
                    path=[];cursor=(x,y)
                    while cursor!=start:path.append(cursor);cursor=parents[cursor]
                    return target,tuple(reversed(path))
                for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    p=(x+dx,y+dy)
                    if p in parents or p in blocked or not field.inside(*p):continue
                    if dx and dy and ((x+dx,y) in blocked or (x,y+dy) in blocked):continue
                    parents[p]=(x,y);queue.append(p)
            self.fail('Original scene has no collision-safe flag route')
        reached=None
        for _ in range(80):
            turn=battle['arena']._turns[battle['room'].room_id][0]
            if turn==owner:
                target,path=route()
                if not path:reached=target;break
                actor=field.actor(identity);prefix=path[:actor.action_points//field.step_cost]
                if prefix:
                    replies=self.send(index,encode_move_request(BattleMove(identity,prefix)))
                    move=decode_battle_move(next(p for p in replies if p[:1]==b'\x3d'))
                    self.assertEqual((field.actor(identity).x,field.actor(identity).y),move.path[-1]);move_replies+=1
                    if abs(move.path[-1][0]-points.positions[target][0])+abs(move.path[-1][1]-points.positions[target][1])<=2:
                        reached=target
                        flags=[struct.unpack('<ffI',p[2:]) for p in replies if p[:2]==b'\xc8\x2e']
                        self.assertIn((*map(float,points.positions[target]),field.teams[owner]+1),flags)
                        break
            # A full AP move automatically ends the turn. Sending an extra
            # EndTurn would deliberately fail and replace the graph on rollback.
            if battle['room'].room_id in battle['arena']._turns:
                self.send(self.owners.index(turn),encode_end_turn())
            self.hub.tick()
        self.assertIsNotNone(reached);self.assertGreater(move_replies,0)
        self.assertEqual(points.owners[reached],field.teams[owner])
        self.assertEqual(field.actor(identity).health,origin.health)
        self.assertLessEqual(move_replies,10)
