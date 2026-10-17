import json,sqlite3,unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import test_ability_learning
from tio.protocol.abilities import AbilityEntry,decode_abilities
from tio.protocol.ability_cast import AbilityCast
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import encode_item_list
from tio.protocol.battle_attack import AttackRequest
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_door import DoorRequest,encode_door_request
from tio.battle_state import BattleActor,BattleField
from tio.battle_doors import BattleDoors
from tio.battle_rejection import restore_actor
from tio.combat import Combat
from tio.weapons import WeaponCatalog
from tio.dog_abilities import configure,cast_scent,catalog_for_play
from tio.abilities import AbilityCatalog,AbilityLevel

ROOT=Path(__file__).resolve().parents[1]

class Random:
    def __init__(self,roll=50):self.roll=roll
    def randrange(self,n):return self.roll
    def randint(self,a,b):return a


class DogLearningTests(unittest.TestCase):
    setUp=test_ability_learning.AbilityLearningTests.setUp

    def level(self,value):
        with closing(sqlite3.connect(self.path)) as db,db:
            row=db.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=2").fetchone()
            pet=decode_pet_info(row[0],human_equipment=False)
            pet.fields['0x8c4aef']=value
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice' AND pet_id=2",(encode_pet_info(pet),))

    def offers(self):
        return {e.ability_id:e.level for e in decode_abilities(self.service.lists('alice',2)[1])[1]}

    def test_manual_levels_doors_persistence_and_species(self):
        self.level(1);self.assertEqual(set(self.offers()),{4,16,18,26})
        with self.assertRaises(ValueError):self.service.learn('alice',2,14)
        self.level(2);self.assertEqual(set(self.offers()),{4,14,15,16,18,23,26})
        self.service.learn('alice',2,14)
        self.assertNotIn(14,self.offers())
        self.assertNotIn(19,self.offers())
        self.level(3);self.assertIn(12,self.offers());self.assertNotIn(19,self.offers())
        self.level(4);self.assertIn(19,self.offers());self.service.learn('alice',2,19)
        from tio.ability_learning import AbilityLearning
        reopened=AbilityLearning.from_workspace(self.path,ROOT)
        self.assertEqual({e.ability_id for e in reopened.state.read('alice',2)[1]},{14,19})
        human={e.ability_id for e in decode_abilities(reopened.lists('alice',1)[1])[1]}
        self.assertFalse(human&{12,14,15,16,18,19,23,26})
        self.assertNotIn(13,self.offers())

    def test_xml_has_boolean_permissions_and_all_active_cooldowns(self):
        from tools.build_skills_fixture import build
        import xml.etree.ElementTree as ET
        xml,_,_=build(self.service.catalog)
        root=ET.fromstring(xml)
        for ability in (14,19):
            node=root.find(f"skill[@id='{ability}']")
            self.assertEqual(node.find('table').text,'1')
        for ability,ap,cooldown in ((12,5,2),(23,7,3),(26,8,2)):
            node=root.find(f"skill[@id='{ability}']")
            values={e.attrib['key']:e.attrib['val'] for e in node.findall('value')}
            self.assertEqual((values['apConsume'],values['reuseTurns']),(str(ap),str(cooldown)))

    def test_saved_dog_skills_prepare_real_survival_scene(self):
        from tio.squad import SquadStore
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tools.survival_scene import prepare_survival
        for ability in (14,19,12,23,26,15,18,4):
            self.offers();self.service.learn('alice',2,ability)
        squad=SquadStore(self.path);squad.assign('alice',1,0);squad.assign('alice',2,1)
        ticket=SurvivalQueue().join(7,OwnedPetStore(self.path).list('alice'))
        data=json.loads((ROOT/'config/abilities.json').read_text())
        raw=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in data['records'])
        scene=prepare_survival(self.path,'alice',ticket,raw,seed=42)
        self.assertEqual(scene.field.doors.permissions[2],{False,True})
        self.assertIn((2,12),scene.field._dog_rules)
        self.assertIn((2,26),scene.field._dog_rules)
        self.assertIn((2,23),scene.field._healing_rules)
        self.assertEqual(scene.field.combat.defense(2),52)


