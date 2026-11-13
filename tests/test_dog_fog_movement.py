"""Fog uses the existing off-map actor without destroying its native model."""
from dataclasses import replace
import unittest

from server.battle_events import movement_packets
from tio.battle_state import BattleActor, BattleField
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
                for view, first in zip(views, (4, 8)):
                    replies = movement_packets(view, before, packet)
                    dog_packets = [p for p in replies if int.from_bytes(p[1:5], 'little') == 2]
                    self.assertEqual([p[0] for p in dog_packets], [0x3b, 0x3d, 0x3b])
                    shown, moved, hidden = dog_packets
                    self.assertEqual(decode_battle_soldier(shown, human_equipment=False).position, (first, 6))
                    self.assertEqual(decode_battle_move(moved), BattleMove(
                        2, tuple((x, 6) for x in range(first + 1, first + 3))))
                    final = decode_battle_soldier(hidden, human_equipment=False)
                    self.assertEqual((final.position, final.fields['0x8c57bb']), ((255, 255), 1))
                    self.assertNotIn(2, view.visible)
