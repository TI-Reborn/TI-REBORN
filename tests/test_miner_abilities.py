import json,sqlite3,struct,unittest
from pathlib import Path
from contextlib import closing
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace
import test_miners
ROOT=test_miners.ROOT
from test_combat import item,FixedRandom
from tio.ability_learning import AbilityLearning
from tio.protocol.abilities import AbilityEntry,decode_abilities,encode_ability_request
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.protocol.ability_cast import AbilityCast,encode_ability_cast
from tio.passive_stats import project_passives
from tio.battle_state import BattleActor,BattleField
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.owned_pets import OwnedPetStore


class MinerAbilityTests(unittest.TestCase):
    setUp=test_miners.MinerTests.setUp
    travel=test_miners.MinerTests.travel

    def miner(self,level=1):
        self.travel(9)
        pet,inventory,_=self.hire.hire('alice',6)
        p=decode_pet_info(pet,human_equipment=True);p.fields['0x8c4aef']=level
        from tio.weapon_proficiency import ProficiencyRules
        from tio.level_progression import normalize
        pet=ProficiencyRules().normalize(normalize(encode_pet_info(p),True),True)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=?',(pet,))
        self.service=AbilityLearning.from_workspace(self.path,ROOT)
        return pet

    def test_dynamic_prices_and_cross_skill_surcharge(self):
        self.miner(4)
        def offers(service):
            return {e.ability_id:e.unknown_u32 for e in decode_abilities(service.lists('alice',1)[1])[1] if e.ability_id!=24}
        self.assertEqual(offers(self.service),{20:300,21:250,22:500})
        other=AbilityLearning.from_workspace(self.path,ROOT);offers(other)
        self.service.learn('alice',1,20)
        self.assertEqual(offers(self.service),{20:945,21:263,22:525})
        with self.assertRaisesRegex(ValueError,'Stale'):other.learn('alice',1,21)
        self.service.learn('alice',1,20)
        self.assertEqual(offers(self.service),{20:2640,21:275,22:550})
        with closing(sqlite3.connect(self.path)) as db,db:
            self.assertEqual(db.execute('SELECT credits FROM wallets').fetchone()[0],6500-300-945)
            db.execute('UPDATE wallets SET credits=100')
        with self.assertRaisesRegex(ValueError,'Insufficient'):self.service.learn('alice',1,22)
        self.assertEqual(self.service.state.read('alice',1)[1][0].level,2)

    def set_level(self,level):
        with closing(sqlite3.connect(self.path)) as db,db:
            packet=db.execute('SELECT pet_packet FROM owned_pets WHERE pet_id=1').fetchone()[0]
            pet=decode_pet_info(packet,human_equipment=True)
            pet.fields['0x8c4aef']=level
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE pet_id=1',(encode_pet_info(pet),))

    def test_tree_exposes_all_ranks_and_enforces_actor_level(self):
        from tio.protocol.binary import Reader
        def rows(packet):
            r=Reader(packet);self.assertEqual(r.u8(),0xaa);self.assertEqual(r.u32(),1)
            result=[(r.u32(),r.u8(),r.u8(),r.u8(),r.u32(),r.u32()) for _ in range(r.u16())]
            r.finish();return result
        self.miner()
        initial=rows(self.service.tree('alice',1))
        self.assertEqual([(a,r,need) for a,r,_,need,_,_ in initial if a!=24],
                         [(a,r,r) for a in (20,21,22) for r in range(1,5)])
        self.assertEqual([(r,need) for a,r,_,need,_,_ in initial if a==24],[(1,2),(2,3),(3,4),(4,5)])
        with patch.object(self.service,'learning_price',return_value=1):
            for rank in range(1,5):
                self.set_level(rank)
                for ability in (20,21,22):
                    tree=rows(self.service.tree('alice',1))
                    self.assertEqual(len(tree),16)
                    self.assertEqual(len(tree),len({(e[0],e[3]) for e in tree}))
                    self.assertEqual([e[1:4] for e in tree if e[0]==ability],
                                     [(r,int(r<rank),r) for r in range(1,5)])
                    reply=self.service.handle('alice',encode_ability_request(1,ability))
                    self.assertEqual([e[1:4] for e in rows(reply[1]) if e[0]==ability],
                                     [(r,int(r<=rank),r) for r in range(1,5)])
                    self.service.tree('alice',1)
                    before=self.service.state.read('alice',1)
                    with self.assertRaises(ValueError):
                        self.service.handle('alice',encode_ability_request(1,ability))
                    self.assertEqual(self.service.state.read('alice',1),before)
            restored=AbilityLearning.from_workspace(self.path,ROOT)
            self.assertEqual([(e[0],e[1],e[2]) for e in rows(restored.tree('alice',1)) if e[0]!=24],
                             [(a,r,1) for a in (20,21,22) for r in range(1,5)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT credits FROM wallets').fetchone()[0],6500-12)

    def test_actor_level_is_rechecked_before_charging(self):
        self.miner(2)
        self.service.tree('alice',1);self.service.learn('alice',1,20)
        self.service.tree('alice',1)
        self.set_level(1)
        before=self.service.state.read('alice',1)
        with self.assertRaisesRegex(ValueError,'Stale'):
            self.service.learn('alice',1,20)
        self.assertEqual(self.service.state.read('alice',1),before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT credits FROM wallets').fetchone()[0],6500-300)

    def test_transaction_engine_with_explicit_test_only_quotes(self):
        # A test-only quote keeps rank mechanics independent of price arithmetic.
        pet=self.miner(4)
        base_hp=decode_pet_info(pet,human_equipment=True).fields['0x8c4a07']
        with patch.object(self.service,'learning_price',return_value=123):
            self.service.tree('alice',1)
            for rank in range(1,5):
                result=self.service.learn('alice',1,20)
                self.assertEqual(decode_abilities(result[0])[1][0].level,rank)
                maximum=decode_pet_info(result[-1],human_equipment=True).fields['0x8c4a07']
                self.assertEqual(maximum,base_hp+(20,28,36,44)[rank-1])
            self.assertNotIn(20,{e.ability_id for e in decode_abilities(self.service.lists('alice',1)[1])[1]})
            with self.assertRaises(ValueError):self.service.learn('alice',1,20)
        self.assertEqual(AbilityLearning.from_workspace(self.path,ROOT).state.read('alice',1)[1][0].level,4)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT credits FROM wallets').fetchone()[0],6500-4*123)

    def test_defense_level_requirements_and_species(self):
        self.miner(5)
        self.travel(3);self.hire.hire('alice',1)
        with patch.object(self.service,'learning_price',return_value=1):
            self.assertNotIn(20,{e.ability_id for e in decode_abilities(self.service.lists('alice',2)[1])[1]})
            for rank in range(1,5):
                self.assertEqual(self.service.required_level(24,rank),rank+1)
                self.service.lists('alice',1);self.service.learn('alice',1,24)
        with self.assertRaises(ValueError):self.service.tree('bob',1)

    def test_passives_each_rank_equipment_and_no_accumulation(self):
        pet=self.miner(5)
        armor=replace(item(999,268),unknown_u8_01=1,location_raw=4)
        # Pick a source-backed miner torso, not an invented item ID.
        from tio.equipment import armor_rules
        identity=next(i for i,r in armor_rules().items() if r.get('miner') and r['slot']==4)
        armor=replace(armor,template_id=identity)
        for rank in range(1,5):
            entries=tuple(AbilityEntry(i,rank,0,0) for i in (20,21,24))
            inv=encode_item_list(1,())
            projected=project_passives(pet,True,entries,self.service.catalog,inventory=inv)
            f=decode_pet_info(projected,human_equipment=True).fields
            self.assertEqual((f['0x8c4a07'],f['0x8c4ab1'],f['0x8c4b57'],f['0x8c4ac5']),
                             (118+(20,28,36,44)[rank-1],98,1200+(60,110,160,210)[rank-1],(52,67,83,99)[rank-1]))
            self.service.state.replace('alice',1,entries,expected_revision=rank-1)
            self.assertEqual(OwnedPetStore(self.path).list('alice')[0][1],projected)
            armored=project_passives(pet,True,entries,self.service.catalog,inventory=encode_item_list(1,(armor,)))
            self.assertEqual(decode_pet_info(armored,human_equipment=True).fields['0x8c4ac5'],0)
            carried=replace(armor,unknown_u8_01=0,location_raw=0)
            carried_pet=decode_pet_info(project_passives(pet,True,entries,self.service.catalog,inventory=encode_item_list(1,(carried,))),human_equipment=True)
            from tio.weight import inventory_weight
            self.assertEqual(carried_pet.fields,{**f,'0x8c4b6d':inventory_weight(encode_item_list(1,(carried,)))})

    def combat(self,rank=1):
        pet=self.miner(5)
        entries=(AbilityEntry(22,rank,0,1),AbilityEntry(24,1,0,0))
        pet=project_passives(pet,True,entries,self.service.catalog)
        actors=[BattleActor(1,7,4,4,14,98,98),BattleActor(2,8,5,4,15,500,500),
                BattleActor(3,8,3,3,15,500,500),BattleActor(4,7,4,5,15,500,500),
                BattleActor(5,8,6,4,15,500,500),BattleActor(6,8,5,5,0,0,500)]
        f=BattleField(10,10,actors,step_cost=1);c=Combat(f,WeaponCatalog(),rng=FixedRandom());f.combat=c
        c.register(1,encode_item_list(1,(item(3001,335,equipped=True),)),human=True,pet_packet=pet)
        for a in actors[1:]:c.register(a.actor_id,encode_item_list(a.actor_id,()),human=True)
        f.configure_miner_slash(7,1,6,entries);f.prepare_turn(7,(1,))
        return f,c

    def test_slash_reports_misses_per_recipient(self):
        from types import SimpleNamespace
        f,c=self.combat()
        rolls=iter((99,0,99,99)) # miss, hit + noncritical, miss
        c.rng=SimpleNamespace(randrange=lambda n:next(rolls),randint=lambda a,b:a)
        packet=c.cast_slash(7,AbilityCast(22,1,0,5,4))[0]
        self.assertEqual(struct.unpack_from('<I',packet,35)[0],0)
        self.assertEqual([struct.unpack_from('<I',packet,47+18*i)[0] for i in range(3)],[2,0,2])
        self.assertEqual((f.actor(2).health,f.actor(4).health),(500,500))
        self.assertLess(f.actor(3).health,500)
        self.assertEqual(f.actor(1).action_points,7)
        with self.assertRaisesRegex(ValueError,'cooling'):c.cast_slash(7,AbilityCast(22,1,0,5,4))

    def test_slash_damage_all_neighbors_cost_and_cooldown(self):
        f,c=self.combat(4)
        replies=c.cast_slash(7,AbilityCast(22,1,0,5,4))
        self.assertEqual(struct.unpack_from('<I',replies[0],23)[0],22)
        self.assertEqual(f.actor(1).action_points,7)
        for i in (2,3,4):self.assertLess(f.actor(i).health,500)
        self.assertEqual((f.actor(1).health,f.actor(5).health,f.actor(6).health),(98,500,0))
        self.assertEqual(c.statistics[7]['damage_dealt'],2*(500-f.actor(2).health))
        self.assertEqual(c.statistics[7]['damage_received'],500-f.actor(4).health)
        for _ in range(2):
            f.prepare_turn(7,(1,))
            with self.assertRaisesRegex(ValueError,'cooling'):c.cast_slash(7,AbilityCast(22,1,0,5,4))
        f.prepare_turn(7,(1,));c.cast_slash(7,AbilityCast(22,1,0,5,4))

    def test_all_slash_percentages_and_blocked_neighbor(self):
        from tio.weapon_proficiency import damage_endpoint
        f,c=self.combat();actors=dict(f._actors)
        profile=c.proficiencies[1];weapon=c.catalog.weapons[335]
        base=damage_endpoint(weapon.damage_base,c.proficiency_rules.value(profile,True,weapon.weapon_type))
        for rank,percent in enumerate((125,145,160,170),1):
            f._actors=dict(actors);f._ability_turns[1]=0;f._cooldowns.clear();c.statistics={}
            c.proficiencies[1]=profile
            f.configure_miner_slash(7,1,6,(AbilityEntry(22,rank,0,1),))
            f.blocked=frozenset({(3,4)})
            c.cast_slash(7,AbilityCast(22,1,0,5,4))
            self.assertEqual(500-f.actor(2).health,base*percent//100)
            # A diagonal neighbor behind a blocking corner receives no damage.
            self.assertEqual(f.actor(3).health,500)

    def test_rejected_slash_has_no_side_effects(self):
        f,c=self.combat()
        def snapshot():return dict(f._actors),dict(f._cooldowns),dict(c.statistics),dict(c.inventories)
        for request,owner in ((AbilityCast(22,1,9,5,4),7),(AbilityCast(22,1,0,6,4),7),
                              (AbilityCast(22,1,0,4,5),7),(AbilityCast(22,1,0,5,4),8)):
            before=snapshot()
            with self.assertRaises(ValueError):c.cast_slash(owner,request)
            self.assertEqual(snapshot(),before)
        c.inventories[1]=encode_item_list(1,())
        with self.assertRaisesRegex(ValueError,'hammer'):c.cast_slash(7,AbilityCast(22,1,0,5,4))
        c.inventories[1]=encode_item_list(1,(item(3001,335,equipped=True),))
        f._actors[1]=replace(f.actor(1),action_points=6)
        with self.assertRaisesRegex(ValueError,'action points'):c.cast_slash(7,AbilityCast(22,1,0,5,4))
        f._actors[1]=replace(f.actor(1),action_points=14)
        with patch.object(c,'_persist_batch',side_effect=sqlite3.OperationalError('failed')):
            before=snapshot()
            with self.assertRaises(sqlite3.OperationalError):c.cast_slash(7,AbilityCast(22,1,0,5,4))
            self.assertEqual(snapshot(),before)

    def test_slash_turn_authority_and_base_defense(self):
        from tio.arena_service import ArenaService
        from tio.protocol.battle_attack import AttackRequest
        f,c=self.combat();arena=ArenaService(clock=lambda:10)
        arena.rooms=SimpleNamespace(snapshot=lambda:(SimpleNamespace(room_id=1,members=(7,8)),))
        arena._fields[1]=f;packet=encode_ability_cast(AbilityCast(22,1,0,5,4))
        with self.assertRaises(ValueError):arena.cast_ability(7,packet)
        arena._turns[1]=(7,{1},9)
        with self.assertRaises(ValueError):arena.cast_ability(7,packet)
        arena._turns[1]=(7,{1},20)
        self.assertEqual(c.defense(1),52)
        c.register(2,encode_item_list(2,()),human=False)
        c.attack(8,AttackRequest(2,4,4))
        self.assertEqual(f.actor(1).health,98-50*100//152)
        arena.cast_ability(7,packet)

    def test_survival_reconnect_profile_and_prepared_skill(self):
        from tio.squad import SquadStore
        from tio.matchmaking import SurvivalQueue
        from tools.survival_scene import prepare_survival
        self.miner(5)
        entries=tuple(AbilityEntry(i,4,0,int(i==22)) for i in (20,21,22,24))
        self.service.state.replace('alice',1,entries,expected_revision=0)
        SquadStore(self.path).assign('alice',1,1)
        ticket=SurvivalQueue().join(42,OwnedPetStore(self.path).list('alice'))
        scene=prepare_survival(self.path,'alice',ticket,self.service.catalog)
        a=scene.field.actor(1)
        self.assertEqual(a.max_health,162) # 98 + four levels*5 + health perk44.
        self.assertEqual(scene.field.combat.defense(1),99)
        self.assertEqual(scene.field._slash_rules[(1,22)],(170,7,3,4))
        self.assertEqual(len(scene.field._slash_rules),2)
        self.assertTrue(scene.field.ability_status_packets(42,(1,)))
