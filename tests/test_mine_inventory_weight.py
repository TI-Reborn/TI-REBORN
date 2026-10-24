"""Shared mine inventory packets must refresh the owner's carried-weight UI."""
from dataclasses import replace
import struct
import unittest

import test_shared_mine_arena as fixtures
import test_multi_account as tcp_fixtures
from pathlib import Path
import json
from tio.db_transaction import transaction
from tio.protocol.battle_loot import LootTransfer, encode_loot_transfer
from tio.protocol.battle_position import BattlePositionRequest, encode_position_request
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.item_list import decode_item_list, encode_item_list
from tio.protocol.item_list import ItemRecord
from tio.protocol.arena import ArenaCreateRequest, encode_create_request
from tio.protocol.battle_soldier import decode_battle_soldier
from tio.owned_pets import OwnedPetStore
from tio.weight import encode_weight, inventory_weight


class MineInventoryWeightTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.SharedMineArenaTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        with transaction(self.case.path) as db:
            for account, identity in db.execute('SELECT account,pet_id FROM owned_pets').fetchall():
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                           (encode_item_list(identity, ()), account, identity))
        self.battle = self.case.enter((0, 1))
        self.field = self.battle['field']
        self.owner = self.case.owners[0]
        self.actor_id = self.field.actor_ids(self.owner)[0]
        self.combat = self.field.combat

    def assert_weight(self, rows, expected):
        inventory_index = next(n for n, p in enumerate(rows)
                               if p[:1] == b'\x30' and int.from_bytes(p[1:5], 'little') == self.actor_id)
        weights = [(n, p) for n, p in enumerate(rows)
                   if p[:1] == b'\x4e' and len(p) == 26
                   and int.from_bytes(p[1:5], 'little') == self.actor_id
                   and struct.unpack_from('<II', p, 5) == (2, 7)]
        self.assertTrue(weights, 'Inventory was sent without carried-weight attributes')
        index, packet = weights[-1]
        self.assertGreater(index, inventory_index)
        self.assertEqual(packet, encode_weight(self.actor_id, expected,
                                              self.combat.weight_capacity(self.actor_id)))
        self.assertEqual(inventory_weight(self.combat.inventories[self.actor_id]), expected)

    def take_crate_drill(self):
        x, y = next(iter(self.field.loot.boxes))
        drill = self.field.loot.boxes[x, y][0]
        with self.case.hub.journal.unit(self.battle):
            self.case.park_mutants(self.battle)
            self.field._actors[self.actor_id] = replace(self.field.actor(self.actor_id), x=x-1, y=y)
        self.case.send(0, encode_position_request(BattlePositionRequest(self.actor_id, x, y)))
        rows = self.case.send(0, encode_loot_transfer(
            LootTransfer(self.actor_id, x, y, (), ((drill.instance_id, 0),))))
        return drill, rows

    def test_empty_drill_updates_weight_immediately_and_remains_battle_local(self):
        _, rows = self.take_crate_drill()
        self.assert_weight(rows, 100)
        with transaction(self.case.path) as db:
            saved = db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',
                               ('alice',)).fetchone()[0]
        self.assertEqual(decode_item_list(saved)[1], ())

    def test_install_and_pickup_loaded_drill_refresh_weight_in_both_directions(self):
        drill, _ = self.take_crate_drill()
        deposit = next(iter(self.field.mining.deposits.values()))
        with self.case.hub.journal.unit(self.battle):
            self.field._actors[self.actor_id] = replace(self.field.actor(self.actor_id),
                                                       x=deposit.position[0], y=deposit.position[1])
        rows = self.case.send(0, encode_item_action(ItemAction(self.actor_id, drill.instance_id, 255)))
        self.assert_weight(rows, 0)
        with self.case.hub.journal.unit(self.battle):
            deposit.extracted = 500
        rows = self.case.send(0, b'\xb0\x15'+struct.pack('<IBBI', self.actor_id, *deposit.position, 500))
        self.assert_weight(rows, 600)

    def test_inventory_query_repairs_stale_display_without_changing_state(self):
        self.take_crate_drill()
        before = self.case.economic_rows()
        actor = self.field.actor(self.actor_id)
        inventory = self.combat.inventories[self.actor_id]
        rows = self.case.send(0, b'\x2f'+struct.pack('<HI', 1, self.actor_id))
        self.assert_weight(rows, 100)
        self.assertEqual(self.case.economic_rows(), before)
        self.assertEqual(self.field.actor(self.actor_id), actor)
        self.assertEqual(self.combat.inventories[self.actor_id], inventory)

    def test_drop_and_retake_drill_refresh_weight(self):
        drill, _ = self.take_crate_drill()
        actor = self.field.actor(self.actor_id)
        rows = self.case.send(0, encode_loot_transfer(
            LootTransfer(self.actor_id, actor.x, actor.y, ((drill.instance_id, 0),), ())))
        self.assert_weight(rows, 0)
        self.case.send(0, encode_position_request(BattlePositionRequest(self.actor_id, actor.x, actor.y)))
        rows = self.case.send(0, encode_loot_transfer(
            LootTransfer(self.actor_id, actor.x, actor.y, (), ((drill.instance_id, 0),))))
        self.assert_weight(rows, 100)

    def test_reconnect_sends_live_drill_weight_instead_of_saved_city_weight(self):
        self.take_crate_drill()
        session = self.case.case.sessions[0]
        self.assertTrue(self.case.hub.disconnect(session))
        self.assertTrue(self.case.hub.resume(session))
        self.assert_weight(tuple(self.case.hub.queues[self.owner]), 100)

    def test_another_account_does_not_receive_private_inventory_or_weight(self):
        other = self.case.owners[1]
        self.case.hub.queues[other].clear()
        self.take_crate_drill()
        rows = tuple(self.case.hub.queues[other])
        self.assertFalse(any(p[:1] == b'\x30' for p in rows))
        self.assertFalse(any(p[:1] == b'\x4e' and len(p) == 26
                             and int.from_bytes(p[1:5], 'little') == self.actor_id for p in rows))

    def test_existing_weight_update_is_not_duplicated(self):
        self.take_crate_drill()
        self.case.hub.queues[self.owner].clear()
        weight = self.combat.weight_packet(self.actor_id)
        self.case.hub.put(self.owner, self.combat.inventory_packet(self.actor_id), weight)
        self.assertEqual(tuple(self.case.hub.queues[self.owner]).count(weight), 1)

    def test_inventory_preview_cannot_change_authoritative_weight(self):
        self.take_crate_drill()
        self.case.hub.queues[self.owner].clear()
        self.case.hub.put(self.owner, encode_item_list(self.actor_id, ()))
        self.assert_weight(tuple(self.case.hub.queues[self.owner]), 100)


