"""Committed combat decisions: finish weak targets, replan misses, retain cover."""
from dataclasses import replace
import random
import unittest

import test_tactical_bot as fixture
from tio.bot_finishing import damage_distribution,attacks_to_finish,forecast,finish_plan
from tio.tactical_bot import play_actor,weapon_for,enemies_for
from tio.visibility import visible_actors
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.item_list import encode_item_list


class Hits(random.Random):
    def randrange(self,*args):return 0
    def randint(self,low,high):return low


class FirstMiss(Hits):
    first=True
    def randrange(self,*args):
        if self.first:self.first=False;return 99
        return 0


class FinishingTests(unittest.TestCase):
    def scene(self,hp=50,*,ap=15,ammo=40,damage=30,price=3,accuracy=95,bullets=1):
        case=fixture.TacticalBotTests()
        field,arena,_=case.scene(bot=(3,3),enemy=(7,3),enemy_sight=5,ap=ap,
                               bag=(fixture.item(10,301,equipped=True,slot=16),fixture.item(11,3,ammo)))
        combat=field.combat;combat.proficiencies.pop(1,None)
        combat.catalog.weapons[301]=replace(combat.catalog.weapons[301],damage_base=damage,damage_random=0,
                                           attack_ap=price,bullets_count=bullets)
        combat.catalog.sources[301]={**combat.catalog.sources[301],'damage_fade':'100',
                                     'accuracy':str(accuracy),'accuracy_gain_amount':'0','critical':'0'}
        combat.rng=Hits();field._actors[2]=replace(field.actor(2),health=hp)
        return field,arena

    def run_bot(self,field,arena):
        packets=play_actor(arena,1,7,1)
        return packets,[decode_attack_result(p) for p in packets if p[0]==0x4b]

    def test_two_hits_finish_target_instead_of_retreating_after_first(self):
        f,a=self.scene();packets,hits=self.run_bot(f,a)
        self.assertEqual([h.hits[0].left_hp for h in hits],[20,0])
        self.assertEqual((f.actor(1).x,f.actor(1).y),(3,3))
        self.assertEqual(f.actor(1).action_points,9)
        self.assertEqual(fixture.items_count(f,3),38)
        self.assertFalse(any(p[0]==0x3d for p in packets))

    def test_one_hit_target_costs_only_one_attack(self):
        f,a=self.scene(hp=20);_,hits=self.run_bot(f,a)
        self.assertEqual(len(hits),1);self.assertEqual(f.actor(2).health,0)
        self.assertEqual(fixture.items_count(f,3),39)

    def test_healthy_target_keeps_hit_and_cover_policy(self):
        f,a=self.scene(hp=1000);_,hits=self.run_bot(f,a)
        self.assertEqual(len(hits),1)
        self.assertNotIn(1,visible_actors(f,8))

    def test_miss_is_replanned_from_actual_hp_and_remaining_ap(self):
        f,a=self.scene(ap=10);f.combat.rng=FirstMiss();_,hits=self.run_bot(f,a)
        self.assertEqual([h.hits[0].left_hp for h in hits],[50,20,0])
        self.assertEqual(f.actor(1).action_points,1)
        self.assertEqual(fixture.items_count(f,3),37)

    def test_miss_without_enough_ap_for_two_more_hits_triggers_cover(self):
        f,a=self.scene(ap=7);f.combat.rng=FirstMiss();_,hits=self.run_bot(f,a)
        self.assertEqual(len(hits),1);self.assertEqual(f.actor(2).health,50)
        self.assertNotIn(1,visible_actors(f,8))

    def test_insufficient_ammo_does_not_make_two_hit_plan(self):
        f,a=self.scene(ammo=1)
        self.assertIsNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))
        _,hits=self.run_bot(f,a);self.assertEqual(len(hits),1)
        self.assertEqual(fixture.items_count(f,3),0)

    def test_expensive_weapon_cannot_assume_extra_ap(self):
        f,a=self.scene(price=8)
        self.assertIsNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))
        _,hits=self.run_bot(f,a);self.assertEqual(len(hits),1)
        self.assertGreaterEqual(f.actor(1).action_points,0)

    def test_visible_armor_changes_finish_decision(self):
        f,a=self.scene(ap=10)
        self.assertIsNotNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))
        f.combat.npc_defense={2:400}
        self.assertIsNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))
        _,hits=self.run_bot(f,a);self.assertEqual(hits[0].hits[0].damage,6)
        self.assertNotEqual(f.actor(2).health,0)

    def test_burst_damage_is_not_multiplied_by_ammo_consumption(self):
        f,a=self.scene(bullets=3);_,hits=self.run_bot(f,a)
        self.assertEqual([h.hits[0].damage for h in hits],[30,20])
        self.assertEqual(fixture.items_count(f,3),34)

    def test_low_accuracy_does_not_claim_a_two_attack_finish(self):
        f,_=self.scene(ap=6,accuracy=20)
        self.assertIsNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))

    def test_forecast_does_not_use_or_advance_future_random_rolls(self):
        f,_=self.scene();f.combat.rng=random.Random(77);state=f.combat.rng.getstate()
        first=finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7))
        self.assertEqual(f.combat.rng.getstate(),state)
        f.combat.rng=random.Random(92)
        self.assertEqual(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)),first)

    def test_hidden_enemy_health_and_location_do_not_change_decision(self):
        f,_=self.scene();first=finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7))
        for hp in (1,1000):
            f._actors[3]=replace(f.actor(2),actor_id=3,owner_id=9,x=23,y=15,health=hp)
            self.assertEqual(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)),first)

    def test_other_hostile_requires_cover_after_planned_kill(self):
        f,_=self.scene(ap=6)
        f._actors[3]=replace(f.actor(2),actor_id=3,owner_id=9,x=5,y=5,health=1000,sight_radius=20)
        # Exactly two attacks consume all AP; a third surviving observer makes
        # standing exposed an unacceptable finish plan.
        self.assertIsNone(finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7)))

    def test_target_that_can_die_this_turn_is_prioritized_over_lower_armored_hp(self):
        f,a=self.scene(hp=20,ap=10);f.combat.npc_defense={2:1000}
        f._actors[3]=replace(f.actor(2),actor_id=3,owner_id=9,x=7,y=4,health=30,sight_radius=1)
        f.combat.register(3,encode_item_list(3,()),human=True)
        plan=finish_plan(f,1,enemies_for(f,7,1),visible_actors(f,7))
        self.assertIsNotNone(plan);self.assertEqual(plan[1],3)

    def test_exact_damage_probability_includes_misses_and_armor(self):
        distribution=damage_distribution(30,30,95,1,0,100)
        self.assertAlmostEqual(dict(distribution)[15],.95)
        self.assertEqual(attacks_to_finish(distribution,30,2)[0],2)
        self.assertAlmostEqual(attacks_to_finish(distribution,30,2)[1],.9025)
        self.assertIsNone(attacks_to_finish(distribution,31,2))

    def test_naked_bot_finishes_adjacent_target_before_seeking_crate(self):
        f,a=self.scene(hp=10);f.combat.inventories[1]=encode_item_list(1,())
        f._actors[2]=replace(f.actor(2),x=4,y=3)
        f.loot.boxes={(2,3):(fixture.item(100,301),fixture.item(101,3,20))}
        _,hits=self.run_bot(f,a)
        self.assertTrue(hits);self.assertEqual(f.actor(2).health,0)
        self.assertFalse(f.loot.opened)

    def test_proficiency_and_weapon_upgrade_match_committed_damage(self):
        f,a=self.scene(hp=56,ap=6)
        original,_,_=fixture.TacticalBotTests().scene()
        f.combat.proficiencies[1]=original.combat.proficiencies[1]
        f.combat.inventories[1]=encode_item_list(1,(
            replace(fixture.item(10,301,equipped=True,slot=16),unknown_bytes_03=b'\x03\0\0'),
            fixture.item(11,3,40)))
        distribution=forecast(f,1,(3,3),f.actor(2),weapon_for(f,1))
        self.assertEqual(max(d for d,p in distribution),28)
        _,hits=self.run_bot(f,a)
        self.assertEqual([h.hits[0].damage for h in hits],[28,28])
        self.assertEqual(f.actor(2).health,0)

    def test_kill_is_followed_by_cover_from_other_surviving_enemy(self):
        f,a=self.scene()
        f._actors[3]=replace(f.actor(2),actor_id=3,owner_id=9,x=7,y=4,health=1000)
        f.combat.register(3,encode_item_list(3,()),human=True)
        _,hits=self.run_bot(f,a)
        self.assertEqual(f.actor(2).health,0)
        self.assertEqual(len(hits),2)
        self.assertEqual(f.actor(3).health,1000)
        self.assertNotIn(1,visible_actors(f,9))

    def test_two_real_recipients_receive_each_hit_and_actual_remaining_hp(self):
        import test_shared_team_arena as shared
        from server.battle_events import BotEventArena
        from tio.training_bot import play_turn
        c=shared.SharedTeamTests();c.setUp();self.addCleanup(c.doCleanups)
        owners,b=c.open_battle();f=b['field'];combat=f.combat
        bot=next(o for o in b['bots'] if not f.allied(o,owners[0]))
        shooter=f.actor_ids(bot)[0];target=f.actor_ids(owners[0])[0]
        f.blocked=frozenset();f.doors.states={};f.loot.boxes={};f.patrol_waypoints=()
        for n,(i,actor) in enumerate(f._actors.items()):f._actors[i]=replace(actor,x=18+n,y=15)
        f._actors[shooter]=replace(f.actor(shooter),x=6,y=5)
        f._actors[target]=replace(f.actor(target),x=5,y=5,health=50)
        observer=f.actor_ids(owners[1])[0];f._actors[observer]=replace(f.actor(observer),x=7,y=5)
        combat.inventories[shooter]=encode_item_list(shooter,(
            fixture.item(10001,301,equipped=True,slot=16),fixture.item(10002,3,40)))
        combat.catalog.weapons[301]=replace(combat.catalog.weapons[301],damage_base=30,damage_random=0)
        combat.catalog.sources[301]={**combat.catalog.sources[301],'damage_fade':'100','accuracy':'95',
                                    'accuracy_gain_amount':'0','critical':'0'}
        combat.proficiencies.pop(shooter,None);combat.rng=Hits()
        for v in b['views'].values():v.refresh()
        for q in c.hub.queues.values():q.clear()
        b['arena']._turns.clear();play_turn(BotEventArena(c.hub,b),b['room'].room_id,bot)
        self.assertEqual(f.actor(target).health,0)
        for owner in owners:
            hits=[decode_attack_result(p) for p in c.hub.queues[owner] if p[0]==0x4b]
            self.assertEqual([h.hits[0].left_hp for h in hits],[20,0])

if __name__=='__main__':unittest.main()
