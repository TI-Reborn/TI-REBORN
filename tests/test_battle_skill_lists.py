"""Battle skill lists reach the owner once the scene actors exist.

The native client binds 80 to an existing battle actor (8b0eac) and the
city-to-battle teardown clears every actor's skills (a8441c). A list sent with
the scene can therefore be lost; the first turn resends it before 7F/01.
"""
import struct
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace

import test_miner_abilities
import test_shared_team_arena
from test_combat import item
from tio.protocol.abilities import AbilityEntry, decode_abilities
from tio.protocol.item_list import encode_item_list


def skill_lists(packets):
    return {decode_abilities(p)[0]: decode_abilities(p)[1] for p in packets if p[:1] == b'\x80'}


class EncounterSkillListTests(unittest.TestCase):
    setUp = test_miner_abilities.MinerAbilityTests.setUp
    travel = test_miner_abilities.MinerAbilityTests.travel
    miner = test_miner_abilities.MinerAbilityTests.miner

    def encounter(self, hammer_slot=16):
        from tio.arena_service import ArenaService
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tio.squad import SquadStore
        from tools.encounter_scene import prepare_encounter
        self.miner(5)
        self.service.state.replace('alice', 1, (AbilityEntry(22, 3, 0, 1),), expected_revision=0)
        with closing(sqlite3.connect(self.path)) as db, db:
            hammer = replace(item(3001, 335, equipped=True), location_raw=hammer_slot)
            db.execute('UPDATE owned_pets SET inventory_packet=?', (encode_item_list(1, (hammer,)),))
        SquadStore(self.path).assign('alice', 1, 1)
        arena = ArenaService(clock=lambda: self.now[0])
        ticket = SurvivalQueue().join(42, OwnedPetStore(self.path).list('alice'))
        scene = prepare_encounter(self.path, 'alice', ticket, self.service.catalog, seed=5)
        arena.start_survival(42, b'Alice', scene)
        arena.member_loaded(42, b'\x36')
        return arena, scene.field

    def test_first_turn_resends_the_slash_list_before_its_status(self):
        arena, field = self.encounter()
        packets = arena.begin_turn_packets(42, field.living_actor_ids(42), 40)
        self.assertIn(22, {e.ability_id for e in skill_lists(packets)[1]})
        listed = next(i for i, p in enumerate(packets) if p[:1] == b'\x80')
        status = next(i for i, p in enumerate(packets) if p[:2] == b'\x7f\x01')
        self.assertLess(listed, status)
        self.assertEqual(packets[-1][:1], b'\x38')

    def test_later_turns_do_not_reset_the_client_skill_list(self):
        arena, field = self.encounter()
        arena.begin_turn_packets(42, field.living_actor_ids(42), 40)
        arena._turns.clear()
        packets = arena.begin_turn_packets(42, field.living_actor_ids(42), 40)
        self.assertFalse(skill_lists(packets))


    def test_slash_cooldown_counts_three_own_turns_then_hits_again(self):
        from dataclasses import replace
        from tio.protocol.ability_cast import AbilityCast, encode_ability_cast
        from tio.protocol.ability_status import decode_ability_status
        arena, field = self.encounter()
        me = field.actor(1)
        dog = field.actor_ids(0x7fffffff)[0]
        occupied = {(a.x, a.y) for a in field._actors.values()}
        cell = next(p for p in ((me.x - 1, me.y), (me.x + 1, me.y), (me.x, me.y + 1), (me.x, me.y - 1))
                    if field.inside(*p) and p not in field.blocked and p not in occupied)
        field._actors[dog] = replace(field.actor(dog), x=cell[0], y=cell[1], health=999, max_health=999)
        cast = encode_ability_cast(AbilityCast(22, 1, 0, *cell))

        def turn():
            arena._turns.clear()
            packets = arena.begin_turn_packets(42, (1,), 40)
            status = [e for p in packets if p[:2] == b'\x7f\x01' for e in decode_ability_status(p)[1]]
            return next((e.state, e.remaining) for e in status if e.ability_id == 22)

        self.assertEqual(turn(), (4, 0))
        replies = arena.cast_ability(42, cast)
        self.assertIn((22, 3, 3), [(e.ability_id, e.state, e.remaining) for p in replies
                                   if p[:2] == b'\x7f\x01' for e in decode_ability_status(p)[1]])
        first = field.actor(dog).health
        for remaining in (2, 1):
            self.assertEqual(turn(), (3, remaining))
            with self.assertRaisesRegex(ValueError, 'cooling'):
                arena.cast_ability(42, cast)
        self.assertEqual(turn(), (4, 0))
        hits_before = field.actor(dog).health
        self.assertEqual(hits_before, first)
        rolls = iter((0, 0, 99))  # hit, no critical
        field.combat.rng = type('R', (), {'randrange': lambda s, n: next(rolls), 'randint': lambda s, a, b: a,
                                          'getstate': lambda s: None, 'setstate': lambda s, v: None})()
        arena.cast_ability(42, cast)
        self.assertLess(field.actor(dog).health, hits_before)


    def test_swapping_the_hammer_into_the_hand_shows_slash_with_its_state(self):
        from tio.protocol.ability_status import decode_ability_status
        arena, field = self.encounter(hammer_slot=128)
        swap = bytes((0x6d,)) + (1).to_bytes(4, 'little')
        first = arena.begin_turn_packets(42, (1,), 40)
        self.assertNotIn(22, {e.ability_id for e in skill_lists(first)[1]})
        replies = arena.swap_weapons(42, swap)
        self.assertIn(22, {e.ability_id for e in skill_lists(replies)[1]})
        listed = next(i for i, p in enumerate(replies) if p[0] == 0x80)
        status = [(i, e) for i, p in enumerate(replies) if p[:2] == bytes((0x7f, 1))
                  for e in decode_ability_status(p)[1] if e.ability_id == 22]
        self.assertTrue(status)
        self.assertGreater(status[0][0], listed)
        self.assertEqual((status[0][1].state, status[0][1].remaining), (4, 0))
        back = arena.swap_weapons(42, swap)
        self.assertNotIn(22, {e.ability_id for e in skill_lists(back)[1]})


class SharedArenaSkillListTests(unittest.TestCase):
    setUp = test_shared_team_arena.SharedTeamTests.setUp
    send = test_shared_team_arena.SharedTeamTests.send
    create = test_shared_team_arena.SharedTeamTests.create
    paired = test_shared_team_arena.SharedTeamTests.paired

    def test_each_account_receives_only_its_own_lists_on_its_first_turn(self):
        owners, battle = self.paired()
        field = battle['field']
        self.send(0, b'\x36'); self.send(1, b'\x36'); self.hub.tick()
        first = tuple(self.hub.queues[owners[0]])
        other = tuple(self.hub.queues[owners[1]])
        own = set(field.actor_ids(owners[0]))
        self.assertEqual(set(skill_lists(first)), own)
        self.assertFalse(set(skill_lists(other)))


if __name__ == '__main__':
    unittest.main()