class SharedWeightTcpTests(unittest.TestCase):
    def test_two_real_tcp_accounts_receive_their_live_inventory_weight(self):
        case = tcp_fixtures.MultiAccountTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        root = Path(__file__).resolve().parents[1]
        pet = bytes.fromhex(json.loads((root/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
        drill = ItemRecord(500, 52, bytes(2), 500, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
        for name, items in (('alice', (drill,)), ('bob', ())):
            OwnedPetStore(case.config.database).ensure(name, pet, encode_item_list(1, items), human=True)
        case.start()
        peers = []
        for name in ('alice', 'bob'):
            peer = case.handoff(case.begin(name))
            case.enter(peer, name.title())
            peers.append(peer)
        request = encode_create_request(ArenaCreateRequest(1, 0, 4, 2, 40, 1, 1, 0, 0))
        for peer in peers:
            peer.send(request)
            peer.until(b'\x25')
            peer.send(b'\x2e')
        actors = []
        for peer in peers:
            own = []
            for _ in range(256):
                packet = peer.receive()
                if packet == b'\x41':
                    break
                if packet[:1] == b'\x3b':
                    record = decode_battle_soldier(packet, human_equipment=True)
                    if record.owner_id == 1:
                        own.append(record)
            else:
                self.fail('Missing shared scene completion')
            self.assertEqual(len(own), 1)
            actors.append(own[0])
            peer.send(b'\x36')
        for index, peer in enumerate(peers):
            identity = actors[index].soldier_id
            rows = case.exchange_inventory_requests(peer, [b'\x2f'+struct.pack('<HI', 1, identity)])
            weights = [p for p in rows if p[:1] == b'\x4e' and len(p) == 26
                       and int.from_bytes(p[1:5], 'little') == identity]
            self.assertTrue(weights)
            self.assertEqual(struct.unpack_from('<I', weights[-1], 21)[0], 600 if index == 0 else 0)
            inventories = [decode_item_list(p) for p in rows if p[:1] == b'\x30']
            self.assertTrue(all(owner == identity for owner, _, _ in inventories))
        # Both network actors have distinct shared identities despite local ID1.
        self.assertNotEqual(actors[0].soldier_id, actors[1].soldier_id)


if __name__ == '__main__':
    unittest.main()
