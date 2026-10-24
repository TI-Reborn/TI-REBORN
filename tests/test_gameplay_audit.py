"""Regressions for the October 24 gameplay audit, with original rule boundaries."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest

import test_armor_equipment as armor_fixture
import test_enhancement as enhancement_fixture
import test_mining as mining_fixture
from tio.armor import ArmorCatalog
from tio.enhancement import EnhancementStore
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.item_action import ItemAction


class SpecialEditionTests(unittest.TestCase):
    setUp = enhancement_fixture.EnhancementTests.setUp
    seed = enhancement_fixture.EnhancementTests.seed
    saved = enhancement_fixture.EnhancementTests.saved

    def test_failed_se_upgrade_restores_initial_state_even_at_zero_durability(self):
        for template in (248, 249, 250, 251, 252, 253, 256, 264, 266):
            with self.subTest(template=template):
                target = replace(enhancement_fixture.item(1001, template, 7),
                                 unknown_words=(0, 0, 955))
                self.seed(target, enhancement_fixture.item(1002, 30))
                result = EnhancementStore(self.path, randbelow=lambda _: 99).handle(
                    'alice', enhancement_fixture.request())
                saved, = decode_item_list(self.saved())[1]
                self.assertEqual((result.outcome, result.level), ('reset', 0))
                self.assertEqual(saved.instance_id, target.instance_id)
                self.assertEqual(saved.unknown_words, (self.rules.items[template]['durability'],) * 3)
                self.assertEqual(saved.unknown_bytes_03[0], 0)


class ComplexArmorTests(unittest.TestCase):
    setUp = armor_fixture.ArmorTests.setUp
    seed = armor_fixture.ArmorTests.seed
    wear = armor_fixture.ArmorTests.wear

    def test_female_exo_conflicts_with_all_three_armor_slots_in_both_directions(self):
        for template in (263, 264):
            for replacement, option in ((1001, 0), (1002, 2), (1003, 3)):
                with self.subTest(template=template, replacement=replacement):
                    self.seed((242, 243, 244, template), female=True)
                    for identity, slot in ((1001, 0), (1002, 2), (1003, 3)):
                        self.wear(identity, slot)
                    bag = self.wear(1004, 2)
                    items = decode_item_list(bag)[1]
                    self.assertEqual([i.equipped for i in items], [0, 0, 0, 1])
                    self.assertEqual(ArmorCatalog().defense(bag, human=True), 208)
                    bag = self.wear(replacement, option)
                    self.assertEqual(decode_item_list(bag)[1][3].equipped, 0)
                    self.assertEqual({i.instance_id for i in decode_item_list(bag)[1]},
                                     {1001, 1002, 1003, 1004})


    def test_legacy_exo_and_helmet_snapshot_cannot_stack_defense(self):
        self.seed((242, 264), female=True)
        bag = self.pets.inventory('alice', 1)
        items = decode_item_list(bag)[1]
        invalid = encode_item_list(1, (replace(items[0], unknown_u8_01=1, location_raw=1),
                                      replace(items[1], unknown_u8_01=1, location_raw=4)))
        self.assertEqual(ArmorCatalog().defense(invalid, human=True), 208)
        self.assertEqual(decode_item_list(invalid)[1][0].equipped, 1)


class MineCapacityTests(unittest.TestCase):
    setUp = mining_fixture.MiningTests.setUp

    def prepare_exo_drill(self):
        from test_combat import item
        combat = self.field.combat
        actor = self.field.actor(self.identity)
        exo = replace(item(8000, 264), unknown_u8_01=1, location_raw=4,
                      unknown_words=(500, 500, 500))
        combat.inventories[self.identity] = encode_item_list(self.identity, (exo,))
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                             (combat.inventories[self.identity], 'probe_user', self.identity))
        combat.resources[self.identity] = 2
        # Includes base and trained carry perk, excludes the dynamic Exo bonus.
        combat.weight_capacities[self.identity] = 1225
        deposit = next(iter(self.mine.deposits.values()))
        deposit.drill = replace(item(8001, 52), unknown_u32_01=0)
        deposit.extracted = 1001
        self.field._actors[self.identity] = replace(actor, x=deposit.position[0],
                                                    y=deposit.position[1])
        return combat, deposit

    def test_exact_capacity_accepts_full_drill_using_equipment_bonus(self):
        from tio.weight import inventory_weight
        combat, deposit = self.prepare_exo_drill()
        self.mine.pickup(42, self.identity, *deposit.position, 1000)
        self.assertEqual(inventory_weight(combat.inventories[self.identity]),
                         combat.weight_capacity(self.identity))

    def test_overweight_rejection_preserves_turn_and_a_subsequent_action_works(self):
        combat, deposit = self.prepare_exo_drill()
        actor = self.field.actor(self.identity)
        old_inventory = combat.inventories[self.identity]
        with self.assertRaises(ValueError):
            self.mine.pickup(42, self.identity, *deposit.position, 1001)
        self.assertEqual(self.field.actor(self.identity), actor)
        self.assertEqual(combat.inventories[self.identity], old_inventory)
        self.assertEqual(deposit.carried, 0)
        self.mine.pickup(42, self.identity, *deposit.position, 1000)
        self.assertEqual(self.field.actor(self.identity).action_points, actor.action_points - 1)



class DismissalTests(unittest.TestCase):
    def setUp(self):
        import test_service_operations as services_fixture
        self.fixture = services_fixture.ServiceOperationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.path = self.fixture.case.path

    def test_secondary_owned_starter_without_hire_history_can_be_dismissed(self):
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        from tio.services_completion import ServicesCompletion
        with closing(sqlite3.connect(self.path)) as database:
            packet = database.execute("SELECT pet_packet FROM owned_pets WHERE account='alice' AND pet_id=1").fetchone()[0]
        pet = decode_pet_info(packet, human_equipment=True)
        packet = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c43eb': 777}))
        OwnedPetStore(self.path).ensure('alice', packet, encode_item_list(777, ()), human=True)
        service = ServicesCompletion(self.path, clock=lambda: 1000)
        result = service.schedule_dismiss('alice', 777, identity='audit-dismissal', allowed=True)
        self.assertEqual(result['receipt']['dismissAt'], 173800)
        self.assertTrue(OwnedPetStore(self.path).inventory('alice', 777))
        service.clock = lambda: 173800
        self.assertEqual(service.finalize_due('alice', allowed=True)['completed'], [777])
        self.assertIsNone(OwnedPetStore(self.path).inventory('alice', 777))

    def test_main_actor_and_inventory_are_still_protected(self):
        from tio.services_completion import ServiceRejected
        with self.assertRaises(ServiceRejected):
            self.fixture.manager.helper.schedule_dismiss('alice', 1, identity='audit-main', allowed=True)


class InjectionAndBoosterTests(unittest.TestCase):
    def test_injection_preserves_original_capacity_effect_and_does_not_heal(self):
        from test_battle_item_effects import BattleItemFixture
        from tio import battle_item_effects, combat_completion
        for health in (50, 199, 200):
            fixture = BattleItemFixture()
            field, combat = fixture.prepare(5012)
            field._actors[1] = replace(field.actor(1), health=health)
            replies = battle_item_effects.use(combat, 7, ItemAction(1, 100, 255))
            self.assertEqual((field.actor(1).health, field.actor(1).max_health), (health, 220))
            self.assertEqual(field.actor(1).action_points, 32)
            self.assertFalse(decode_item_list(combat.inventories[1])[1])
            self.assertEqual(replies[0], combat_completion.encode_max_health(1, 220))
            field._ability_turns[1] = 9
            combat_completion.end_turn(combat, 7, (1,))
            self.assertEqual((field.actor(1).health, field.actor(1).max_health), (health, 200))

    def test_ultra_blocker_activates_for_eight_hours_and_stays_account_local(self):
        from test_battle_item_effects import BoosterAccountTests
        from tio.item_boosters import use_saved, active, nontransferable
        fixture = BoosterAccountTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seed(5011)
        result = use_saved(fixture.path, 'alice', ItemAction(1, 100, 255), now=1000)
        self.assertFalse(decode_item_list(result)[1])
        self.assertEqual(active(fixture.path, 'alice', 1, 1001)['block_xp'],
                         dict(template=5011, value=100, expires_at=29800))
        self.assertEqual(active(fixture.path, 'bob', 1, 1001), {})
        self.assertEqual(active(fixture.path, 'alice', 1, 29800), {})
        self.assertTrue(nontransferable(5011))
        with self.assertRaises(ValueError):
            use_saved(fixture.path, 'alice', ItemAction(1, 100, 255), now=1001)
