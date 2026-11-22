"""Native item requests, discovery privacy and authoritative mine removal."""
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import random
import sqlite3
import unittest
from unittest.mock import patch

import test_shared_team_arena as shared
import test_special_items as fixture
from test_combat import item
from tio import battle_snapshot
from tio.city_catalogs import CityCatalogs
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_mines import MineDeploy, MineDeployed, decode_mine_deployed, encode_mine_deploy
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.known_mines import KnownMine, decode_known_mines
from tio.protocol.mine_defuse import MineDefuse, encode_mine_defuse
from tio.protocol.shop_purchase import ShopPurchase
from tio.shop import ShopStore

ROOT = Path(__file__).resolve().parents[1]
FINDER = 5101
DEFUSER = 5102


def device(instance, template, durability=30):
    return replace(item(instance, template), unknown_words=(durability, 30, 30))


class MineDeviceTests(unittest.TestCase):
    def setUp(self):
        scene = fixture.SpecialItemsTests()
        scene.plant()
        self.field, self.combat, self.arena = scene.field, scene.combat, scene.arena
        self.field._actors[2] = replace(self.field.actor(2), x=4)
        self.arena._turns[1] = (8, {2}, 20)
        self.combat.register(2, encode_item_list(2, (device(101, FINDER), device(102, DEFUSER))), human=True)
        self.scan = encode_item_action(ItemAction(2, 101, 255))
        self.disarm = encode_mine_defuse(MineDefuse(2, 3, 2))

    def known(self, owner):
        return decode_known_mines(self.combat.hazard_packets(owner)[0])

    def carried(self):
        return tuple((i.instance_id, i.unknown_words[0]) for i in decode_item_list(self.combat.inventories[2])[1])

    def test_search_is_private_and_repeated_packet_spends_once(self):
        for _ in range(2):
            self.arena.equip(8, self.scan)
        self.assertEqual(self.known(8), (KnownMine(3, 2, 321, 0),))
        self.assertEqual(self.known(9), ())
        self.assertEqual((self.field.actor(2).action_points, self.carried()), (38, ((101, 29), (102, 30))))

    def test_only_new_discoveries_and_hostile_disarming_train_engineering(self):
        from test_weapon_proficiency import profile

        self.combat.register(2, self.combat.inventories[2], human=True, pet_packet=profile())
        rules = self.combat.proficiency_rules
        before = self.combat.proficiencies[2]
        self.field._actors[2] = replace(self.field.actor(2), x=7)
        self.arena.equip(8, self.scan)
        self.assertEqual(self.combat.proficiencies[2], before)
        self.field._actors[2] = replace(self.field.actor(2), x=4)
        self.arena.equip(8, self.scan)
        discovered = rules.train(before, True, 'Engineering', 2, True)
        self.assertEqual(self.combat.proficiencies[2], discovered)
        self.arena.equip(8, self.scan)
        self.assertEqual(self.combat.proficiencies[2], discovered)
        self.arena.mine_action(8, self.disarm)
        self.assertEqual(self.combat.proficiencies[2], rules.train(discovered, True, 'Engineering', 2, True))

    def test_search_respects_radius_and_walls(self):
        self.field._actors[2] = replace(self.field.actor(2), x=7)
        self.arena.equip(8, self.scan)
        self.assertEqual(self.known(8), ())
        self.field._actors[2] = replace(self.field.actor(2), x=5)
        self.field.blocked = frozenset({(4, 2)})
        self.arena.equip(8, self.scan)
        self.assertEqual(self.known(8), ())
        self.field._actors[2] = replace(self.field.actor(2), x=6)
        self.field.blocked = frozenset()
        self.arena.equip(8, self.scan)
        self.assertEqual(self.known(8), (KnownMine(3, 2, 321, 0),))

    def test_known_mine_can_be_disarmed_after_snapshot_reload(self):
        self.arena.equip(8, self.scan)
        self.combat.rng = random.Random(3)
        self.field, _ = battle_snapshot.loads(battle_snapshot.dumps(self.field))
        self.combat = self.field.combat
        self.arena._fields[1] = self.field
        self.arena.equip(8, self.scan)
        self.assertEqual(self.field.actor(2).action_points, 38)
        packets = self.arena.mine_action(8, self.disarm)
        self.assertIn(MineDeployed(2, 3, 2, 321, 3),
                      [decode_mine_deployed(p) for p in packets if p[:2] == b'\xc8\x3f'])
        self.assertEqual((self.known(7), self.known(8)), ((), ()))
        self.assertEqual((self.field.actor(2).action_points, self.carried()), (36, ((101, 29), (102, 29))))
        with self.assertRaises(ValueError):
            self.arena.mine_action(8, self.disarm)
        self.assertEqual(self.field.actor(2).action_points, 36)

    def test_invalid_defuse_does_not_spend_or_remove(self):
        with self.assertRaises(ValueError):
            self.arena.mine_action(8, self.disarm)
        self.arena.equip(8, self.scan)
        before = self.carried()
        for ap, x, turn in ((1, 4, 8), (38, 5, 8), (38, 4, 7)):
            self.field._actors[2] = replace(self.field.actor(2), action_points=ap, x=x)
            self.arena._turns[1] = (turn, {2}, 20)
            with self.assertRaises(ValueError):
                self.arena.mine_action(8, self.disarm)
            self.assertEqual((self.field.actor(2).action_points, self.carried(), len(self.combat.mines)), (ap, before, 1))

    def test_defuse_uses_lowest_working_probe_and_removes_its_last_charge(self):
        self.combat.register(2, encode_item_list(2, (device(101, FINDER), device(102, DEFUSER, 0),
                                                     device(104, DEFUSER), device(103, DEFUSER, 1))), human=True)
        self.arena.equip(8, self.scan)
        self.arena.mine_action(8, self.disarm)
        self.assertEqual(dict(self.carried()), {101: 29, 102: 0, 104: 30})

    def test_failed_inventory_write_does_not_change_discovery_or_disarm(self):
        with patch.object(self.combat, '_persist_batch', side_effect=sqlite3.OperationalError), self.assertRaises(sqlite3.OperationalError):
            self.arena.equip(8, self.scan)
        self.assertEqual((self.known(8), self.carried(), self.field.actor(2).action_points), ((), ((101, 30), (102, 30)), 40))
        self.arena.equip(8, self.scan)
        with patch.object(self.combat, '_persist_batch', side_effect=sqlite3.OperationalError), self.assertRaises(sqlite3.OperationalError):
            self.arena.mine_action(8, self.disarm)
        self.assertEqual((len(self.combat.mines), self.carried(), self.field.actor(2).action_points), (1, ((101, 29), (102, 30)), 38))


