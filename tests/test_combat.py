import unittest
import sqlite3
import tempfile
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from contextlib import closing
from tio.battle_state import BattleActor,BattleField
from tio.weapons import WeaponCatalog
from tio.combat import Combat
from tio.arena_service import ArenaService
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_request
from tio.protocol.item_list import ItemRecord,encode_item_list,decode_item_list


def item(i,template,count=1,equipped=False):
    return ItemRecord(i,template,b'\0'*2,count,int(equipped),16 if equipped else 0,(300,300,300),b'\0'*4,None,b'\0'*3)


class FixedRandom:
    # Deterministic hit without triggering the now-supported base critical.
    def randrange(self,n):return min(10,n-1)
    def randint(self,a,b):return a


class CombatTests(unittest.TestCase):
    def test_result_statistics_friendly_fire_healing_and_failed_attack(self):
        ally=BattleActor(3,7,5,2,15,50,100)
        f,c=self.setup_combat(317,None,extra=(ally,))
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(c.statistics[7],dict(kills=0,losses=1,damage_dealt=99,damage_received=50))
        self.assertEqual(c.statistics[8],dict(kills=0,losses=0,damage_dealt=0,damage_received=99))
        before={k:dict(v) for k,v in c.statistics.items()}
        with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(c.statistics,before)
        # An enemy with one remaining HP yields one damage, not nominal50.
        f._actors[1]=replace(f.actor(1),x=4,y=1)
        c.register(1,encode_item_list(1,()),human=False)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(c.statistics[7]['damage_dealt'],100)
        self.assertEqual(c.statistics[7]['kills'],1)
        self.assertEqual(c.statistics[8]['losses'],1)

    def test_wounded_dog_can_cross_corpse_then_bite(self):
        from tio.protocol.battle_move import BattleMove
        from tio.training_bot import approach_path
        dog=BattleActor(1,7,12,16,17,1,100)
        corpse=BattleActor(2,8,13,16,0,0,100)
        enemy=BattleActor(3,8,13,14,15,100,100)
        f=BattleField(32,32,[dog,corpse,enemy],step_cost=1)
        c=Combat(f,WeaponCatalog(),rng=FixedRandom())
        c.register(1,encode_item_list(1,()),human=False)
        # Corpses must not close narrow paths or diagonal corners.
        f.move(7,BattleMove(1,((13,16),(13,15))))
        c.attack(7,AttackRequest(1,13,14))
        self.assertEqual((f.actor(1).health,f.actor(1).action_points),(1,10))
        self.assertEqual(f.actor(3).health,50)
        with self.assertRaises(ValueError):f.move(7,BattleMove(1,((13,14),)))
        f._actors[1]=dog
        f.blocked=frozenset((x,y) for x in range(32) for y in range(32)
                            if (x,y) not in ((12,16),(13,16),(13,15),(13,14)))
        self.assertEqual(approach_path(f,1,[enemy],{1,2,3}),((13,16),(13,15)))

    def test_medical_action_route_persistence_and_failed_commit(self):
        from tio.protocol.item_action import ItemAction,encode_item_action
        f,c=self.setup_combat()
        f._actors[1]=replace(f.actor(1),health=20,action_points=15)
        c.register(1,encode_item_list(1,(item(200,10,2),)),human=True)
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f;arena._turns={1:(7,{1},20)}
        packet=encode_item_action(ItemAction(1,200,255))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                db.execute('INSERT INTO owned_pets VALUES (?,?,?)',('alice',1,c.inventories[1]))
            c.persistence[1]=(path,'alice')
            replies=arena.equip(7,packet)
            self.assertEqual([p[0] for p in replies],[0x4e,0x4e,0x30])
            self.assertEqual((f.actor(1).health,f.actor(1).action_points),(50,12))
            with closing(sqlite3.connect(path)) as db,db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets').fetchone()[0],replies[-1])
                db.execute('UPDATE owned_pets SET inventory_packet=?',(b'changed',))
            before=(dict(f._actors),c.inventories[1])
            with self.assertRaisesRegex(ValueError,'outside battle'):arena.equip(7,packet)
            self.assertEqual((dict(f._actors),c.inventories[1]),before)

    def test_medical_items_heal_cap_consume_and_reject_atomically(self):
        from tio.protocol.item_action import ItemAction
        for template,power,cost in ((9,10,1),(10,30,3),(11,50,5),(34,13,1)):
            f,c=self.setup_combat()
            f._actors[1]=replace(f.actor(1),health=95,action_points=15)
            c.register(1,encode_item_list(1,(item(200,template,2),)),human=True)
            action=ItemAction(1,200,255)
            replies=c.use_medical(7,action)
            self.assertEqual([p[0] for p in replies],[0x4e,0x4e,0x30])
            self.assertEqual((f.actor(1).health,f.actor(1).action_points),(100,15-cost))
            self.assertEqual(decode_item_list(c.inventories[1])[1][0].count,1)
            before=(dict(f._actors),c.inventories[1])
            with self.assertRaises(ValueError):c.use_medical(7,action)
            self.assertEqual((dict(f._actors),c.inventories[1]),before)
            f._actors[1]=replace(f.actor(1),health=20,action_points=cost)
            c.use_medical(7,action)
            self.assertEqual((f.actor(1).health,f.actor(1).action_points),(20+power,0))
            self.assertEqual(decode_item_list(c.inventories[1])[1],())
        for health,ap,owner in ((0,15,7),(20,0,7),(20,15,8)):
            f,c=self.setup_combat()
            f._actors[1]=replace(f.actor(1),health=health,action_points=ap)
            c.register(1,encode_item_list(1,(item(200,9),)),human=True)
            before=(dict(f._actors),c.inventories[1])
            with self.assertRaises(ValueError):c.use_medical(owner,ItemAction(1,200,255))
            self.assertEqual((dict(f._actors),c.inventories[1]),before)

    def test_secondary_slot_swap_and_attack_uses_active_weapon(self):
        from tio.protocol.item_action import ItemAction
        f,c=self.setup_combat()
        _,items,_=decode_item_list(c.inventories[1])
        c.register(1,encode_item_list(1,(*items,item(202,317))),human=True)
        c.equip(7,ItemAction(1,202,7))
        self.assertEqual(f.actor(1).weapons[0].template_id,301)
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f;arena._turns={1:(7,{1},20)}
        for packet in (b'\x6d\x01',b'\x6d\x01\0\0\0\0',b'\x6d\x02\0\0\0'):
            with self.assertRaises(ValueError):arena.swap_weapons(7,packet)
        replies=arena.swap_weapons(7,b'\x6d\x01\0\0\0')
        self.assertEqual([p[0] for p in replies],[0x30,0x4e])
        self.assertEqual(f.actor(1).action_points,39)
        self.assertEqual(f.actor(1).weapons[0].template_id,317)
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual(f.actor(1).action_points,32)
        self.assertEqual(f.actor(2).health,1)
        c.swap_weapons(7,1)
        self.assertEqual(f.actor(1).weapons[0].template_id,301)
        self.assertEqual(f.actor(1).action_points,31)
        f._actors[1]=replace(f.actor(1),action_points=0)
        before=c.inventories[1]
        with self.assertRaises(ValueError):c.swap_weapons(7,1)
        self.assertEqual(c.inventories[1],before)

    def test_switch_to_grenade_then_throw_persists_and_consumes(self):
        from tio.protocol.item_action import ItemAction,encode_item_action
        f,c=self.setup_combat()
        _,items,unknown=decode_item_list(c.inventories[1])
        c.register(1,encode_item_list(1,(*items,item(102,317),item(103,317)),unknown),human=True)
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f
        arena._turns={1:(7,{1},20)}
        action=encode_item_action(ItemAction(1,102,4))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                db.execute('INSERT INTO owned_pets VALUES (?,?,?)',('alice',1,c.inventories[1]))
            c.persistence[1]=(path,'alice')
            before=c.inventories[1]
            with self.assertRaises(ValueError):arena.equip(8,action)
            self.assertEqual(c.inventories[1],before)
            arena.equip(7,action)
            self.assertEqual(f.actor(1).weapons[0].template_id,317)
            self.assertEqual(f.actor(1).action_points,40)
            arena.attack(7,encode_attack_request(AttackRequest(1,5,1)))
            self.assertEqual((f.actor(2).health,f.actor(1).action_points),(1,33))
            remaining=decode_item_list(c.inventories[1])[1]
            self.assertEqual({i.instance_id for i in remaining},{100,101,103})
            self.assertEqual(next(i.count for i in remaining if i.template_id==3),2)
            with closing(sqlite3.connect(path)) as db,db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets').fetchone()[0],c.inventories[1])
                db.execute('UPDATE owned_pets SET inventory_packet=?',(before,))
            state=(dict(f._actors),c.inventories[1])
            with self.assertRaisesRegex(ValueError,'outside battle'):
                arena.equip(7,encode_item_action(ItemAction(1,100,4)))
            self.assertEqual((dict(f._actors),c.inventories[1]),state)

    def test_dog_bite_adjacent_diagonal_and_no_ammunition(self):
        for x,y in ((2,1),(2,2),(1,2)):
            with self.subTest(target=(x,y)):
                f,c=self.setup_combat(ammo=None)
                f._actors[2]=replace(f.actor(2),x=x,y=y)
                inventory=encode_item_list(1,(item(200,203,equipped=True),))
                c.register(1,inventory,human=False)
                result=c.attack(7,AttackRequest(1,x,y))
                self.assertEqual(f.actor(2).health,50)
                self.assertEqual(f.actor(1).action_points,35)
                self.assertEqual(c.inventories[1],inventory)
                self.assertEqual(int.from_bytes(result[0][21:23],'little'),333)
                self.assertEqual(f.actor(1).weapons[0].template_id,333)

    def test_dog_cannot_bite_two_cells_away_or_through_corner(self):
        for target,blocked in (((3,1),()),((2,2),((2,1),))):
            f,c=self.setup_combat(ammo=None,blocked=blocked)
            f._actors[2]=replace(f.actor(2),x=target[0],y=target[1])
            c.register(1,encode_item_list(1,()),human=False)
            before=dict(f._actors)
            with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,*target))
            self.assertEqual(f._actors,before)

    def test_xml_bindings_match_server_catalog(self):
        import xml.etree.ElementTree as ET
        root=ET.parse(Path(__file__).resolve().parents[1]/'evidence/items_diagnostic.xml').getroot()
        catalog=WeaponCatalog()
        for weapon in (301,303,317):
            node=root.find(f"item[@id='{weapon}']")
            self.assertEqual(node.find("value[@key='attackType']").get('val'),catalog.sources[weapon]['weaponAttack'])
            consume=node.find('for/consume')
            self.assertEqual(int(consume.get('id')),317 if weapon==317 else catalog.weapons[weapon].ammo_id)
            self.assertEqual(int(consume.get('amount')),catalog.weapons[weapon].bullets_count)

    def setup_combat(self,weapon=301,ammo=3,count=2,*,blocked=(),extra=()):
        a=BattleActor(1,7,1,1,40,100,100)
        b=BattleActor(2,8,5,1,40,100,100)
        f=BattleField(20,20,[a,b,*extra],blocked=blocked,step_cost=1)
        c=Combat(f,WeaponCatalog(),rng=FixedRandom())
        items=[item(100,weapon,equipped=True)]
        if ammo:items.append(item(101,ammo,count))
        c.register(1,encode_item_list(1,items),human=True)
        f.combat=c
        return f,c

    def test_shot_ap_damage_and_last_round(self):
        f,c=self.setup_combat()
        for hp,ap in ((84,37),(68,34)):
            packets=c.attack(7,AttackRequest(1,5,1))
            self.assertEqual([p[0] for p in packets],[0x4b,0x4e,0x30])
            self.assertEqual((f.actor(2).health,f.actor(1).action_points),(hp,ap))
        before=(dict(f._actors),c.inventories[1])
        with self.assertRaisesRegex(ValueError,'ammunition'):c.attack(7,AttackRequest(1,5,1))
        self.assertEqual((f._actors,c.inventories[1]),before)
        self.assertEqual([i.template_id for i in decode_item_list(c.inventories[1])[1]],[301])

    def test_burst_combines_ammo_stacks(self):
        f,c=self.setup_combat(303,3,3)
        _,items,_=decode_item_list(c.inventories[1])
        c.inventories[1]=encode_item_list(1,(*items,item(102,3,4),item(103,7,50)))
        c.attack(7,AttackRequest(1,5,1))
        amounts={i.instance_id:i.count for i in decode_item_list(c.inventories[1])[1]}
        self.assertNotIn(101,amounts)
        self.assertEqual((amounts[102],amounts[103]),(2,50))

    def test_rejections_are_atomic(self):
        for case in ('wrong_ammo','ap','wall','owner','dead','range','unknown'):
            with self.subTest(case=case):
                f,c=self.setup_combat(ammo=7 if case=='wrong_ammo' else 3,blocked={(3,1)} if case=='wall' else ())
                if case=='ap':f._actors[1]=replace(f.actor(1),action_points=2)
                if case=='dead':f._actors[1]=replace(f.actor(1),health=0)
                before=(dict(f._actors),c.inventories[1])
                request=AttackRequest(99 if case=='unknown' else 1,15 if case=='range' else 5,1)
                with self.assertRaises(ValueError):c.attack(99 if case=='owner' else 7,request)
                self.assertEqual((f._actors,c.inventories[1]),before)

    def test_grenade_blast_friend_damage_cover_and_consumption(self):
        ally=BattleActor(3,7,5,2,40,50,50)
        covered=BattleActor(4,8,7,1,40,100,100)
        f,c=self.setup_combat(317,None,extra=(ally,covered),blocked={(6,1)})
        c.attack(7,AttackRequest(1,5,1))
        self.assertEqual((f.actor(2).health,f.actor(3).health,f.actor(4).health),(1,0,100))
        self.assertEqual(f.actor(1).action_points,33)
        self.assertEqual(decode_item_list(c.inventories[1])[1],())
        self.assertEqual(f.actor(1).weapons[0].template_id,300)
        with self.assertRaises(ValueError):c.attack(7,AttackRequest(1,5,1))

    def test_miss_still_consumes_ammo_and_ap(self):
        f,c=self.setup_combat()
        c.rng=SimpleNamespace(randrange=lambda n:99,randint=lambda a,b:a)
        packet=c.attack(7,AttackRequest(1,5,1))[0]
        self.assertEqual(int.from_bytes(packet[35:39],'little'),2)
        self.assertEqual(int.from_bytes(packet[47:51],'little'),2)
        self.assertEqual(int.from_bytes(packet[51:53],'little'),0)
        self.assertEqual(f.actor(2).health,100)
        self.assertEqual(f.actor(1).action_points,37)
        self.assertEqual(decode_item_list(c.inventories[1])[1][1].count,1)

    def test_original_accuracy_boundaries_for_shots_melee_and_bites(self):
        # Source items.cfg values, including unarmed humans and miners.
        for weapon,accuracy in ((301,70),(304,89),(326,85),(300,90),(337,90),(335,95),(333,85)):
            for roll in (accuracy-1,accuracy):
                with self.subTest(weapon=weapon,roll=roll):
                    catalog=WeaponCatalog();w=catalog.weapons[weapon]
                    f,c=self.setup_combat(weapon,w.ammo_id,count=100)
                    f._actors[1]=replace(f.actor(1),x=4)
                    if weapon==333:c.register(1,encode_item_list(1,()),human=False)
                    c.rng=SimpleNamespace(randrange=lambda n:roll,randint=lambda a,b:a)
                    packet=c.attack(7,AttackRequest(1,5,1))[0]
                    hit=roll<accuracy
                    self.assertEqual(f.actor(2).health<100,hit)
                    self.assertEqual(int.from_bytes(packet[35:39],'little'),0 if hit else 2)
                    self.assertEqual(int.from_bytes(packet[47:51],'little'),0 if hit else 2)
                    self.assertEqual(f.actor(1).action_points,40-w.attack_ap)

    def test_accuracy_cap_and_zero_damage_are_not_confused_with_miss(self):
        for dog in (False,True):
            for roll in (94,95):
                f,c=self.setup_combat()
                f._actors[1]=replace(f.actor(1),x=4)
                if dog:
                    c.register(1,encode_item_list(1,()),human=False)
                    c.dog_bonuses[1]={18:20}
                else:c.catalog.sources[301]={**c.catalog.sources[301],'accuracy':100}
                c.rng=SimpleNamespace(randrange=lambda n:roll,randint=lambda a,b:a)
                packet=c.attack(7,AttackRequest(1,5,1))[0]
                self.assertEqual(f.actor(2).health<100,roll==94)
                self.assertEqual(int.from_bytes(packet[35:39],'little'),0 if roll==94 else 2)
        f,c=self.setup_combat()
        c.catalog.weapons[301]=replace(c.catalog.weapons[301],damage_base=0,damage_random=0)
        packet=c.attack(7,AttackRequest(1,5,1))[0]
        self.assertEqual(f.actor(2).health,100)
        self.assertEqual(int.from_bytes(packet[35:39],'little'),0)
        self.assertEqual(int.from_bytes(packet[47:51],'little'),0)

    def test_inventory_commit_and_stale_snapshot(self):
        f,c=self.setup_combat()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'state.db'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,inventory_packet BLOB)')
                db.execute('INSERT INTO owned_pets VALUES (?,?,?)',('alice',1,c.inventories[1]))
            c.persistence[1]=(path,'alice')
            c.attack(7,AttackRequest(1,5,1))
            with closing(sqlite3.connect(path)) as db,db:
                self.assertEqual(db.execute('SELECT inventory_packet FROM owned_pets').fetchone()[0],c.inventories[1])
                db.execute('UPDATE owned_pets SET inventory_packet=?',(b'changed',))
            before=(dict(f._actors),c.inventories[1])
            with self.assertRaisesRegex(ValueError,'outside battle'):c.attack(7,AttackRequest(1,5,1))
            self.assertEqual((f._actors,c.inventories[1]),before)

    def test_turn_authority_and_packet_validation(self):
        f,c=self.setup_combat()
        arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f
        packet=encode_attack_request(AttackRequest(1,5,1))
        self.assertEqual(decode_attack_request(packet),AttackRequest(1,5,1))
        for suffix in (b'\0',):
            with self.assertRaises(ValueError):decode_attack_request(packet+suffix)
        for turn in (None,(8,{1},20),(7,{2},20),(7,{1},10)):
            arena._turns={} if turn is None else {1:turn}
            with self.assertRaises(ValueError):arena.attack(7,packet)
        arena._turns={1:(7,{1},20)}
        self.assertEqual(arena.attack(7,packet)[0][0],0x4b)
        # A later inventory request returns the remaining round, not the city
        # entry snapshot; duplicate or foreign actor IDs expose no extra bags.
        replies=arena.inventory_packets(7,(1,1,2,999))
        self.assertEqual(len(replies),1)
        self.assertEqual(sum(i.count for i in decode_item_list(replies[0])[1] if i.template_id==3),1)
