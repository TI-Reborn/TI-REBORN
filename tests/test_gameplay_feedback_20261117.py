"""Requested balance and shared mine exit regressions."""
from dataclasses import replace
from contextlib import closing
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
import unittest
from xml.etree import ElementTree

from server.implant_service import catalogue_xml
from tio.crystal_market import POLICY, SCALE
from tio.weapons import WeaponCatalog
from tio.protocol.item_list import decode_item_list, encode_item_list
import test_shared_mine_arena as mines

ROOT = Path(__file__).resolve().parents[1]


class BalanceTests(unittest.TestCase):
    def test_crystal_quote_is_fifty_credits(self):
        self.assertEqual(POLICY['market_rate_units'], 50 * SCALE)

    def test_p90_costs_four_action_points(self):
        catalog = WeaponCatalog()
        self.assertEqual(catalog.weapons[306].attack_ap, 4)
        self.assertEqual(catalog.sources[306]['actionPoints'], '4')

    def test_p90_tooltip_matches_combat_cost_in_both_client_interfaces(self):
        cost = WeaponCatalog().weapons[306].attack_ap
        for interface in ('new', 'original'):
            with self.subTest(interface=interface):
                session = SimpleNamespace(interface=interface)
                items = ElementTree.fromstring(catalogue_xml(session, ()))
                ap = items.find("item[@id='306']/value[@key='actionPoints']")
                self.assertEqual(ap.get('val'), str(cost))

    def test_approved_mine_armor_keeps_the_lowest_mine_unchanged(self):
        self.assertEqual([row[4] for row in POLICY['bands']], [128, 180, 200, 240])

    def test_victory_threshold_by_mine_level(self):
        from tio.mining import minimum_victory_crystals
        self.assertEqual([minimum_victory_crystals(level) for level in (4, 7, 11, 16)],
                         [100, 100, 200, 200])

    def test_every_shop_section_has_unlimited_stock(self):
        policy = json.loads((ROOT / 'config/shop_completion.json').read_text())
        self.assertTrue(policy['stock'])
        self.assertTrue(all(rule == {'mode': 'infinite'} for rule in policy['stock'].values()))


