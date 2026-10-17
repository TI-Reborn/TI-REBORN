import json
import sqlite3
import time
import unittest
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import test_multi_account as wire
from test_combat import item,FixedRandom
from tio.combat_rolls import burst
from tio.combat import Combat
from tio.battle_state import BattleActor,BattleField
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import encode_item_list,decode_item_list
from tio.protocol.battle_attack import AttackRequest,decode_attack_result
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.abilities import AbilityEntry
from tio.abilities import AbilityCatalog,AbilityLevel


class RollsTests(unittest.TestCase):
    def test_partial_burst_full_miss_and_full_hit_keep_whole_burst_scale(self):
        rolls=iter([0,99,0,99,0])
        rng=SimpleNamespace(randrange=lambda n:next(rolls),randint=lambda a,b:50)
        self.assertEqual(burst(rng,50,75,65,5,0),(30,True,False))
        for roll,expected in ((99,(0,False,False)),(10,(53,True,False))):
            rng=SimpleNamespace(randrange=lambda n:roll,randint=lambda a,b:53)
            self.assertEqual(burst(rng,50,75,65,5,0),expected)

    def setup_scene(self,weapon=301):
        f=BattleField(24,24,[BattleActor(1,7,2,2,40,100,100,sight_radius=20),
            BattleActor(2,8,5,2,40,1000,1000),BattleActor(3,7,7,2,40,1000,1000),
            BattleActor(4,9,9,2,40,1000,1000),BattleActor(5,9,8,3,40,1000,1000)],step_cost=1)
        c=f.combat=Combat(f,WeaponCatalog(),rng=FixedRandom())
        ammo=c.catalog.weapons[weapon].ammo_id
        c.register(1,encode_item_list(1,(item(100,weapon,equipped=True),item(101,ammo,100))),human=True)
        return f,c

    def test_human_critical_perk_changes_chance_and_real_damage(self):
        raw=json.loads((wire.ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in raw['records'])
        damages=[]
        for rank in (0,4):
            f,c=self.setup_scene()
            c.configure_accuracy(1,() if not rank else (AbilityEntry(4,rank,0),),catalog)
            c.rng=SimpleNamespace(randrange=lambda n:8,randint=lambda a,b:a)
            result=decode_attack_result(c.attack(7,AttackRequest(1,5,2))[0]);damages.append(result.hits[0].damage)
            self.assertEqual(result.flags,4 if rank else 0)
            self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,99)
        self.assertEqual(damages[1],damages[0]*2)

    def test_piercing_line_hits_allies_but_not_off_ray_or_behind_wall(self):
        for weapon in (314,315):
            f,c=self.setup_scene(weapon)
            f.blocked=frozenset({(8,2)})
            result=decode_attack_result(c.attack(7,AttackRequest(1,5,2))[0])
            self.assertEqual({h.actor_id for h in result.hits},{2,3})
            self.assertLess(f.actor(3).health,1000)
            self.assertEqual((f.actor(4).health,f.actor(5).health),(1000,1000))
            self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,100-c.catalog.weapons[weapon].bullets_count)

    def test_attack_commit_failure_leaves_all_targets_ammo_and_stats_unchanged(self):
        f,c=self.setup_scene(314)
        before=(dict(f._actors),dict(c.inventories),dict(c.statistics),list(c.rank_kills))
        with patch.object(c,'_persist_batch',side_effect=ValueError('stale')):
            with self.assertRaisesRegex(ValueError,'stale'):c.attack(7,AttackRequest(1,5,2))
        self.assertEqual((f._actors,c.inventories,c.statistics,c.rank_kills),before)


