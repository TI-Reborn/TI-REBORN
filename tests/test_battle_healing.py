import unittest
from tio.battle_state import BattleActor,BattleField
from tio.protocol.ability_cast import AbilityCast
from tio.protocol.battle_move import BattleMove

class BattleHealingTests(unittest.TestCase):
    def test_learned_rule_and_authoritative_turn(self):
        from tio.arena_service import ArenaService
        from tio.abilities import AbilityCatalog,AbilityLevel
        from tio.protocol.abilities import AbilityEntry
        from tio.protocol.ability_cast import encode_ability_cast
        from tio.protocol.ability_status import decode_ability_status,AbilityStatus
        from tio.protocol.health import encode_health
        from tio.protocol.action_points import encode_action_points
        from tio.protocol.battle_turn import encode_end_turn
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        from tio.protocol.battle_ground import BattleGround,encode_battle_ground
        catalog=AbilityCatalog([AbilityLevel(23,1,{'name':'Dog Cure','levels':'4','value':'12','AP':'7','Cooldown':'3'}),
                                AbilityLevel(23,2,{'name':'Dog Cure','levels':'4','value':'20','AP':'7'})])
        f=self.field()
        for resource,entries in [(1,[AbilityEntry(23,1,0,1)]),(3,[]),(3,[AbilityEntry(23,2,0,1)])]:
            with self.assertRaises(ValueError):f.configure_dog_healing(1,4,resource,entries,catalog)
        f.configure_dog_healing(1,4,3,[AbilityEntry(23,1,0,1)],catalog)
        now=[0];service=ArenaService(clock=lambda:now[0])
        service.create(1,b'Owner',encode_create_request(ArenaCreateRequest(0,1,2,2,40,1,1,0,0)))
        ground=encode_battle_ground(BattleGround(0,8,8,bytes(64),(),bytes(64)))
        service.start_loading(1,b'\x2e',lambda room:(ground,b'\x41'))
        service.configure_field(1,f);service.member_loaded(1,b'\x36')
        wire=encode_ability_cast(AbilityCast(23,4,0,2,3))
        with self.assertRaises(ValueError):service.cast_healing(1,wire)
        initial=service.begin_turn_packets(1,[4],40)
        self.assertEqual(decode_ability_status(initial[-2]),(4,(AbilityStatus(23,1,4,0),)))
        self.assertEqual(initial[-1][0],0x38)
        with self.assertRaises(ValueError):service.cast_healing(2,wire)
        from unittest.mock import patch
        before=f.actor(4)
        with patch('tio.protocol.ability_status.encode_ability_status',side_effect=ValueError('serialize failed')):
            with self.assertRaises(ValueError):service.cast_healing(1,wire,with_packets=True)
        self.assertEqual(f.actor(4),before)
        self.assertEqual(f._cooldowns,{})
        replies=service.cast_healing(1,wire,with_packets=True)
        self.assertEqual(replies[0][0],0x4b)
        self.assertEqual(replies[1:3],(encode_health(4,85),encode_action_points(4,33)))
        self.assertEqual(decode_ability_status(replies[3]),(4,(AbilityStatus(23,1,3,3),)))
        for left in (2,1,0):
            before=f.actor(4)
            with self.assertRaises(ValueError):service.cast_healing(1,wire,with_packets=True)
            self.assertEqual(f.actor(4),before)
            service.end_turn(1,encode_end_turn(4))
            notifications=service.begin_turn_packets(1,[4],40)
            status=decode_ability_status(notifications[-2])[1][0]
            self.assertEqual((status.state,status.remaining),(3 if left else 4,left))
        self.assertEqual(service.cast_healing(1,wire).health,97)
        now[0]=40
        before=f.actor(4)
        with self.assertRaises(ValueError):service.cast_healing(1,wire)
        self.assertEqual(f.actor(4),before)

    def field(self,health=73,points=40):
        return BattleField(8,8,[BattleActor(4,1,2,3,points,health,105)],step_cost=1)

    def heal(self,field,request=None,owner=1):
        return field.heal_self(owner,request or AbilityCast(23,4,0,2,3),amount=12,ap_cost=7,reuse_turns=3)

    def test_heal_movement_share_ap_and_cooldown(self):
        f=self.field();f.prepare_turn(1,[4]);a=self.heal(f)
        self.assertEqual((a.health,a.action_points),(85,33))
        f.move(1,BattleMove(4,((3,3),)))
        self.assertEqual(f.actor(4).action_points,32)
        req=AbilityCast(23,4,0,3,3)
        for _ in range(3):
            before=f.actor(4)
            with self.assertRaises(ValueError):self.heal(f,req)
            self.assertEqual(f.actor(4),before)
            f.prepare_turn(1,[4])
        self.assertEqual(self.heal(f,req).health,97)

    def test_invalid_casts_are_atomic(self):
        for health,points,owner,request in [(0,40,1,None),(105,40,1,None),(73,6,1,None),(73,40,2,None),
                                          (73,40,1,AbilityCast(23,4,0,3,3)),(73,40,1,AbilityCast(23,4,1,2,3))]:
            f=self.field(health,points);before=f.actor(4)
            with self.assertRaises(ValueError):self.heal(f,request,owner)
            self.assertEqual(f.actor(4),before)

    def test_cap_and_actor_removal(self):
        f=self.field(100)
        self.assertEqual(self.heal(f).health,105)
        f.remove_owner(1)
        with self.assertRaises(ValueError):self.heal(f)
        self.assertEqual(f._cooldowns,{})
