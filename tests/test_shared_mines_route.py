"""Local-only refusal/collision tests for mining QA route planning."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from tools.shared_mines_route import RouteCache,UnsafeRouteError,plan_mission,plan_route,unsafe_cells


def snapshot():
    return dict(width=60,height=60,blocked=[],actors=[
        dict(id=100,owner=10,account='owned-a',team=0,x=0,y=0,hp=115,sight=5),
        dict(id=200,owner=20,account=None,team=2,x=40,y=40,hp=150,sight=6)])


class SharedMinesRouteTests(unittest.TestCase):
    def test_cardinal_detour_avoids_collision_without_mutating_snapshot(self):
        state=snapshot();state['actors'].pop()
        state['blocked']=[[1,1]]
        state['actors'].append(dict(id=101,owner=11,account='owned-b',team=1,x=1,y=0,hp=115,sight=5))
        before=deepcopy(state);plan=plan_route(state,10,[(3,0)])
        self.assertEqual(state,before);self.assertEqual(plan.path[-1],(3,0))
        self.assertNotIn((1,0),plan.path);self.assertNotIn((1,1),plan.path)
        old=plan.start
        for cell in plan.path:
            self.assertEqual(abs(old[0]-cell[0])+abs(old[1]-cell[1]),1);old=cell

    def test_interaction_can_approach_blocked_crate_but_never_walk_onto_it(self):
        state=snapshot();state['blocked']=[[3,0]]
        plan=plan_route(state,10,[(3,0)],interaction_radius=1)
        self.assertEqual(plan.goal,(3,0));self.assertNotIn((3,0),plan.path)
        self.assertLessEqual(max(abs(plan.path[-1][0]-3),abs(plan.path[-1][1])),1)

    def test_all_own_fighters_must_avoid_potential_patrol_sight(self):
        state=snapshot();npc=state['actors'][1];npc.update(x=12,y=1)
        state['bot_patrol_regions']={'200':[[x,1] for x in range(6,13)]}
        self.assertIn((0,0),unsafe_cells(state))
        with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(3,0)])

    def test_exact_opaque_wall_allows_safe_route_on_its_protected_side(self):
        state=snapshot();npc=state['actors'][1];npc.update(x=9,y=2)
        state['blocked']=[[5,y] for y in range(60)];state['transparent_obstacles']=[]
        state['bot_patrol_regions']={'200':[[9,2]]}
        plan=plan_route(state,10,[(4,2)])
        self.assertEqual(plan.path[-1],(4,2));self.assertEqual(plan.safety_model,'persisted_patrol_envelope')
        del state['transparent_obstacles']
        with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(4,2)])

    def test_missing_region_is_conservative_and_pursuing_mutant_refuses(self):
        state=snapshot();state['actors'][1].update(x=18,y=0)
        with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(2,0)])
        state['bot_patrol_regions']={'200':[[30,30]]}
        with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(2,0)])

    def test_step_and_ap_bounds_and_ambiguous_squad_refuse(self):
        state=snapshot()
        with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(4,0)],max_steps=3)
        plan=plan_route(state,10,[(4,0)])
        self.assertEqual(plan.prefix(3,reserve=1),plan.path[:2]);self.assertEqual(plan.prefix(0),())
        for points,reserve in ((-1,0),(256,0),(3,4),(True,0)):
            with self.assertRaises(ValueError):plan.prefix(points,reserve=reserve)
        state['actors'].append({**state['actors'][0],'id':101,'x':1})
        with self.assertRaises(ValueError):plan_route(state,10,[(4,0)])

    def test_cache_reuses_only_immutable_threats_and_checks_live_pursuit_and_expiry(self):
        state=snapshot();state['bot_patrol_regions']={'200':[[40,40],[40,41]]}
        now=[0];cache=RouteCache(max_entries=1,ttl_seconds=20,clock=lambda:now[0])
        with patch('tools.shared_mines_route.unsafe_cells',wraps=unsafe_cells) as compute:
            first=plan_route(state,10,[(4,0)],cache=cache)
            state['actors'][1]['y']=41
            self.assertEqual(plan_route(state,10,[(4,0)],cache=cache),first)
            self.assertEqual(compute.call_count,1)
            state['actors'][1]['y']=42
            with self.assertRaises(UnsafeRouteError):plan_route(state,10,[(4,0)],cache=cache)
            state['actors'][1]['y']=41;now[0]=21
            plan_route(state,10,[(4,0)],cache=cache);self.assertEqual(compute.call_count,2)
            state['actors'][1]['hp']=0
            plan_route(state,10,[(4,0)],cache=cache);self.assertEqual(compute.call_count,3)
            self.assertEqual(len(cache._entries),1)

    def test_mission_preflights_entire_chain_on_a_copy_and_requires_safe_exit(self):
        state=snapshot();state.update(crates=[[3,0]])
        state['blocked']=[[3,0]]
        state['mining']=dict(roles={'10':1},owner_deadlines={'10':5},round=0,lift=[[0,0]],raider_exits=[[59,59]],
                            deposits=[dict(x=5,y=0,installed=False,left=500)])
        before=deepcopy(state);mission=plan_mission(state,10,cache=RouteCache())
        self.assertEqual(state,before);self.assertEqual(mission.completed_rounds_to_wait,5)
        self.assertEqual(mission.crate.goal,(3,0));self.assertEqual(mission.deposit.goal,(5,0))
        self.assertEqual(mission.exit.goal,(0,0));self.assertEqual(mission.exit.path[-1],(0,0))
        with self.assertRaises(UnsafeRouteError):plan_mission(state,10,max_steps=1)
        state['mining']['lift']=[[40,40]]
        with self.assertRaises(UnsafeRouteError):plan_mission(state,10)


if __name__=='__main__':unittest.main()
