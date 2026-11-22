"""Wild Miner gunners: original client mob 102 (mobs.udf) with the AK 47 (304).

They share the band's level, HP and armour with the melee mutants and use the
ordinary AK 47 rules, so they shoot from range instead of closing to melee.
"""
from dataclasses import replace
import unittest
from xml.etree import ElementTree

import test_mining as fixture
from test_combat import FixedRandom
from tio.crystal_market import POLICY
from tio.item_presentation import NEW, ORIGINAL, items_xml
from tio.protocol.battle_attack import AttackRequest
from tio.protocol.item_list import decode_item_list, encode_item_list

AK47 = 304
WILD_MINER = 102


class MineGunnerTests(unittest.TestCase):
    setUp = fixture.MiningTests.setUp

    def mobs(self):
        return self.field.actor_ids(self.scene.bot_owner)

    def gunners(self):
        return [i for i in self.mobs() if self.field.combat.resources[i] == WILD_MINER]

    def equipped_weapon(self, identity):
        items = decode_item_list(self.field.combat.inventories[identity])[1]
        return next(i for i in items if i.equipped and i.client_slot == 16)

    def ammo(self, identity):
        items = decode_item_list(self.field.combat.inventories[identity])[1]
        return sum(i.count for i in items if i.template_id == 7)

    def isolate(self, gunner, distance):
        """Open ground: the player stands `distance` cells east of the gunner."""
        self.field.blocked = frozenset();self.field.transparent_obstacles = frozenset()
        for i in self.mobs():
            if i != gunner:self.field._actors[i] = replace(self.field.actor(i), health=0)
        self.field.combat.inventories[self.identity] = encode_item_list(self.identity, ())
        self.field._actors[self.identity] = replace(self.field.actor(self.identity), x=10+distance, y=10,
                                                    health=5000, max_health=5000)
        self.field._actors[gunner] = replace(self.field.actor(gunner), x=10, y=10)

    def test_mine_keeps_ten_mobs_with_configured_gunners(self):
        self.assertEqual(len(self.mobs()), POLICY['mob_count'])
        self.assertEqual(len(self.gunners()), POLICY['gunners']['count'])
        self.assertGreater(len(self.gunners()), 0)

    def test_gunner_is_native_wild_miner_with_band_stats_and_ak47(self):
        for identity in self.gunners():
            actor = self.field.actor(identity);fields = self.scene.visibility.templates[identity].fields
            self.assertEqual((actor.health, actor.action_points, self.field.combat.defense(identity)), (150, 15, 160))
            self.assertEqual((fields['0x8c50fb'], fields['0x8c52cf'], fields['0x8c5731']), (WILD_MINER, AK47, 160))
            self.assertEqual((fields['0x8c571d'], fields['0x8c5694']), (15, 15))
            self.assertEqual(fields['0x8c5116'], b'Wild Miner')
            self.assertEqual(self.equipped_weapon(identity).template_id, AK47)
            self.assertEqual(actor.weapons[0].max_range, 9)

    def test_wild_miner_body_is_in_both_delivered_catalogues(self):
        for interface in (NEW, ORIGINAL):
            with self.subTest(interface=interface):
                bodies = ElementTree.fromstring(items_xml(interface)).findall("item[@id='65514']")
                self.assertEqual(len(bodies), 1)
                values = {node.get('key'): node.get('val') for node in bodies[0]}
                self.assertEqual(values['bodypart'], 'chest')
                self.assertEqual(values['model_1'], 'mob_wildminer')
                self.assertEqual(values['texture_1'], 'mob_wildminer.jpg')

    def test_gunner_shoots_from_range_spending_ap_and_ammo_without_wear(self):
        gunner = self.gunners()[0];self.isolate(gunner, 4)
        weapon, ammo = self.equipped_weapon(gunner), self.ammo(gunner)
        self.field.combat.attack(self.scene.bot_owner, AttackRequest(gunner, 14, 10))
        self.assertEqual(self.field.actor(gunner).action_points, 10)
        self.assertEqual(self.ammo(gunner), ammo-5)
        self.assertEqual(self.equipped_weapon(gunner), weapon)

    def test_gunner_ai_fires_without_closing_to_melee(self):
        from tio.arena_service import ArenaService
        from tio.training_bot import play_turn
        from tio.protocol.battle_turn import encode_end_turn
        arena = ArenaService(clock=lambda:0);room, _ = arena.start_survival(42, b'Alice', self.scene)
        arena.member_loaded(42, b'\x36');arena.begin_turn_packets(42, (self.identity,), 40)
        gunner = self.gunners()[0];self.isolate(gunner, 4)
        ammo = self.ammo(gunner)
        arena.end_turn(42, encode_end_turn(self.identity))
        play_turn(arena, room.room_id, self.scene.bot_owner, view=self.scene.visibility)
        self.assertEqual((self.field.actor(gunner).x, self.field.actor(gunner).y), (10, 10))
        self.assertLess(self.field.actor(self.identity).health, 5000)
        self.assertEqual(self.field.actor(gunner).action_points, 0)
        self.assertEqual(self.ammo(gunner), ammo-15)

    def test_gunner_kill_gives_no_rank_like_other_mutants(self):
        from tio.ranks import battle_report
        combat = self.field.combat;gunner = self.gunners()[0]
        combat.rank_kills = [(gunner, self.identity)]
        self.field._actors[self.identity] = replace(self.field.actor(self.identity), health=0)
        self.assertEqual(battle_report(combat, 42), {self.identity:(0, True, False)})

    def test_dead_gunner_drops_no_weapon_or_ammunition(self):
        gunner = self.gunners()[0];self.isolate(gunner, 1)
        self.field._actors[gunner] = replace(self.field.actor(gunner), health=1)
        self.field._actors[self.identity] = replace(self.field.actor(self.identity), action_points=20)
        combat = self.field.combat
        combat.rng = FixedRandom()
        combat.inventories[self.identity] = encode_item_list(self.identity, ())
        combat.attack(42, AttackRequest(self.identity, 10, 10))
        self.assertEqual(self.field.actor(gunner).health, 0)
        self.assertNotIn((10, 10), self.field.loot.ground)


class SharedMineGunnerTests(unittest.TestCase):
    setUp = fixture.MiningTests.setUp

    def test_shared_mine_keeps_gunner_identity_and_template(self):
        import json
        from tools.mining_scene import prepare_shared_mining
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tio.abilities import AbilityCatalog, AbilityLevel
        catalog = AbilityCatalog(AbilityLevel(r['id'], r['level'], r['fields'])
                                 for r in json.loads((fixture.ROOT/'config/abilities.json').read_text())['records'])
        ticket = SurvivalQueue().join(42, OwnedPetStore(self.path).list('probe_user'))
        scene = prepare_shared_mining(self.path, (('probe_user', ticket, 1),), catalog, seed=4)
        field = scene.field;mobs = field.actor_ids(scene.bot_owner)
        gunners = [i for i in mobs if field.combat.resources[i] == WILD_MINER]
        self.assertEqual(len(gunners), POLICY['gunners']['count'])
        for i in gunners:
            self.assertEqual(scene.visibility.templates[i].fields['0x8c50fb'], WILD_MINER)
            self.assertEqual(field.actor(i).action_points, 15)
            items = decode_item_list(field.combat.inventories[i])[1]
            self.assertTrue(any(item.template_id == AK47 and item.equipped for item in items))
        self.assertEqual({field.combat.resources[i] for i in mobs if i not in gunners}, {100})


if __name__ == '__main__':unittest.main()
