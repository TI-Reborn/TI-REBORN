"""Shared mine item creation must preserve account-wide item ownership."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest

import test_shared_mine_arena as mine_fixture
import test_battle_exchange as exchange_fixture
from tio.item_stacking import compact_saved_items
from tio.protocol.battle_loot import LootTransfer
from tio.protocol.battle_position import BattlePositionRequest
from tio.protocol.battle_exchange import BattleExchange
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.warehouse import WarehouseStore


def champagne(identity: int) -> ItemRecord:
    return ItemRecord(identity, 33, bytes(2), 1, 0, 0, (1, 1, 1),
                      bytes(4), None, bytes(3))


class MineItemIdentityTests(unittest.TestCase):
    def setUp(self):
        self.case = mine_fixture.SharedMineArenaTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def warehouse(self, account: str, identity: int) -> None:
        WarehouseStore(self.case.path)
        with closing(sqlite3.connect(self.case.path)) as db, db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',
                       (account, identity, encode_item_list(0, (champagne(identity),))))

    def test_drop_and_pickup_cannot_duplicate_a_warehouse_champagne_id(self):
        # Before the fix a fresh shared mine starts at 0x7200000B regardless
        # of its founder's saved stock. Dropping a real bottle assigns this
        # occupied ID; picking it back up then blocks every subsequent login.
        reserved = 0x7200000B
        self.warehouse('alice', reserved)
        with closing(sqlite3.connect(self.case.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                       (encode_item_list(1, (champagne(100),)), 'alice'))
        battle = self.case.enter((0,))
        field = battle['field']
        owner = self.case.owners[0]
        actor = field.actor(field.actor_ids(owner)[0])
        position = actor.x, actor.y
        loot = field.loot
        with self.case.hub.journal.unit(battle):
            loot.transfer(owner, LootTransfer(actor.actor_id, *position, ((100, 1),)), 1)
            dropped = loot.boxes[position][0]
            loot.open(owner, BattlePositionRequest(actor.actor_id, *position), 1)
            loot.transfer(owner, LootTransfer(actor.actor_id, *position,
                                             withdrawals=((dropped.instance_id, 1),)), 1)
        packet = field.combat.inventories[actor.actor_id]
        bottles = decode_item_list(packet)[1]
        self.assertEqual(len(bottles), 1)
        self.assertEqual(replace(bottles[0], instance_id=100), champagne(100))
        self.assertNotEqual(bottles[0].instance_id, reserved)
        self.assertEqual(WarehouseStore(self.case.path).items('alice'), (champagne(reserved),))
        compact_saved_items(self.case.path, 'alice')

    def test_initial_drill_reserves_founder_saved_ids_and_high_water_mark(self):
        self.warehouse('alice', 0x7200000A)
        with closing(sqlite3.connect(self.case.path)) as db, db:
            db.execute('INSERT INTO item_sequences VALUES (?,?)', ('alice', 0x73000000))
        battle = self.case.enter((0,), load=False)
        drill = next(iter(battle['field'].loot.boxes.values()))[0]
        self.assertGreaterEqual(drill.instance_id, 0x73000000)

    def test_later_join_reserves_warehouse_and_retired_ids(self):
        battle = self.case.enter((0,), load=False)
        self.warehouse('bob', 0x74000000)
        with closing(sqlite3.connect(self.case.path)) as db, db:
            db.execute('INSERT INTO item_sequences VALUES (?,?)', ('bob', 0x75000000))
        self.case.send(1, b'\xb0\x14\x02')
        self.assertIn(self.case.owners[1], battle['humans'])
        self.assertGreaterEqual(battle['field'].loot.next_id, 0x75000000)

    def test_join_with_existing_drill_identity_is_rejected_without_save_changes(self):
        battle = self.case.enter((0,), load=False)
        drill = next(iter(battle['field'].loot.boxes.values()))[0]
        self.warehouse('bob', drill.instance_id)
        before = self.case.economic_rows()
        replies = self.case.send(1, b'\xb0\x14\x02')
        self.assertTrue(any(p[:1] == b'\xf0' for p in replies))
        self.assertNotIn(self.case.owners[1], battle['humans'])
        self.assertEqual(self.case.economic_rows(), before)


class BattleAllocationRefreshTests(unittest.TestCase):
    def test_old_match_counter_cannot_reuse_a_saved_id_during_stack_split(self):
        case = exchange_fixture.ExchangeTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        target = encode_item_list(2, (case.contents(2)[202],))
        case.c.inventories[2] = target
        with closing(sqlite3.connect(case.path)) as db, db:
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE pet_id=2', (target,))
        case.req = BattleExchange(1, 2, deposits=((101, 10),))
        reserved = case.loot.next_id
        WarehouseStore(case.path)
        with closing(sqlite3.connect(case.path)) as db, db:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?)',
                       ('alice', reserved, encode_item_list(0, (champagne(reserved),))))
        # Model an old recovered checkpoint or a new participant/award whose
        # stock was unknown when this match's counter was constructed.
        case.open()
        case.transfer()
        seen = set()
        for packet in case.saved().values():
            for item in decode_item_list(packet)[1]:
                self.assertNotEqual(item.instance_id, reserved)
                self.assertNotIn(item.instance_id, seen)
                seen.add(item.instance_id)
        self.assertEqual(WarehouseStore(case.path).items('alice'), (champagne(reserved),))


if __name__ == '__main__':
    unittest.main()