class MineExitTests(unittest.TestCase):
    def setUp(self):
        self.fixture = mines.SharedMineArenaTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def carry_inside(self, battle, index, amount):
        f = self.fixture
        identity = f.carry_at_exit(battle, index, amount)
        field = battle['field']
        x, y = next(iter(field.mining.deposits))
        with f.hub.journal.unit(battle):
            field._actors[identity] = replace(field.actor(identity), x=x, y=y)
        return identity

    def test_miner_can_leave_from_inside_with_empty_drill(self):
        f = self.fixture
        battle = f.enter((0,))
        self.carry_inside(battle, 0, 0)
        self.assertTrue(f.hub.mine_can_quit(battle, f.owners[0]))
        f.send(0, b'\x2a\x01')
        self.assertNotIn(f.owners[0], f.hub.battles)

    def test_less_than_one_hundred_crystals_is_a_defeat(self):
        f = self.fixture
        battle = f.enter((0,))
        self.carry_inside(battle, 0, 99)
        replies = f.send(0, b'\x2a\x01')
        result = next(p for p in replies if p[0] == 0x4c)
        self.assertEqual(result[3], 0)

    def test_one_hundred_crystals_is_a_victory(self):
        f = self.fixture
        battle = f.enter((0,))
        self.carry_inside(battle, 0, 100)
        replies = f.send(0, b'\x2a\x01')
        result = next(p for p in replies if p[0] == 0x4c)
        self.assertEqual(result[3], 1)

    def high_level_exit(self, level, location, amount):
        from tio.locations import center
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        f = self.fixture
        session = f.case.sessions[0]
        identity, raw, _ = OwnedPetStore(f.path).list(session.account)[0]
        pet = decode_pet_info(raw, human_equipment=True)
        pet = replace(pet, fields={**pet.fields, '0x8c4aef': level})
        with closing(sqlite3.connect(f.path)) as db, db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                       (encode_pet_info(pet), session.account, identity))
            session.locations._save(db, session.account, location, *center(location))
        battle = f.enter((0,))
        self.carry_inside(battle, 0, amount)
        return next(p for p in f.send(0, b'\x2a\x01') if p[0] == 0x4c)[3]

    def test_high_mine_199_is_defeat(self):
        self.assertEqual(self.high_level_exit(11, 15, 199), 0)

    def test_high_mine_200_is_victory(self):
        self.assertEqual(self.high_level_exit(11, 15, 200), 1)

    def test_highest_mine_199_is_defeat(self):
        self.assertEqual(self.high_level_exit(16, 16, 199), 0)

    def test_highest_mine_200_is_victory(self):
        self.assertEqual(self.high_level_exit(16, 16, 200), 1)

    def test_raw_quit_without_drill_cannot_bypass_exit(self):
        f = self.fixture
        battle = f.enter((0,))
        identity = battle['field'].actor_ids(f.owners[0])[0]
        x, y = next(iter(battle['field'].mining.deposits))
        with f.hub.journal.unit(battle):
            battle['field']._actors[identity] = replace(battle['field'].actor(identity), x=x, y=y)
        f.send(0, b'\x2a\x01')
        self.assertIs(f.hub.battles.get(f.owners[0]), battle)

    def test_raider_locks_both_exits_for_five_rounds(self):
        f = self.fixture
        battle = f.enter((0, 1))
        mine = battle['field'].mining
        self.assertEqual([mine.exit_blocked_until_by_owner[o] for o in f.owners[:2]], [5, 5])

    def test_after_five_rounds_enemy_allows_menu_only_at_exit(self):
        f = self.fixture
        battle = f.enter((0, 1))
        self.carry_inside(battle, 0, 100)
        with f.hub.journal.unit(battle):
            battle['field'].mining.advance(1)
            battle['field'].mining.advance(2)
            battle['field'].mining.advance(3)
            battle['field'].mining.advance(4)
            battle['field'].mining.advance(5)
        self.assertFalse(f.hub.mine_can_quit(battle, f.owners[0]))
        f.send(0, b'\x2a\x01')
        self.assertIs(f.hub.battles.get(f.owners[0]), battle)
        f.move_to_exit(battle, 0)
        with f.hub.journal.unit(battle):
            f.hub.mine_after_action(battle, f.owners[0])
        self.assertFalse(battle['finished'])
        self.assertTrue(f.hub.mine_can_quit(battle, f.owners[0]))
        f.send(0, b'\x2a\x01')
        self.assertTrue(battle['finished'])

    def test_dead_raider_allows_menu_inside_after_the_full_lock(self):
        f = self.fixture
        battle = f.enter((0, 1))
        self.carry_inside(battle, 0, 100)
        field = battle['field']
        with f.hub.journal.unit(battle):
            for identity in field.living_actor_ids(f.owners[1]):
                field._actors[identity] = replace(field.actor(identity), health=0)
            for generation in range(1, 5):
                field.mining.advance(generation)
        self.assertFalse(field.mining.at_exit(f.owners[0]))
        self.assertFalse(f.hub.mine_can_quit(battle, f.owners[0]))
        with f.hub.journal.unit(battle):
            field.mining.advance(5)
            f.hub.mine_after_action(battle, f.owners[0])
        self.assertFalse(battle['finished'])
        self.assertTrue(f.hub.mine_can_quit(battle, f.owners[0]))
        self.assertIn(b'\xb2\x16\x01', f.hub.queues[f.owners[0]])
        replies = f.send(0, b'\x2a\x01')
        self.assertEqual(next(p for p in replies if p[0] == 0x4c)[3], 1)


class UnlimitedStockTests(unittest.TestCase):
    def test_old_exhausted_stock_does_not_limit_either_account(self):
        from tio.db_transaction import transaction
        from tio.shop_completion import ShopCompletion
        from test_shop_completion import ShopCompletionTests
        f = ShopCompletionTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        completion = ShopCompletion(f.path, f.catalogs)
        offer = f.offer(30)
        with transaction(f.path) as db:
            db.execute('INSERT INTO shop_global_stock VALUES (?,?,?,?,?,?,?)',
                       (completion.policy['version'], 3, 0, offer.unknown_u32_01, 0, 0, None))
            for account in ('alice', 'bob'):
                self.assertIn(offer, completion.offers(db, account, 0))
                completion.consume(db, account, offer, 1000)
                self.assertIsNone(completion.stock(db, 3, 0, offer.unknown_u32_01, offer.item_id))
            self.assertEqual(db.execute('SELECT quantity FROM shop_global_stock').fetchall(), [(0,)])


if __name__ == '__main__':
    unittest.main()
