"""Mine hunters exercise real turn, movement and combat authority."""
import random
import unittest
from dataclasses import replace

from tio.arena_service import ArenaService
from tio.battle_snapshot import dumps, loads
from tio.battle_state import BattleActor, BattleField
from tio.combat import Combat
from tio.mining_ai import configure_patrols
from tio.protocol.arena import ArenaCreateRequest
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.battle_move import decode_battle_move
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.training_bot import bot_known, play_turn
from tio.weapons import WeaponCatalog, WeaponStats


MUTANT_OWNER = 7
MINER_OWNER = 8
RAIDER_OWNER = 9


def mutant(identity=1, position=(1, 1), *, ap=20, sight=6):
    return BattleActor(identity, MUTANT_OWNER, *position, ap, 150, 150, sight)


def human(identity=10, position=(6, 1), *, owner=MINER_OWNER):
    return BattleActor(identity, owner, *position, 40, 1000, 1000, 6)


class MineHunterTests(unittest.TestCase):
    def scene(self, actors, *, step_cost=1, attack_ap=5, attack_range=1,
              blocked=(), transparent=None):
        """Minimal shared mine room; gameplay calls retain their real services."""
        owners = tuple(dict.fromkeys(a.owner_id for a in actors))
        humans = tuple(o for o in owners if o != MUTANT_OWNER)
        field = BattleField(32, 32, actors, step_cost=step_cost, blocked=blocked,
            transparent_obstacles=transparent,
            teams={MINER_OWNER: 0, RAIDER_OWNER: 1, MUTANT_OWNER: 2})
        field.battle_mode = 7
        catalog = WeaponCatalog()
        weapon = WeaponStats(353, 'Sick Miner Attack', 'Melee', 10, 0,
                             attack_ap, None, None, 1, 1, attack_range)
        catalog.weapons[353] = weapon
        catalog.sources[353] = {'weaponAttack': 'None', 'weaponType': 'Melee',
                                'accuracy': '100', 'damage_fade': '0'}
        field.combat = Combat(field, catalog, rng=random.Random(0))
        field.combat.npc_defense = {}
        for actor in actors:
            mob = actor.owner_id == MUTANT_OWNER
            items = (ItemRecord(100 + actor.actor_id, 353, bytes(2), 1, 1, 16,
                                (1000, 1000, 1000), bytes(4), None, bytes(3)),) if mob else ()
            field.combat.register(actor.actor_id,
                                  encode_item_list(actor.actor_id, items), human=True)
            field.combat.resources[actor.actor_id] = 100 if mob else 1
            field.combat.npc_defense[actor.actor_id] = 0
            field._actors[actor.actor_id] = replace(actor, weapons=(weapon,)) if mob else actor
        configure_patrols(field, field.actor_ids(MUTANT_OWNER))
        arena = ArenaService(clock=lambda: 0)
        request = ArenaCreateRequest(7, 0, len(owners), 2, 40, 1, 1, 0, 0)
        room = arena.rooms.create(humans[0], request)
        for owner in (*humans[1:], MUTANT_OWNER):
            room = arena.rooms.join(room.room_id, owner)
        arena._loading[room.room_id] = set(room.members)
        arena._fields[room.room_id] = field
        return arena, room.room_id, field

    def turn(self, arena, room_id):
        packets = play_turn(arena, room_id, MUTANT_OWNER)
        attacks = tuple(decode_attack_result(p) for p in packets if p[:1] == b'\x4b')
        steps = tuple(cell for p in packets if p[:1] == b'\x3d'
                      for cell in decode_battle_move(p).path)
        return attacks, steps

    def view(self, field, owner):
        from tio.protocol.battle_soldier import BattleSoldier, SCHEMAS, CONDITIONS
        from tio.visibility import VisibilityView
        templates = {}
        for identity, actor in field._actors.items():
            fields = {key: (b'' if reader == 'CString' else 0)
                      for key, size, reader in SCHEMAS[True]}
            fields.update({'0x8c5088': identity, '0x8c50ea': actor.owner_id,
                '0x8c50fb': field.combat.resources[identity], '0x8c5116': b'Test',
                '0x8c5134': 4, '0x8c519b': actor.x, '0x8c51af': actor.y,
                '0x8c5187': field.teams[actor.owner_id], '0x8c5173': 1,
                '0x8c566a': actor.max_health, '0x8c57bb': actor.health,
                '0x8c567f': actor.sight_radius, '0x8c571d': actor.action_points,
                '0x8c5694': field._turn_points[identity],
                '0x8c52cf': 353 if actor.owner_id == MUTANT_OWNER else 0})
            for key, (control, expected) in CONDITIONS.items():
                if not (bool(fields[control]) if expected is None else fields[control] == expected):
                    fields.pop(key, None)
            templates[identity] = BattleSoldier(True, fields)
        view = VisibilityView(field, owner, templates)
        view.refresh()
        return view

    def test_detection_during_patrol_replans_and_attacks_in_same_turn(self):
        arena, room, field = self.scene([mutant(sight=2), human()])
        field.bot_patrol_waypoints[1] = ((7, 1), (1, 1))
        attacks, steps = self.turn(arena, room)
        self.assertEqual(steps, ((2, 1), (3, 1), (4, 1), (5, 1)))
        self.assertEqual(len(attacks), 3)
        self.assertTrue(all(a.target == (6, 1) for a in attacks))
        self.assertLess(field.actor(10).health, 1000)
        self.assertEqual(arena.next_turn_owner(room), MINER_OWNER)

    def test_diagonal_melee_uses_all_four_attacks_without_movement(self):
        arena, room, field = self.scene([mutant(), human(position=(2, 2))])
        attacks, steps = self.turn(arena, room)
        self.assertEqual(steps, ())
        self.assertEqual(len(attacks), 4)
        self.assertTrue(all(a.origin == (1, 1) and a.target == (2, 2) for a in attacks))
        self.assertLess(field.actor(10).health, 1000)

    def test_diagonal_wall_requires_a_visible_approach_before_attack(self):
        arena, room, field = self.scene([mutant(), human(position=(2, 2))], blocked={(2, 1)})
        field.bot_patrol_waypoints[1] = ((1, 3), (1, 1))
        self.assertNotIn(10, bot_known(field, MUTANT_OWNER, 1))
        attacks, steps = self.turn(arena, room)
        self.assertEqual(steps, ((1, 2),))
        self.assertEqual(len(attacks), 3)
        self.assertTrue(all(a.origin == (1, 2) for a in attacks))
        self.assertLess(field.actor(10).health, 1000)

    def test_real_movement_cost_leaves_only_two_attacks(self):
        arena, room, field = self.scene([mutant(), human()], step_cost=2)
        attacks, steps = self.turn(arena, room)
        self.assertEqual(len(steps), 4)
        self.assertEqual(len(attacks), 2)  # 20 - 4 * 2 = 12 AP; attack costs 5.
        self.assertLessEqual(len(steps) * field.step_cost + len(attacks) * 5, 20)

    def test_weapon_range_and_attack_cost_change_the_plan(self):
        arena, room, _ = self.scene([mutant(), human(position=(5, 1))],
                                   step_cost=2, attack_ap=6, attack_range=3)
        attacks, steps = self.turn(arena, room)
        self.assertEqual(len(steps), 1)
        self.assertEqual(len(attacks), 3)  # One 2 AP step leaves three 6 AP hits.
        self.assertTrue(all(a.weapon_id == 353 for a in attacks))

    def test_low_ap_never_grants_free_movement_or_attack(self):
        for target, expected_steps in (((6, 1), 1), ((2, 2), 0)):
            with self.subTest(target=target):
                arena, room, field = self.scene([mutant(ap=3), human(position=target)],
                                               step_cost=2)
                attacks, steps = self.turn(arena, room)
                self.assertEqual(len(steps), expected_steps)
                self.assertEqual(attacks, ())
                self.assertEqual(field.actor(10).health, 1000)

    def test_hidden_target_position_does_not_update_memory_or_route(self):
        outcomes = []
        for hidden in ((25, 1), (1, 25)):
            arena, room, field = self.scene([mutant(ap=1, sight=4), human(position=(5, 1))])
            self.turn(arena, room)
            self.assertEqual(field.mine_hunter_state[1]['last_seen'], (5, 1))
            field._actors[10] = replace(field.actor(10), x=hidden[0], y=hidden[1])
            self.assertNotIn(10, bot_known(field, MUTANT_OWNER, 1))
            attacks, steps = self.turn(arena, room)
            self.assertEqual(attacks, ())
            self.assertEqual(field.mine_hunter_state[1]['last_seen'], (5, 1))
            outcomes.append((steps, field.actor(1), dict(field.mine_hunter_state[1])))
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0][0], ((3, 1),))

    def test_memory_expires_after_three_unseen_personal_turns(self):
        arena, room, field = self.scene([mutant(ap=1, sight=4), human(position=(5, 1))])
        self.turn(arena, room)
        field._actors[10] = replace(field.actor(10), x=25, y=25)
        for _ in range(3):
            self.turn(arena, room)
            self.assertEqual(field.mine_hunter_state[1]['last_seen'], (5, 1))
        self.turn(arena, room)
        self.assertIsNone(field.mine_hunter_state[1]['target_id'])
        self.assertIsNone(field.mine_hunter_state[1]['last_seen'])

    def test_one_mutant_cannot_reveal_enemy_to_another(self):
        arena, room, field = self.scene([mutant(ap=1, sight=4),
            mutant(2, (20, 1), ap=1, sight=2), human(position=(5, 1))])
        self.assertIn(10, bot_known(field, MUTANT_OWNER, 1))
        self.assertNotIn(10, bot_known(field, MUTANT_OWNER, 2))
        self.turn(arena, room)
        self.assertEqual(field.mine_hunter_state[1]['last_seen'], (5, 1))
        self.assertIsNone(field.mine_hunter_state[2]['last_seen'])
        self.assertIsNone(field.mine_hunter_state[2]['target_id'])

    def test_restored_snapshot_resumes_identical_memory_and_actions(self):
        arena, room, field = self.scene([mutant(ap=1, sight=4), human(position=(5, 1))])
        self.turn(arena, room)
        field._actors[10] = replace(field.actor(10), x=25, y=25)
        restored, _ = loads(dumps(arena, clock=lambda: 0, wall=lambda: 0),
                            clock=lambda: 0, wall=lambda: 0)
        restored_field = restored._fields[room]
        self.assertEqual(restored_field.mine_hunter_state, field.mine_hunter_state)
        self.assertIs(restored_field.combat.field, restored_field)
        self.assertEqual(self.turn(arena, room), self.turn(restored, room))
        self.assertEqual(restored_field.actor(1), field.actor(1))
        self.assertEqual(restored_field.mine_hunter_state, field.mine_hunter_state)

    def test_older_snapshot_without_hunter_state_initializes_on_next_turn(self):
        arena, room, field = self.scene([mutant(), human(position=(2, 2))])
        if hasattr(field, 'mine_hunter_state'):
            del field.mine_hunter_state
        restored, _ = loads(dumps(arena, clock=lambda: 0, wall=lambda: 0),
                            clock=lambda: 0, wall=lambda: 0)
        attacks, steps = self.turn(restored, room)
        self.assertEqual(steps, ())
        self.assertEqual(len(attacks), 4)
        self.assertEqual(restored._fields[room].mine_hunter_state[1]['last_seen'], (2, 2))

    def test_patrol_visits_multiple_waypoints_within_spawn_region(self):
        arena, room, field = self.scene([mutant(), human(position=(25, 25))])
        waypoints = set(field.bot_patrol_waypoints[1])
        self.assertGreaterEqual(len(waypoints), 3)
        visited = {(field.actor(1).x, field.actor(1).y)}
        for _ in range(5):
            attacks, steps = self.turn(arena, room)
            self.assertEqual(attacks, ())
            self.assertTrue(set(steps) <= field.bot_patrol_regions[1])
            visited.update(steps)
        self.assertGreaterEqual(len(visited & waypoints), 3)

    def test_raider_account_is_a_target_even_with_miners_in_room(self):
        arena, room, field = self.scene([mutant(), human(position=(25, 25)),
            human(11, (2, 2), owner=RAIDER_OWNER)])
        attacks, steps = self.turn(arena, room)
        self.assertEqual(steps, ())
        self.assertEqual(len(attacks), 4)
        self.assertTrue(all(a.target == (2, 2) for a in attacks))
        self.assertLess(field.actor(11).health, 1000)
        self.assertEqual(field.actor(10).health, 1000)

    def test_unreachable_visible_enemy_does_not_block_reachable_enemy(self):
        ring = {(x, y) for x in range(2, 5) for y in range(0, 3) if (x, y) != (3, 1)}
        arena, room, field = self.scene([mutant(sight=9), human(position=(3, 1)),
            human(11, (1, 7))], blocked=ring, transparent=ring)
        self.assertIn(10, bot_known(field, MUTANT_OWNER, 1))
        self.assertIn(11, bot_known(field, MUTANT_OWNER, 1))
        attacks, steps = self.turn(arena, room)
        self.assertTrue(steps)
        self.assertTrue(attacks)
        self.assertTrue(all(a.target == (1, 7) for a in attacks))
        self.assertEqual(field.actor(10).health, 1000)
        self.assertLess(field.actor(11).health, 1000)

    def test_target_selection_uses_actual_route_cost_instead_of_distance(self):
        wall = {(2, y) for y in range(9)}
        arena, room, field = self.scene([mutant(sight=9), human(position=(4, 1)),
            human(11, (1, 7))], blocked=wall, transparent=wall)
        # The first enemy is closer in coordinates but needs a long detour.
        self.assertIn(10, bot_known(field, MUTANT_OWNER, 1))
        self.assertIn(11, bot_known(field, MUTANT_OWNER, 1))
        attacks, steps = self.turn(arena, room)
        self.assertEqual(len(steps), 5)
        self.assertEqual(len(attacks), 3)
        self.assertTrue(all(a.target == (1, 7) for a in attacks))
        self.assertEqual(field.actor(10).health, 1000)

    def test_killing_target_replans_remaining_attacks_in_same_turn(self):
        arena, room, field = self.scene([mutant(),
            replace(human(position=(2, 1)), health=1), human(11, (1, 2))])
        attacks, steps = self.turn(arena, room)
        self.assertEqual(steps, ())
        self.assertEqual(tuple(a.target for a in attacks),
                         ((2, 1), (1, 2), (1, 2), (1, 2)))
        self.assertEqual(field.actor(10).health, 0)
        self.assertLess(field.actor(11).health, 1000)

    def test_planted_mine_effects_keep_packets_flat_and_hunter_active(self):
        from tio.battle_hazards import PlantedMine
        arena, room, field = self.scene([mutant(), human()])
        field.combat.mines[1] = PlantedMine(1, field.actor(10), 321, 2, 1, 10, 0, 1)
        packets = play_turn(arena, room, MUTANT_OWNER)
        self.assertTrue(all(isinstance(p, bytes) for p in packets))
        attacks = tuple(decode_attack_result(p) for p in packets if p[:1] == b'\x4b')
        self.assertEqual(field.actor(1).health, 140)
        self.assertEqual(field.combat.mines, {})
        self.assertEqual(len([a for a in attacks if a.actor_id == 1]), 3)
        self.assertTrue(any(a.weapon_id == 321 and a.hits[0].actor_id == 1 for a in attacks))

    def test_mine_effects_respect_real_view_visibility_and_private_inventory(self):
        from tio.battle_hazards import PlantedMine
        for visible in (True, False):
            with self.subTest(visible=visible):
                arena, room, field = self.scene([mutant(),
                    human(position=(6, 1) if visible else (25, 25))])
                field.bot_patrol_waypoints[1] = ((7, 1), (1, 1))
                field.combat.mines[1] = PlantedMine(1, field.actor(10), 321, 2, 1, 10, 0, 1)
                view = self.view(field, MINER_OWNER)
                packets = play_turn(arena, room, MUTANT_OWNER, view=view)
                self.assertTrue(all(isinstance(p, bytes) for p in packets))
                self.assertEqual(field.actor(1).health, 140)
                self.assertFalse(any(p[:1] == b'\x30' and
                    int.from_bytes(p[1:5], 'little') == 1 for p in packets))
                attacks = [decode_attack_result(p) for p in packets if p[:1] == b'\x4b']
                if visible:
                    self.assertTrue(any(a.weapon_id == 321 and
                        any(h.actor_id == 1 for h in a.hits) for a in attacks))
                else:
                    self.assertFalse(any(h.actor_id == 1 for a in attacks for h in a.hits))
                    self.assertFalse(any(p[:1] in (b'\x3d', b'\x4e') and
                        int.from_bytes(p[1:5], 'little') == 1 for p in packets))

    def test_personal_perception_respects_smoke_and_flare_light(self):
        from tio.battle_item_effects import initialize, refresh_sight
        _, _, field = self.scene([mutant(sight=4), human(position=(5, 1))])
        state = initialize(field.combat)
        self.assertIn(10, bot_known(field, MUTANT_OWNER, 1))
        state['areas'][1] = dict(kind='smoke', center=(3, 1), radius=1,
                                 source=10, owner=MINER_OWNER, expiry=10)
        self.assertNotIn(10, bot_known(field, MUTANT_OWNER, 1))
        state['areas'].clear()
        field.item_darkness = True
        refresh_sight(field.combat)
        self.assertNotIn(10, bot_known(field, MUTANT_OWNER, 1))
        state['areas'][2] = dict(kind='flare', center=(5, 1), radius=1,
                                 source=10, owner=MINER_OWNER, expiry=10)
        self.assertIn(10, bot_known(field, MUTANT_OWNER, 1))


if __name__ == '__main__':
    unittest.main()
