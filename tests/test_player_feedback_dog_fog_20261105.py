"""Fog uses the existing off-map actor without destroying its native model."""
from dataclasses import replace
import unittest

from server.battle_events import movement_packets
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.protocol.battle_move import BattleMove, decode_battle_move, encode_battle_move
from tio.protocol.battle_soldier import (
    BattleSoldier, CONDITIONS, SCHEMAS, decode_battle_soldier)
from tio.visibility import VisibilityView


def template(actor: BattleActor, resource: int) -> BattleSoldier:
    fields = {key: (b'' if reader == 'CString' else 0)
              for key, _, reader in SCHEMAS[False]}
    fields.update({
        '0x8c5088': actor.actor_id, '0x8c50ea': actor.owner_id,
        '0x8c50fb': resource, '0x8c5116': b'Dog', '0x8c5134': 1,
        '0x8c5187': 1, '0x8c5173': 1,
    })
    for key, (control, expected) in CONDITIONS.items():
        enabled = bool(fields[control]) if expected is None else fields[control] == expected
        if not enabled:
            fields.pop(key, None)
    return BattleSoldier(False, fields)


class DogFogTests(unittest.TestCase):
    def test_observers_receive_one_route_per_visible_dog_segment(self):
        observers = (BattleActor(1, 10, 5, 5, 15, 100, 100, 2),
                     BattleActor(3, 30, 9, 5, 15, 100, 100, 2))
        for resource in (3, 4, 5, 103):
            with self.subTest(resource=resource):
                dog = BattleActor(2, 20, 1, 6, 17, 55, 55, 9)
                field = BattleField(16, 16, (*observers, dog), step_cost=1)
                field.battle_mode = 7
                templates = {1: template(observers[0], 1), 3: template(observers[1], 1),
                             2: template(dog, resource)}
                views = tuple(VisibilityView(field, a.owner_id, templates) for a in observers)
                for view in views:
                    view.refresh(visuals=False)
                before = dict(field._actors)
                route = tuple((x, 6) for x in range(2, 13))
                field._actors[2] = replace(dog, x=12, action_points=6)
                packet = encode_battle_move(BattleMove(2, route))
                for view, first in zip(views, (3, 7)):
                    replies = movement_packets(view, before, packet)
                    dog_packets = [p for p in replies if int.from_bytes(p[1:5], 'little') == 2]
                    self.assertEqual([p[0] for p in dog_packets], [0x3b, 0x3d, 0x3b])
                    shown, moved, hidden = dog_packets
                    self.assertEqual(decode_battle_soldier(shown, human_equipment=False).position, (first, 6))
                    self.assertEqual(decode_battle_move(moved), BattleMove(
                        2, tuple((x, 6) for x in range(first + 1, first + 5))))
                    final = decode_battle_soldier(hidden, human_equipment=False)
                    self.assertEqual((final.position, final.fields['0x8c57bb']), ((255, 255), 1))
                    self.assertNotIn(2, view.visible)

    def test_side_step_keeps_dog_visible_on_native_nine_cell_boundary(self):
        player = BattleActor(1, 10, 5, 5, 15, 100, 100, 9)
        dog = BattleActor(2, 20, 14, 5, 17, 55, 55, 9)
        ally = BattleActor(3, 30, 2, 20, 15, 100, 100, 9)
        field = BattleField(32, 32, (player, dog, ally), step_cost=1,
                            teams={10: 0, 20: 1, 30: 0}, transparent_obstacles=())
        field.battle_mode = 7
        field.combat = Combat(field, None)
        templates = {1: template(player, 3), 2: template(dog, 103), 3: template(ally, 3)}
        views = (VisibilityView(field, 10, templates), VisibilityView(field, 30, templates))
        for view in views:
            view.refresh(visuals=False)
            self.assertIn(2, view.visible)

        for x, y, expected in ((5, 6, True), (5, 7, True), (5, 8, True), (5, 9, False)):
            before = dict(field._actors)
            packet = field.move(10, BattleMove(1, ((x, y),)))
            for view in views:
                with self.subTest(position=(x, y), viewer=view.owner):
                    replies = movement_packets(view, before, packet)
                    self.assertEqual(2 in view.visible, expected)
                    snapshots = [decode_battle_soldier(p, human_equipment=False) for p in replies
                                 if p.startswith(b'\x3b\x02\0\0\0')]
                    self.assertEqual([s.position for s in snapshots], [] if expected else [(255, 255)])

    def scene(self, mode):
        actors = [BattleActor(1, 10, 5, 5, 15, 100, 100, 3),
                  BattleActor(2, 20, 6, 5, 17, 55, 55, 9)]
        field = BattleField(32, 32, actors, step_cost=1)
        if mode is not None:
            field.battle_mode = mode
        view = VisibilityView(field, 10, {
            1: template(actors[0], 3), 2: template(actors[1], 103)})
        view.refresh()
        return field, view

    def test_living_dog_fog_cycles_keep_model_registered_without_position_or_hp_leak(self):
        for mode in (0, 1, 16):
            with self.subTest(mode=mode):
                field, view = self.scene(mode)
                for _ in range(3):
                    field._actors[2] = replace(field.actor(2), x=25, y=24, health=17)
                    packets = view.refresh()
                    self.assertFalse(any(p[:1] == b'\x43' for p in packets))
                    self.assertEqual(len(packets), 1)
                    hidden = decode_battle_soldier(packets[0], human_equipment=False).fields
                    self.assertEqual((hidden['0x8c519b'], hidden['0x8c51af'],
                                      hidden['0x8c57bb']), (255, 255, 1))
                    self.assertNotIn(2, view.visible)
                    self.assertEqual(view.refresh(), ())
                    field._actors[2] = replace(field.actor(2), x=6, y=5)
                    packets = view.refresh()
                    self.assertEqual(len(packets), 1)
                    shown = decode_battle_soldier(packets[0], human_equipment=False).fields
                    self.assertEqual((shown['0x8c519b'], shown['0x8c51af'],
                                      shown['0x8c57bb']), (6, 5, 17))
                    self.assertIn(2, view.visible)

    def test_unregistered_probe_still_removes_lost_actor(self):
        field, view = self.scene(None)
        field._actors[2] = replace(field.actor(2), x=25)
        self.assertEqual(view.refresh(), (b'\x43\x02\0\0\0',))

    def test_known_corpse_survives_fog_without_second_death_transition(self):
        field, view = self.scene(0)
        field._actors[2] = replace(field.actor(2), health=0)
        view.refresh()
        field._actors[1] = replace(field.actor(1), x=25)
        self.assertEqual(view.refresh(), ())
        field._actors[1] = replace(field.actor(1), x=5)
        self.assertEqual(view.refresh(), ())
        self.assertIn(2, view.resident_corpses)
