"""Range pruning must preserve the reference fog and item semantics."""
from copy import copy
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio import battle_item_effects as effects
from tio.battle_state import BattleActor,BattleField
from tio.combat_distance import combat_distance


def legacy_can_observe(combat,observer,target,*,field=None):
    """Unpruned reference using the client's rounded observer distance."""
    if not observer.health:return False
    field=combat.field if field is None else field
    end=(target.x,target.y);start=(observer.x,observer.y)
    if not effects.clear_item_sight(combat,start,end):return False
    state=effects.initialize(combat);distance=combat_distance(start,end)
    if effects.field_sight(field,start,end):
        if distance<=observer.sight_radius:return True
        if effects.is_dark(combat) and distance<=effects.normal_sight(combat,observer.actor_id):
            if any(a['kind']=='flare' and (target.x-a['center'][0])**2+(target.y-a['center'][1])**2<=a['radius']**2 for a in state['areas'].values()):return True
    for recon in state['recon'].values():
        source=field._actors.get(recon['source'])
        if source is None or not source.health or not field.allied(source.owner_id,observer.owner_id):continue
        x,y=recon['center']
        if ((target.x-x)**2+(target.y-y)**2<=recon['radius']**2 and effects.clear_item_sight(combat,(x,y),end) and effects.field_sight(field,(x,y),end)):return True
    return False


