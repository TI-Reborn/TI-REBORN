"""Authoritative owner projection, turn expiry and reconnect for F9/v1."""
from dataclasses import replace
import unittest
from test_battle_item_effects import BattleItemFixture
from tio import battle_item_effects as effects, battle_item_visuals as visuals, battle_snapshot
from tio.protocol.night_vision_state import encode_night_vision_state, decode_night_vision_state
from tio.protocol.binary import PacketError
from tio.protocol.item_action import ItemAction


class NightVisionStateTests(BattleItemFixture):
    def snapshot(self, owner):
        return decode_night_vision_state(visuals.packets(self.field, owner)[1])

    def test_codec_rejects_invalid_actor_identity_order_and_trailing_bytes(self):
        self.assertEqual(encode_night_vision_state(()), b'\xf9\1\0\0')
        self.assertEqual(decode_night_vision_state(encode_night_vision_state((1, 0x7fffffff))), (1, 0x7fffffff))
        for invalid in ((True,), (0,), (-1,), (0x80000000,), (2, 1), (1, 1), tuple(range(1, 66))):
            with self.subTest(invalid=invalid[:2]), self.assertRaises(PacketError):
                encode_night_vision_state(invalid)
        for packet in (b'\xf9\2\0\0', b'\xf9\1\0\0\0', b'\xf9\1\1\0', b'\xf9\1\x41\0', b'\xf9\1\1\0\0\0\0\0'):
            with self.subTest(packet=packet), self.assertRaises(PacketError):
                decode_night_vision_state(packet)

    def test_state_is_private_even_to_an_allied_owner(self):
        self.prepare(5002)
        effects.initialize(self.combat)['night_vision'][1] = dict(instance=100, generation=0)
        self.assertEqual(self.snapshot(7), (1,))
        self.assertEqual(self.snapshot(8), ())
        self.assertEqual(self.snapshot(9), ())

    def test_dead_missing_and_inactive_actors_clear_without_leaking(self):
        self.prepare(5002)
        state = effects.initialize(self.combat)
        state['night_vision'][1] = dict(instance=100, generation=0)
        state['night_vision'][9999] = dict(instance=100, generation=0)
        self.field._actors[1] = replace(self.field.actor(1), health=0)
        self.assertEqual(self.snapshot(7), ())
        self.field._actors[1] = replace(self.field.actor(1), health=100)
        state['night_vision'].clear()
        self.assertEqual(self.snapshot(7), ())

    def test_turn_loss_of_ap_and_reconnect_preserve_only_actual_activation(self):
        self.prepare(5002)
        self.field.item_darkness = True
        action = ItemAction(1, 100, 255)
        effects.use(self.combat, 7, action)
        self.assertEqual(self.snapshot(7), (1,))
        restored, _ = battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.assertEqual(decode_night_vision_state(visuals.packets(restored, 7)[1]), (1,))
        effects.use(self.combat, 7, action)
        self.assertEqual(self.snapshot(7), ())
        effects.use(self.combat, 7, action)
        self.assertEqual(self.snapshot(7), (1,))
        self.field._actors[1] = replace(self.field.actor(1), action_points=0)
        self.field._ability_turns[1] = self.field._ability_turns.get(1, 0) + 1
        effects.begin_turn(self.combat, 7, (1,))
        self.assertEqual(self.snapshot(7), ())


if __name__ == '__main__':
    unittest.main()