class SharedMineDeviceTests(unittest.TestCase):
    def test_shop_to_shared_removal_updates_both_clients(self):
        case = shared.SharedTeamTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        catalogs = CityCatalogs(ROOT / 'config/city_catalogs.json')
        shop = ShopStore(case.path, catalogs)
        for template in (FINDER, DEFUSER):
            offer = next((o for o in catalogs.items[0] if o.item_id == template), None)
            self.assertIsNotNone(offer)
            shop.purchase('bob', ShopPurchase(1, 0, offer.unknown_u32_01, 1))
        with closing(sqlite3.connect(case.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=?',
                       (encode_item_list(1, (item(100, 321),)), 'alice'))
        store = OwnedPetStore(case.path)
        initial = {name: store.list(name)[0][1] for name in ('alice', 'bob')}
        owners, battle = case.paired()
        field = battle['field']
        actor_a, actor_b = (field.actor_ids(owner)[0] for owner in owners)
        field.blocked = frozenset()
        for index, actor in enumerate(field._actors.values()):
            pos = {actor_a: (5, 5), actor_b: (7, 5)}.get(actor.actor_id, (20 + index, 20))
            field._actors[actor.actor_id] = replace(actor, x=pos[0], y=pos[1])
        for index in (0, 1):
            case.send(index, b'\x36')
        case.hub.tick()
        case.send(0, encode_mine_deploy(MineDeploy(actor_a, 100, 6, 5)))
        case.send(0, encode_end_turn())
        case.hub.tick()
        finder = next(i for i in decode_item_list(field.combat.inventories[actor_b])[1] if i.template_id == FINDER)
        case.send(1, encode_item_action(ItemAction(actor_b, finder.instance_id, 255)))
        replies = case.send(1, encode_mine_defuse(MineDefuse(actor_b, 6, 5)))
        for recipient, packets in ((actor_a, case.hub.queues[owners[0]]), (actor_b, replies)):
            removed = [decode_mine_deployed(p) for p in packets if p[:2] == b'\xc8\x3f']
            self.assertIn(MineDeployed(recipient, 6, 5, 321, 3), removed)
        self.assertFalse(field.combat.mines)
        saved = store.inventory('bob', 1)
        self.assertEqual({i.template_id: i.unknown_words[0] for i in decode_item_list(saved)[1]}, {FINDER: 29, DEFUSER: 29})
        for name in ('alice', 'bob'):
            before = field.combat.proficiency_rules.normalize(initial[name], True)
            after = store.list(name)[0][1]
            self.assertGreater(field.combat.proficiency_rules.value(after, True, 'Engineering'),
                               field.combat.proficiency_rules.value(before, True, 'Engineering'))
            self.assertEqual(field.combat.proficiency_rules.value(after, True, 'Throwing'),
                             field.combat.proficiency_rules.value(before, True, 'Throwing'))