class VisibilityRangeCostTests(unittest.TestCase):
    def prepare(self,*,target=(8,3),dark=False,blocker=(),flash=False,nvg=False,vision=False,flare=False,recon=False,smoke=False,source='allied',native=False):
        actors=[BattleActor(1,7,2,3,40,100,100,9),BattleActor(2,8,*target,40,100,100,9),BattleActor(3,9,20,3,40,100,100,9)]
        field=BattleField(64,32,actors,step_cost=1,blocked=set(blocker),teams={7:0,8:1,9:0})
        if native:field.transparent_obstacles=set()
        combat=SimpleNamespace(field=field);field.combat=combat
        field.item_darkness=dark;field.item_dark_sight_penalty=5
        state=effects.initialize(combat)
        if flash:state['flash'][1]=dict(expiry=3)
        if nvg:state['night_vision'][1]=dict(expiry=3)
        if vision:state['vision'][1]=dict(expiry=3)
        if flare:state['areas'][1]=dict(kind='flare',center=target,radius=3,source=1,owner=7,expiry=3)
        if smoke:state['areas'][2]=dict(kind='smoke',center=(5,3),radius=2,source=1,owner=7,expiry=3)
        if recon:
            identity=3
            if source=='missing':identity=99
            if source=='dead':field._actors[3]=replace(field.actor(3),health=0)
            if source=='hostile':identity=2
            state['recon'][1]=dict(source=identity,center=(target[0]-1,target[1]),radius=3,expiry=3)
        effects.refresh_sight(combat)
        return field,combat

    def assert_legacy_equal(self,field,combat,*,observer=1,target=2):
        current=effects.can_observe(combat,field.actor(observer),field.actor(target),field=field)
        self.assertEqual(current,legacy_can_observe(combat,field.actor(observer),field.actor(target),field=field))
        return current

    def test_daylight_radius_boundary_diagonal_cover_and_native_geometry(self):
        for point in ((3,3),(11,3),(12,3),(11,4),(50,20)):
            for blockers in ((),((6,3),),((6,4),(6,3))):
                for native in (False,True):
                    with self.subTest(point=point,blockers=blockers,native=native):
                        field,combat=self.prepare(target=point,blocker=blockers,native=native);self.assert_legacy_equal(field,combat)

    def test_far_ordinary_targets_never_trace_static_geometry(self):
        for dark in (False,True):
            field,combat=self.prepare(target=(50,20),dark=dark,native=True)
            with patch.object(effects,'field_sight',side_effect=AssertionError('Impossible far ray')) as los:
                self.assertFalse(effects.can_observe(combat,field.actor(1),field.actor(2)));los.assert_not_called()

    def test_geometry_changes_between_calls_without_cache(self):
        field,combat=self.prepare(native=True)
        self.assertTrue(self.assert_legacy_equal(field,combat))
        field.blocked=frozenset(((6,3),))
        self.assertFalse(self.assert_legacy_equal(field,combat))
        field.blocked=frozenset()
        self.assertTrue(self.assert_legacy_equal(field,combat))

    def test_dark_flare_blindness_nvg_and_vision_keep_legacy_results(self):
        for point in ((5,3),(7,3),(10,3),(11,3),(12,3),(14,3),(50,3)):
            for flash,nvg,vision,flare in ((False,False,False,False),(False,False,False,True),(True,False,False,True),(False,True,False,True),(False,False,True,True),(True,True,True,True)):
                with self.subTest(point=point,flash=flash,nvg=nvg,vision=vision,flare=flare):
                    field,combat=self.prepare(target=point,dark=True,flash=flash,nvg=nvg,vision=vision,flare=flare,native=True);self.assert_legacy_equal(field,combat)

    def test_eligible_flare_still_requires_real_static_line_of_sight(self):
        field,combat=self.prepare(target=(10,3),dark=True,flare=True,blocker=((6,3),),native=True)
        with patch.object(effects,'field_sight',wraps=effects.field_sight) as los:
            self.assertFalse(self.assert_legacy_equal(field,combat));self.assertGreaterEqual(los.call_count,1)

    def test_flash_far_flare_does_not_call_los_beyond_capped_normal_radius(self):
        field,combat=self.prepare(target=(10,3),dark=True,flare=True,flash=True,nvg=True)
        with patch.object(effects,'field_sight',side_effect=AssertionError('Blind out-of-range flare ray')) as los:
            self.assertFalse(effects.can_observe(combat,field.actor(1),field.actor(2)));los.assert_not_called()

    def test_remote_recon_still_uses_its_own_center_geometry(self):
        field,combat=self.prepare(target=(40,3),recon=True,native=True)
        with patch.object(effects,'field_sight',wraps=effects.field_sight) as los:
            self.assertTrue(effects.can_observe(combat,field.actor(1),field.actor(2)))
            self.assertEqual(los.call_args_list,[unittest.mock.call(field,(39,3),(40,3))])
        self.assertTrue(self.assert_legacy_equal(field,combat))

    def test_recon_dead_missing_hostile_and_outside_radius_never_reveal(self):
        for source in ('dead','missing','hostile'):
            field,combat=self.prepare(target=(40,3),recon=True,source=source)
            self.assertFalse(self.assert_legacy_equal(field,combat))
        field,combat=self.prepare(target=(40,3),recon=True);combat.item_effects['recon'][1]['center']=(20,3)
        with patch.object(effects,'field_sight',side_effect=AssertionError('Remote recon out-of-range ray')):
            self.assertFalse(effects.can_observe(combat,field.actor(1),field.actor(2)))

    def test_global_observer_smoke_continues_to_block_remote_recon(self):
        field,combat=self.prepare(target=(40,3),recon=True,smoke=True)
        self.assertFalse(self.assert_legacy_equal(field,combat))
        with patch.object(effects,'field_sight',side_effect=AssertionError('Smoke should reject first')):
            self.assertFalse(effects.can_observe(combat,field.actor(1),field.actor(2)))

    def test_live_observer_can_see_corpse_but_dead_observer_never_grants_sight(self):
        field,combat=self.prepare();field._actors[2]=replace(field.actor(2),health=0)
        self.assertTrue(self.assert_legacy_equal(field,combat))
        field._actors[1]=replace(field.actor(1),health=0)
        with patch.object(effects,'field_sight',side_effect=AssertionError('Dead observer ray')):
            self.assertFalse(effects.can_observe(combat,field.actor(1),field.actor(2)))

    def test_stale_combat_reference_uses_supplied_projection_positions(self):
        field,combat=self.prepare(target=(40,3));replay=copy(field);replay._actors=dict(field._actors)
        replay._actors[2]=replace(field.actor(2),x=8)
        self.assertTrue(self.assert_legacy_equal(replay,combat));self.assertFalse(self.assert_legacy_equal(field,combat))
        replay._actors[3]=replace(field.actor(3),x=35)
        combat.item_effects['recon'][1]=dict(source=3,center=(39,3),radius=3,expiry=3)
        replay._actors[2]=replace(field.actor(2),x=40)
        self.assertTrue(self.assert_legacy_equal(replay,combat))

    def test_recon_geometry_and_source_liveness_follow_supplied_projection(self):
        field,combat=self.prepare(target=(40,3),recon=True,blocker=((6,3),),native=True)
        self.assertTrue(self.assert_legacy_equal(field,combat))
        combat.item_effects['recon'][1]['center']=(38,3)
        field.blocked=frozenset(((6,3),(39,3)))
        self.assertFalse(self.assert_legacy_equal(field,combat))
        field.blocked=frozenset(((6,3),))
        replay=copy(field);replay._actors=dict(field._actors)
        for source in (replace(field.actor(3),health=0),replace(field.actor(3),owner_id=8)):
            replay._actors[3]=source
            self.assertFalse(self.assert_legacy_equal(replay,combat))
            self.assertTrue(self.assert_legacy_equal(field,combat))


if __name__=='__main__':unittest.main()