class ReconnectTests(unittest.TestCase):
    def setUp(self):
        self.c=wire.MultiAccountTests();self.c.setUp();self.addCleanup(self.c.doCleanups)
        self.c.start();self.hub=self.c.server.multi.team_arena
        self.packets={};self.peers={}

    def connect(self,name):
        peer=self.c.handoff(self.c.begin(name));packets=[];original=peer.receive
        def receive():
            packet=original();packets.append(packet);return packet
        peer.receive=receive;self.packets[name]=packets;self.peers[name]=peer
        self.c.enter(peer,name.title());return peer

    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate():
            if time.monotonic()>end:self.fail('condition timeout')
            time.sleep(.01)

    def drop(self,name):
        self.peers[name].sock.close()
        self.wait(lambda:name not in self.c.server.multi.active_accounts)

    def survival(self):
        a=self.connect('alice');b=self.connect('bob')
        for p in (a,b):p.send(b'\xba\x03\0\1')
        for p in (a,b):p.until(b'\x41');p.send(b'\x36')
        with self.hub.lock:
            battle=next(iter(self.hub.battles.values()))
            owner=next(o for o,s in self.hub.players.items() if s.account=='alice')
        self.wait(lambda:bool(battle['arena']._turns))
        with self.hub.lock:turn=battle['arena']._turns[battle['room'].room_id][0]
        if turn!=owner:
            b.until(b'\x38');b.send(b'\x3a'+bytes(4))
        a.until(b'\x38')
        return battle,owner

    def test_reconnect_same_battle_preserves_state_and_does_not_reset_turn(self):
        battle,owner=self.survival();f=battle['field'];arena=battle['arena'];room=battle['room']
        with self.hub.lock:
            identity=f.actor_ids(owner)[0]
            f._actors[identity]=replace(f.actor(identity),health=43,action_points=7)
            before=(f.actor(identity),dict(f.combat.inventories),battle['match_id'])
            deadline=arena._turns[room.room_id][2]
        self.drop('alice')
        self.assertIn(owner,self.hub.offline);self.assertEqual(battle['settled'],set())
        peer=self.connect('alice')
        self.assertIn(b'\x41',self.packets['alice'])
        snapshots=[decode_battle_soldier(p,human_equipment=True) for p in self.packets['alice'] if p[:1]==b'\x3b' and int.from_bytes(p[1:5],'little')==identity]
        self.assertEqual(snapshots[-1].fields['0x8c57bb'],43)
        peer.send(b'\x3a'+bytes(4));peer.until(b'\xf0')
        peer.send(b'\x36');peer.until(b'\x38')
        with self.hub.lock:
            self.assertEqual((f.actor(identity),f.combat.inventories,battle['match_id']),before)
            self.assertLessEqual(arena._turns[room.room_id][2],deadline)
            self.assertEqual(self.hub.identities[self.c.server.multi.active_accounts['alice']],owner)
        self.drop('alice');peer=self.connect('alice');peer.send(b'\x36');peer.until(b'\x38')
        self.assertEqual(battle['settled'],set())

    def test_finished_while_offline_returns_result_without_double_payment(self):
        battle,owner=self.survival();self.drop('alice')
        with self.hub.lock:
            for i in battle['field'].actor_ids(owner):
                battle['field']._actors[i]=replace(battle['field'].actor(i),health=0)
            self.hub.tick()
        self.assertIn(owner,self.hub.completed)
        peer=self.connect('alice');peer.send(b'\x36');peer.until(b'\x4c')
        peer.send(b'\x36');self.c.ping(peer)
        with closing(sqlite3.connect(self.c.config.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_rewards WHERE match_id=?',(battle['match_id'],)).fetchone()[0],2)
        peer.send(b'\x2a\1');self.c.ping(peer)
        self.assertNotIn(owner,self.hub.completed)

    def test_all_offline_expiry_settles_once_without_any_connected_player(self):
        battle,owner=self.survival();self.drop('alice');self.drop('bob')
        with self.hub.lock:
            for i in self.hub.offline:self.hub.offline[i]=time.monotonic()-1
        self.wait(lambda:not self.hub.offline)
        self.assertFalse(self.hub.battles)
        with closing(sqlite3.connect(self.c.config.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_rewards WHERE match_id=?',(battle['match_id'],)).fetchone()[0],2)

    def test_result_disconnect_after_another_player_expired_does_not_notify_stale_session(self):
        battle,owner=self.survival();self.drop('alice')
        with self.hub.lock:
            for i in battle['field'].actor_ids(owner):
                battle['field']._actors[i]=replace(battle['field'].actor(i),health=0)
            self.hub.tick()
            self.hub.offline[owner]=time.monotonic()-1
            self.hub.expire_reconnects()
        self.drop('bob')
        self.assertFalse(self.c.errors)
        self.assertEqual(len(self.hub.offline),1)

    def test_shared_mine_reconnect_keeps_instance_and_inventory(self):
        a=self.connect('alice')
        session=self.c.server.multi.active_accounts['alice']
        from tio.locations import center
        with closing(sqlite3.connect(self.c.config.database)) as db,db:
            session.locations._save(db,'alice',13,*center(13))
            raw=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
            p=wire.decode_pet_info(raw,human_equipment=True)
            p=replace(p,fields={**p.fields,'0x8c4aef':4,'0x8c4a07':100,'0x8c4ab1':100})
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=1",(wire.encode_pet_info(p),))
        a.send(b'\xb0\x14\1');a.until(b'\x41');a.send(b'\x36');a.until(b'\x38')
        with self.hub.lock:
            owner=self.hub.identities[session];battle=self.hub.battles[owner]
            field=battle['field'];match_id=battle['match_id'];ground=battle['ground']
            inventory=dict(field.combat.inventories);identities=set(field._actors)
            self.assertTrue(field.mining.shared)
            self.assertEqual(field.mining.roles,{owner:1})
            self.assertEqual(field.combat.storage_ids[field.actor_ids(owner)[0]],1)
        self.drop('alice');self.assertIn(owner,self.hub.offline)
        self.assertNotIn('alice',self.hub.private)
        a=self.connect('alice');self.assertIn(b'\x41',self.packets['alice'])
        a.send(b'\x36');a.until(b'\x38')
        fresh=self.c.server.multi.active_accounts['alice']
        with self.hub.lock:
            restored=self.hub.battles[self.hub.identities[fresh]]
            self.assertIs(restored,battle);self.assertIs(restored['field'],field)
            self.assertEqual((restored['match_id'],restored['ground']),(match_id,ground))
            self.assertEqual(set(field._actors),identities)
            self.assertEqual(field.combat.inventories,inventory)

    def test_four_real_players_team_and_battle_chat_isolation(self):
        for name in ('carol','dave','eve'):self.c.accounts.create(name,wire.PASSWORD,character=name.title())
        for name in ('alice','bob','carol','dave','eve'):self.connect(name)
        for name in ('alice','bob'):
            self.peers[name].send(b'\xba\x03\1\1');self.peers[name].until(b'\x25')
        with self.hub.lock:
            rooms={self.hub.players[r.captain].account:r.identity for r in self.hub.lobbies.rooms.values()}
        for name,captain in (('carol','alice'),('dave','bob')):
            p=self.peers[name];p.send(b'\xba\4'+rooms[captain].to_bytes(4,'little'));p.until(b'\x25')
            p.send(b'\x2c\1');self.c.ping(p)
        for name in ('alice','bob'):self.peers[name].send(b'\x2e')
        for name in ('alice','bob','carol','dave'):
            p=self.peers[name];p.until(b'\x41',max_packets=256);p.send(b'\x36')
        self.wait(lambda:any(b['arena']._turns for b in self.hub.battles.values()))
        for channel,text,expected in ((4,'Только союзнику',{'carol'}),(3,'Всем в бою',{'bob','carol','dave'})):
            for values in self.packets.values():values.clear()
            self.peers['alice'].send(bytes((0x21,channel))+text.encode('utf-16-le')+b'\0\0')
            self.c.ping(self.peers['alice'])
            for name,p in self.peers.items():
                self.c.ping(p)
                found=any(x[:1]==b'\x22' and text.encode('utf-16-le') in x for x in self.packets[name])
                self.assertEqual(found,name in expected,name)
        self.peers['eve'].send(b'\x21\4'+ 'Чужой'.encode('utf-16-le')+b'\0\0')
        self.peers['eve'].until(b'\xf0')
