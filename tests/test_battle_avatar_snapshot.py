"""Battle soldier snapshots keep the selected avatar.

Native RECV_BattleSoldierAdd (8c5044) copies 0x8c581d into model+60DC, the same
field FC assigns. A post-shot 3B with zero erased the portrait until the next
movement resent FC; snapshots must carry the actor's avatar themselves.
"""
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace

import test_battle_skill_lists
import test_shared_team_arena
from test_combat import item
from tio.avatars import catalog
from tio.protocol.abilities import AbilityEntry
from tio.protocol.battle_attack import AttackRequest, encode_attack_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.protocol.item_list import encode_item_list

AVATAR = sorted(catalog())[0]


def avatars(packets, combat):
    return {int.from_bytes(p[1:5], 'little'):
            decode_battle_soldier(p, human_equipment=combat.human.get(int.from_bytes(p[1:5], 'little'), True))
            .fields['0x8c581d'] for p in packets if p[:1] == b'\x3b'}


class SharedShotAvatarTests(unittest.TestCase):
    setUp = test_shared_team_arena.SharedTeamTests.setUp
    send = test_shared_team_arena.SharedTeamTests.send
    create = test_shared_team_arena.SharedTeamTests.create
    paired = test_shared_team_arena.SharedTeamTests.paired
    open_battle = test_shared_team_arena.SharedTeamTests.open_battle

    def test_shooter_snapshot_after_the_shot_keeps_its_avatar(self):
        owners, battle = self.open_battle(); field = battle['field']
        attacker = field.actor_ids(owners[0])[0]; victim = field.actor_ids(owners[1])[0]
        field.avatar_ids = {attacker: AVATAR}
        field._actors[victim] = replace(field.actor(victim), x=5, y=6)
        replies = self.send(0, encode_attack_request(AttackRequest(attacker, 5, 6)))
        shown = avatars(replies, field.combat)
        self.assertIn(attacker, shown)
        self.assertEqual(shown[attacker], AVATAR)

    def test_hidden_enemy_snapshots_do_not_disclose_an_avatar(self):
        owners, battle = self.open_battle(); field = battle['field']
        enemy = field.actor_ids(owners[1])[0]
        field.avatar_ids = {enemy: AVATAR}
        view = battle['views'][owners[0]]
        packet = view.snapshot(enemy, hidden=True, health=1)
        self.assertEqual(decode_battle_soldier(packet, human_equipment=True).fields['0x8c581d'], 0)


class PrivateShotAvatarTests(unittest.TestCase):
    setUp = test_battle_skill_lists.EncounterSkillListTests.setUp
    travel = test_battle_skill_lists.EncounterSkillListTests.travel
    miner = test_battle_skill_lists.EncounterSkillListTests.miner

    def test_private_attack_reply_snapshot_keeps_its_avatar(self):
        from tio.arena_service import ArenaService
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tio.squad import SquadStore
        from tools.encounter_scene import prepare_encounter
        self.miner(5)
        self.service.state.replace('alice', 1, (AbilityEntry(22, 1, 0, 1),), expected_revision=0)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=?',
                       (encode_item_list(1, (item(3001, 335, equipped=True),)),))
        SquadStore(self.path).assign('alice', 1, 1)
        arena = ArenaService(clock=lambda: self.now[0])
        ticket = SurvivalQueue().join(42, OwnedPetStore(self.path).list('alice'))
        scene = prepare_encounter(self.path, 'alice', ticket, self.service.catalog, seed=5)
        arena.start_survival(42, b'Alice', scene)
        arena.member_loaded(42, b'\x36')
        field = scene.field; field.avatar_ids = {1: AVATAR}
        me = field.actor(1); dog = field.actor_ids(scene.bot_owner)[0]
        occupied = {(a.x, a.y) for a in field._actors.values()}
        cell = next(p for p in ((me.x - 1, me.y), (me.x + 1, me.y), (me.x, me.y + 1), (me.x, me.y - 1))
                    if field.inside(*p) and p not in field.blocked and p not in occupied)
        field._actors[dog] = replace(field.actor(dog), x=cell[0], y=cell[1])
        arena.begin_turn_packets(42, (1,), 40)
        scene.visibility.refresh()
        replies = arena.attack(42, encode_attack_request(AttackRequest(1, *cell)), view=scene.visibility)
        shown = avatars(replies, field.combat)
        self.assertIn(1, shown)
        self.assertEqual(shown[1], AVATAR)
        self.assertEqual(scene.visibility.templates[1].fields['0x8c581d'], AVATAR)


if __name__ == '__main__':
    unittest.main()