class DogBattleTests(unittest.TestCase):
    def prepare(self,skills,roll=50):
        f=BattleField(12,12,[BattleActor(1,7,2,2,17,50,100),BattleActor(2,8,3,2,15,1000,1000)],step_cost=1)
        c=f.combat=Combat(f,WeaponCatalog(),rng=Random(roll))
        c.register(1,encode_item_list(1,()),human=False)
        c.register(2,encode_item_list(2,()),human=True)
        data=json.loads((ROOT/'config/abilities.json').read_text())
        catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in data['records'])
        configure(f,7,1,3,tuple(AbilityEntry(i,r,0,int(i in (12,23,26))) for i,r in skills),catalog)
        f.prepare_turn(7,(1,))
        return f,c

    def test_deathbite_damage_ap_cooldown_and_rejections(self):
        for rank,damage in enumerate((80,100,120,140),1):
            f,c=self.prepare(((26,rank),))
            request=AbilityCast(26,1,0,3,2)
            replies=c.cast_deathbite(7,request)
            self.assertEqual([p[0] for p in replies],[0x4b,0x4e,0x30,0x7f])
            self.assertEqual((f.actor(2).health,f.actor(1).action_points),(1000-damage,9))
            snapshot=dict(f._actors)
            with self.assertRaises(ValueError):c.cast_deathbite(7,request)
            self.assertEqual(f._actors,snapshot)
            f.prepare_turn(7,(1,))
            with self.assertRaises(ValueError):c.cast_deathbite(7,request)
            f.prepare_turn(7,(1,));c.cast_deathbite(7,request)
            f.prepare_turn(7,(1,));f.prepare_turn(7,(1,))
            for bad in (replace(request,actor_id=2),replace(request,unknown_u32=1),replace(request,x=10)):
                with self.assertRaises(ValueError):c.cast_deathbite(7,bad)
        f,c=self.prepare(())
        with self.assertRaises(ValueError):c.cast_deathbite(7,AbilityCast(26,1,0,3,2))

    def test_scent_through_wall_presence_only_and_failed_search_cost(self):
        f,c=self.prepare(((12,1),))
        f._actors[2]=replace(f.actor(2),x=5)
        f.blocked=frozenset({(4,2)})
        request=AbilityCast(12,1,0,2,2)
        seen=cast_scent(f,7,request)
        self.assertEqual(int.from_bytes(seen[0][39:43],'little'),0) # no enemy records
        self.assertEqual(f.actor(1).action_points,12)
        with self.assertRaises(ValueError):cast_scent(f,7,request)
        f.prepare_turn(7,(1,));f.prepare_turn(7,(1,))
        f._actors[2]=replace(f.actor(2),x=10)
        empty=cast_scent(f,7,request)
        self.assertNotEqual(empty[0],seen[0])
        self.assertEqual(f.actor(1).health,50)
        self.assertEqual(f.actor(1).action_points,12)
        self.assertEqual(int.from_bytes(empty[0][43:47],'little'),1) # self, not enemy
        self.assertEqual(int.from_bytes(empty[0][47:51],'little'),2) # evade/fail

    def test_passive_armor_accuracy_and_critical_bonus(self):
        f,c=self.prepare(((15,4),(18,4)),roll=90)
        self.assertEqual(c.defense(1),99)
        c.attack(7,AttackRequest(1,3,2)) # 85+10 accuracy, roll90 hits
        self.assertEqual(f.actor(2).health,950)
        f,c=self.prepare(((4,4),),roll=8) # source fangs5 + perk4 > roll8
        result=c.attack(7,AttackRequest(1,3,2))
        self.assertEqual(f.actor(2).health,900)
        self.assertEqual(int.from_bytes(result[0][35:39],'little'),4)
        self.assertEqual(int.from_bytes(result[0][47:51],'little'),4)
        f,c=self.prepare((),roll=8)
        c.attack(7,AttackRequest(1,3,2));self.assertEqual(f.actor(2).health,950)

    def test_healing_all_ranks_with_native_animation_and_cap(self):
        for rank,heal in enumerate((12,20,27,35),1):
            f,c=self.prepare(((23,rank),))
            result=f.cast_healing(7,AbilityCast(23,1,0,2,2),with_packets=True)
            self.assertEqual([p[0] for p in result],[0x4b,0x4e,0x4e,0x7f])
            self.assertEqual(f.actor(1).health,50+heal)
            self.assertEqual(f.actor(1).action_points,10)
            with self.assertRaises(ValueError):f.cast_healing(7,AbilityCast(23,1,0,2,2))

    def test_rejected_door_or_path_restore_and_next_move(self):
        f,c=self.prepare(())
        f._actors[2]=replace(f.actor(2),x=8)
        f.doors=BattleDoors(f,((3,2,False),),{1:frozenset()})
        door=DoorRequest(1,True,3,2)
        with self.assertRaises(ValueError):f.doors.change(7,door)
        for packet in (encode_door_request(door),encode_move_request(BattleMove(1,((3,2),)))):
            reply=restore_actor(f,7,packet)
            self.assertEqual(decode_battle_move(reply[0]),BattleMove(1,((2,2),(2,2))))
            self.assertEqual(f.actor(1).action_points,17)
            self.assertEqual(restore_actor(f,8,packet),())
        f.move(7,BattleMove(1,((2,3),)))
        self.assertEqual((f.actor(1).x,f.actor(1).y),(2,3))
        self.assertFalse(f.doors.states[(3,2)])


if __name__=='__main__':unittest.main()
