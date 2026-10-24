"""Manual medical/optical items across stores and authoritative combat."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import unittest

import test_credits_only as shop_fixture
from test_battle_item_effects import BattleItemFixture
from test_combat import item
from deploy.item_effect_descriptions import load_descriptions
from deploy.medical_optics_assets import patch_health_metadata, patch_night_vision_language, replacements
from tio import battle_item_effects as effects, battle_snapshot
from tio.owned_pets import OwnedPetStore
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.item_action import ItemAction
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.shop_purchase import ShopPurchase

ROOT = Path(__file__).resolve().parents[1]


class MedicalOpticsShopTests(unittest.TestCase):
    setUp = shop_fixture.CreditsOnlyTests.setUp

    def locate(self, town: int) -> None:
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute('UPDATE character_locations SET town_id=?', (town,))

    def test_both_stores_offer_approved_prices_in_mines_and_cities(self):
        for town in (2, 13, 14, 15, 16, 19, 22):
            self.locate(town)
            _, ordinary = decode_item_shop(self.shop.catalog('alice', 0))
            with closing(sqlite3.connect(self.path)) as database:
                database.execute('BEGIN')
                sc = tuple(self.sc._visible(database, 'alice').values())
            for identity, credits, durability in ((20, 300, 1), (5002, 1800, 300)):
                with self.subTest(town=town, item=identity):
                    offer = next(row for row in ordinary if row.item_id == identity)
                    self.assertEqual((offer.unknown_u32_03, offer.durability),
                                     (credits, durability))
                    offer = next(row for row in sc if row.item_id == identity)
                    self.assertEqual((offer.credits, offer.gold, offer.durability),
                                     (credits, 0, durability))

    def test_level_three_town_keeps_health_but_excludes_level_four_goggles(self):
        self.locate(3)
        _, ordinary = decode_item_shop(self.shop.catalog('alice', 0))
        with closing(sqlite3.connect(self.path)) as database:
            database.execute('BEGIN')
            sc = tuple(self.sc._visible(database, 'alice').values())
        for rows in (ordinary, sc):
            identities = {row.item_id for row in rows}
            self.assertIn(20, identities)
            self.assertNotIn(5002, identities)

    def test_two_accounts_buy_different_items_and_retry_without_double_debit(self):
        offer = next(row for row in self.cats.items[0] if row.item_id == 20)
        request = ShopPurchase(1, 0, offer.unknown_u32_01, 1)
        self.shop.purchase('alice', request, identity='medical-order')
        self.shop.purchase('alice', request, identity='medical-order')
        goggles = next(row for row in self.sc.offers.values() if row.item_id == 5002)
        request = shop_fixture.sc(6, goggles.lot_id, 1, 1)
        self.sc.handle('bob', request, identity='optical-order')
        self.sc.handle('bob', request, identity='optical-order')
        with closing(sqlite3.connect(self.path)) as database:
            wallets = dict(database.execute('SELECT account,credits FROM wallets'))
        self.assertEqual(wallets, {'alice': 99700, 'bob': 98200})
        for account, identity, durability in (('alice', 20, 1), ('bob', 5002, 300)):
            inventory = OwnedPetStore(self.path).inventory(account, 1)
            _, records, _ = decode_item_list(inventory)
            self.assertEqual(len(records), 1)
            self.assertEqual((records[0].template_id, records[0].count,
                              records[0].unknown_words),
                             (identity, 1, (durability,)*3))

    def test_insufficient_credits_does_not_grant_health_injection(self):
        offer = next(row for row in self.sc.offers.values() if row.item_id == 20)
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute("UPDATE wallets SET credits=299 WHERE account='alice'")
        before = OwnedPetStore(self.path).inventory('alice', 1)
        with self.assertRaises(ValueError):
            self.sc.handle('alice', shop_fixture.sc(6, offer.lot_id, 1, 1))
        self.assertEqual(OwnedPetStore(self.path).inventory('alice', 1), before)


class HealthInjectionTests(BattleItemFixture):
    def prepare_health(self, health: int, points: int = 8) -> None:
        self.prepare(20)
        self.field._actors[1] = replace(self.field.actor(1), health=health,
                                       action_points=points)

    def test_heals_one_hundred_for_eight_points_and_consumes_one(self):
        self.prepare_health(10)
        self.combat.use_medical(7, ItemAction(1, 100, 255))
        self.assertEqual((self.field.actor(1).health, self.field.actor(1).action_points),
                         (110, 0))
        self.assertEqual(decode_item_list(self.combat.inventories[1])[1], ())

    def test_nearly_full_health_caps_at_maximum(self):
        self.prepare_health(195)
        self.combat.use_medical(7, ItemAction(1, 100, 255))
        self.assertEqual((self.field.actor(1).health, self.field.actor(1).action_points),
                         (200, 0))

    def test_full_health_insufficient_points_and_foreign_actor_are_atomic(self):
        for health, points, owner in ((200, 8, 7), (10, 7, 7), (10, 8, 8)):
            self.prepare_health(health, points)
            before = (dict(self.field._actors), dict(self.combat.inventories))
            with self.assertRaises(ValueError):
                self.combat.use_medical(owner, ItemAction(1, 100, 255))
            self.assertEqual((self.field._actors, self.combat.inventories), before)

    def test_duplicate_use_cannot_heal_or_charge_again(self):
        self.prepare_health(10, 16)
        self.combat.use_medical(7, ItemAction(1, 100, 255))
        before = (dict(self.field._actors), dict(self.combat.inventories))
        with self.assertRaises(ValueError):
            self.combat.use_medical(7, ItemAction(1, 100, 255))
        self.assertEqual((self.field._actors, self.combat.inventories), before)


class NightVisionManualTests(BattleItemFixture):
    def test_description_includes_active_armor_and_two_cell_bonus(self):
        descriptions = load_descriptions(ROOT)
        self.assertIn('20', descriptions['ru'][5002][0])
        self.assertIn('+2', descriptions['ru'][5002][0])
        self.assertEqual(len(descriptions['ru'][5002]), 2)
        self.assertIn('3 AP', descriptions['en'][5002][1])

    def test_dark_battle_bonus_and_armor_apply_only_to_the_user(self):
        self.prepare(5002)
        self.field.item_darkness = True
        effects.refresh_sight(self.combat)
        before = self.field.actor(1).sight_radius
        other = self.field.actor(2)
        effects.use(self.combat, 7, ItemAction(1, 100, 255))
        self.assertEqual(self.field.actor(1).sight_radius, before+2)
        self.assertEqual(effects.armor_bonus(self.combat, 1), 20)
        self.assertEqual(effects.armor_bonus(self.combat, 2), 0)
        self.assertEqual(self.field.actor(2), other)

    def test_three_points_per_turn_survive_reconnect_and_are_not_charged_twice(self):
        self.prepare(5002)
        self.field.item_darkness = True
        effects.use(self.combat, 7, ItemAction(1, 100, 255))
        restored, _ = battle_snapshot.loads(battle_snapshot.dumps(self.field))
        restored.prepare_turn(7, (1,))
        effects.begin_turn(restored.combat, 7, (1,))
        self.assertEqual(restored.actor(1).action_points, 37)
        self.assertEqual(effects.begin_turn(restored.combat, 7, (1,)), ())
        self.assertEqual(restored.actor(1).action_points, 37)

    def test_level_three_cannot_activate_and_zero_points_can_deactivate(self):
        self.prepare(5002)
        self.field.item_darkness = True
        self.combat.rank_profiles[1] = (3, 0)
        with self.assertRaises(ValueError):
            effects.use(self.combat, 7, ItemAction(1, 100, 255))
        self.combat.rank_profiles[1] = (4, 0)
        effects.use(self.combat, 7, ItemAction(1, 100, 255))
        self.field._actors[1] = replace(self.field.actor(1), action_points=0)
        effects.use(self.combat, 7, ItemAction(1, 100, 255))
        self.assertEqual(effects.armor_bonus(self.combat, 1), 0)
        self.assertEqual(self.field.actor(1).action_points, 0)


class SharedMineMedicalOpticsTests(unittest.TestCase):
    def test_two_accounts_keep_private_items_and_use_both_native_actions(self):
        import test_shared_mine_arena as fixture
        from tio.protocol.item_action import encode_item_action
        from tio.protocol.night_vision_state import decode_night_vision_state

        case = fixture.SharedMineArenaTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        session = case.case.sessions[0]
        with closing(sqlite3.connect(case.path)) as database, database:
            raw = database.execute('SELECT inventory_packet FROM owned_pets '
                                   'WHERE account=? AND pet_id=1',
                                   (session.account,)).fetchone()[0]
            identity, records, flag = decode_item_list(raw)
            raw = encode_item_list(identity, (*records, item(9901, 20),
                                             item(9902, 5002)), flag)
            database.execute('UPDATE owned_pets SET inventory_packet=? '
                             'WHERE account=? AND pet_id=1', (raw, session.account))
        battle = case.enter((0, 1))
        field = battle['field']
        actor_id = field.actor_ids(case.owners[0])[0]
        other_id = field.actor_ids(case.owners[1])[0]
        before_other = field.combat.inventories[other_id]
        with case.hub.journal.unit(battle):
            field._actors[actor_id] = replace(field.actor(actor_id), health=10)
        points = field.actor(actor_id).action_points
        replies = case.send(0, encode_item_action(ItemAction(actor_id, 9901, 255)))
        self.assertTrue(any(packet[:1] == b'\x30' for packet in replies))
        self.assertEqual((field.actor(actor_id).health,
                          field.actor(actor_id).action_points), (110, points-8))
        sight = field.actor(actor_id).sight_radius
        replies = case.send(0, encode_item_action(ItemAction(actor_id, 9902, 255)))
        self.assertEqual((field.actor(actor_id).sight_radius,
                          field.actor(actor_id).action_points), (sight+2, points-11))
        self.assertEqual(effects.armor_bonus(field.combat, actor_id), 20)
        states = [decode_night_vision_state(packet) for packet in replies
                  if packet[:1] == b'\xf9']
        self.assertIn((actor_id,), states)
        self.assertEqual(field.combat.inventories[other_id], before_other)
        saved = OwnedPetStore(case.path).inventory(session.account, 1)
        records = decode_item_list(saved)[1]
        self.assertFalse(any(record.template_id == 20 for record in records))
        goggles = next(record for record in records if record.template_id == 5002)
        self.assertEqual(goggles.unknown_words, (297, 300, 300))


class MedicalOpticsAssetTests(unittest.TestCase):
    def test_metadata_changes_only_health_injection_points(self):
        raw = (b'<items><item id="9"><value key="actionPoints" val="10" /></item>'
               b'<item id="20" name="Health Injection">'
               b'<value key="power" val="100" /><value key="weight" val="100" />'
               b'<value key="actionPoints" val="10" /></item></items>')
        updated = patch_health_metadata(raw)
        self.assertIn(b'<item id="9"><value key="actionPoints" val="10" />', updated)
        self.assertTrue(updated.endswith(b'<value key="actionPoints" val="8" /></item></items>'))
        self.assertEqual(patch_health_metadata(updated), updated)
        self.assertEqual(len(replacements(raw, updated, xml=True)), 1)

    def test_localization_changes_only_two_existing_rows_without_native_patch(self):
        raw = (b'[language]\r\nc026=Heals %s hp\r\n'
               b'tio_item_effect_5002_0=Old sight\r\n'
               b'tio_item_effect_5002_1=Old cost\r\nother=Untouched\r\n')
        updated = patch_night_vision_language(raw, 'en', ROOT)
        self.assertIn(b'c026=Heals %s hp\r\n', updated)
        self.assertTrue(updated.endswith(b'other=Untouched\r\n'))
        self.assertIn(b'Armor: 20; sight in darkness: +2 cells', updated)
        self.assertEqual(patch_night_vision_language(updated, 'en', ROOT), updated)
        self.assertEqual(len(replacements(raw, updated, xml=False)), 2)

    def test_unknown_medical_metadata_or_missing_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            patch_health_metadata(b'<items><item id="20" /></items>')
        with self.assertRaises(ValueError):
            patch_night_vision_language(b'[language]\r\n', 'en', ROOT)


if __name__ == '__main__':
    unittest.main()
