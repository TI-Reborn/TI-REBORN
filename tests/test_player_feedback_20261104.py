"""Player-reported scene transitions against temporary multiplayer fixtures."""
from dataclasses import replace
import unittest

from tio.arena_service import ArenaService
from tio.locations import leave_town_packet, stop_packet


class MapReturnTests(unittest.TestCase):
    def test_map_transition_repeats_after_asynchronous_scene_teardown(self):
        from test_world_encounters import EncounterTests
        fixture = EncounterTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        arena = ArenaService()
        arena._completed.add(42)
        arena._return_maps[42] = (-87, -231)
        from contextlib import closing
        import sqlite3
        with closing(sqlite3.connect(fixture.path)) as db, db:
            fixture.locations._save(db, 'alice', None, -87, -231)
        arena.finish_results(42, b'\x2a\x01')
        packets = arena.city_roster_refresh(
            42, b'\x4a\xff\xff\xff\xff', fixture.path, 'alice')
        self.assertIn(leave_town_packet(), packets)
        self.assertIn(stop_packet(42, -87, -231), packets)


class MineLoadTests(unittest.TestCase):
    def test_reload_after_retired_participant_disconnects_keeps_mine_running(self):
        from test_shared_mine_arena import SharedMineArenaTests
        fixture = SharedMineArenaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        battle = fixture.enter((0, 1))
        retired = fixture.owners[1]
        fixture.hub.complete_mine_owner(battle, retired, 0)
        fixture.hub.players.pop(retired)
        fixture.send(0, b'\x36')
        self.assertNotIn('faulted', battle)
        self.assertIn(fixture.owners[0], fixture.hub.battles)

    def test_loaded_client_receives_visible_deposit_again(self):
        from test_shared_mine_arena import SharedMineArenaTests
        fixture = SharedMineArenaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        battle = fixture.enter((0,), load=False)
        owner = fixture.owners[0]
        field = battle['field']
        identity = field.actor_ids(owner)[0]
        position, deposit = next(iter(field.mining.deposits.items()))
        field._actors[identity] = replace(
            field.actor(identity), x=position[0], y=position[1])
        # The preliminary scene snapshot has already consumed the cache.
        self.assertIn(deposit.packet(), field.mining.packets(owner))
        packets = fixture.send(0, b'\x36')
        self.assertIn(deposit.packet(), packets)


class MineAvatarTests(unittest.TestCase):
    def test_first_and_late_squads_use_their_member_list_colors(self):
        from test_shared_mining_state import SharedMiningStateTests
        from tools.mining_scene import append_mining_owner
        fixture = SharedMiningStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        scene = fixture.prepare((0, 1))
        append_mining_owner(scene.field, fixture.path, fixture.accounts[2],
                            fixture.tickets[2], fixture.catalog, role=3,
                            templates=scene.visibility.templates)
        for index, owner in enumerate(fixture.owners[:3]):
            for identity in scene.field.actor_ids(owner):
                self.assertEqual(
                    scene.visibility.templates[identity].fields['0x8c5173'], index)

    def test_shared_and_late_squads_keep_distinct_saved_portraits(self):
        from contextlib import closing
        import sqlite3
        from test_shared_mining_state import SharedMiningStateTests
        from tio import avatars, battle_snapshot
        from tools.mining_scene import append_mining_owner
        fixture = SharedMiningStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with closing(sqlite3.connect(fixture.path)) as db, db:
            avatars.ensure(db)
            db.executemany('INSERT INTO pet_avatars VALUES (?,?,?)', (
                (account, fixture.fixture.identity, 10001 + index)
                for index, account in enumerate(fixture.accounts)))
        scene = fixture.prepare((0, 1))
        append_mining_owner(scene.field, fixture.path, fixture.accounts[2],
                            fixture.tickets[2], fixture.catalog, role=3,
                            templates=scene.visibility.templates)
        for field in (scene.field, battle_snapshot.loads(
                battle_snapshot.dumps(scene.field), rebase=False)[0]):
            for index, owner in enumerate(fixture.owners[:3]):
                identity, = field.actor_ids(owner)
                self.assertEqual(field.avatar_ids[identity], 10001 + index)


class ExchangeWireTests(unittest.TestCase):
    def test_native_left_to_right_bandages_are_deposits(self):
        from tio.protocol.battle_exchange import decode_exchange
        request = decode_exchange(bytes.fromhex(
            '6e0300004002000040010000008f2300000500000000000000'))
        self.assertEqual(request.actor_id, 0x40000003)
        self.assertEqual(request.target_id, 0x40000002)
        self.assertEqual(request.deposits, ((9103, 5),))
        self.assertEqual(request.withdrawals, ())


class LiveLootTests(unittest.TestCase):
    def test_last_action_points_allow_live_loot_until_close(self):
        from test_shared_mine_arena import SharedMineArenaTests
        from tio.protocol.battle_loot import LootTransfer, decode_container, encode_loot_transfer
        from tio.protocol.battle_position import BattlePositionRequest, encode_position_request

        for close in ('unchanged', 'transferred', 'timeout'):
            with self.subTest(close=close):
                fixture = SharedMineArenaTests()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                battle = fixture.enter((0, 1))
                field = battle['field']
                owner = fixture.owners[0]
                identity, = field.actor_ids(owner)
                position = next(iter(field.loot.boxes))
                with fixture.hub.journal.unit(battle):
                    field._actors[identity] = replace(
                        field.actor(identity), x=position[0]-1, y=position[1], action_points=4)
                opened = fixture.send(0, encode_position_request(BattlePositionRequest(identity, *position)))
                self.assertEqual(field.actor(identity).action_points, 0)
                contents = decode_container(next(p for p in opened if p[0] == 0x47))[3]
                self.assertNotIn(b'\x39', opened)
                fixture.hub.tick()
                turn = battle['arena']._turns[battle['room'].room_id]
                self.assertEqual(turn[0], owner)
                if close == 'transferred':
                    drill = contents[0]
                    moved = fixture.send(0, encode_loot_transfer(LootTransfer(
                        identity, *position, withdrawals=((drill.instance_id, drill.count),),
                        live=True, nonce=1)))
                    self.assertIn(0x47, [p[0] for p in moved])
                    self.assertNotIn(b'\x39', moved)
                if close == 'timeout':
                    fixture.case.now = turn[2] + 1
                    fixture.hub.tick()
                    self.assertIn(b'\x39', fixture.hub.queues[owner])
                else:
                    finished = fixture.send(0, encode_loot_transfer(LootTransfer(identity, *position)))
                    self.assertEqual(finished.count(b'\x39'), 1)
                    self.assertNotIn(identity, field.loot.sessions)

    def test_each_move_commits_and_refreshes_without_closing_the_container(self):
        from test_battle_loot import BattleLootTests
        from tio.protocol.battle_loot import (
            decode_container, decode_loot_transfer)
        fixture = BattleLootTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        supplies = fixture.supply((9, 5))
        identity = supplies[0].instance_id
        import struct
        points = fixture.field.actor(1).action_points
        def request(count, nonce):
            return decode_loot_transfer(b'\xf5' + struct.pack(
                '<IIBBIII', nonce, 1, 2, 2, 0, 1, identity) + struct.pack('<I', count))
        replies = fixture.loot.transfer(7, request(2, 1), 1)
        container = next(p for p in replies if p[:1] == b'\x47')
        self.assertEqual(decode_container(container)[3][0].count, 3)
        self.assertIn(1, fixture.loot.sessions)
        self.assertEqual(fixture.loot.transfer(7, request(2, 1), 1), replies)
        fixture.loot.transfer(7, request(3, 2), 1)
        self.assertEqual(fixture.loot.boxes[(2, 2)], ())
        self.assertEqual(fixture.saved(), fixture.initial)
        self.assertEqual(fixture.field.actor(1).action_points, points)
        with self.assertRaises(ValueError):
            fixture.loot.transfer(7, request(2, 1), 1)

    def test_shared_container_confirmation_stays_private_to_its_owner(self):
        from contextlib import closing
        import sqlite3
        from test_shared_mine_arena import SharedMineArenaTests
        from tio.protocol.battle_position import (
            BattlePositionRequest, encode_position_request)
        from tio.protocol.battle_loot import (
            LootTransfer, encode_loot_transfer, decode_container)
        from tio.protocol.item_list import decode_item_list, encode_item_list
        from test_combat import item
        fixture = SharedMineArenaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with closing(sqlite3.connect(fixture.path)) as db, db:
            account = fixture.case.sessions[0].account
            pet_id, = db.execute('SELECT pet_id FROM owned_pets WHERE account=?', (account,)).fetchone()
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (encode_item_list(pet_id, (item(150,301,equipped=True),)), account, pet_id))
        battle = fixture.enter((0, 1))
        field = battle['field']
        identity = field.actor_ids(fixture.owners[0])[0]
        equipped = next(item for item in decode_item_list(field.combat.inventories[identity])[1]
                        if item.equipped and item.client_slot == 16)
        position = next(iter(field.loot.boxes))
        with fixture.hub.journal.unit(battle):
            field._actors[identity] = replace(
                field.actor(identity), x=position[0]-1, y=position[1])
        replies = fixture.send(0, encode_position_request(
            BattlePositionRequest(identity, *position)))
        initial = decode_container(next(p for p in replies if p[:1] == b'\x47'))[3]
        for queue in fixture.hub.queues.values():queue.clear()
        wire = encode_loot_transfer(LootTransfer(
            identity, *position, deposits=((equipped.instance_id, equipped.count),),
            live=True, nonce=1))
        replies = fixture.send(0, wire)
        contents = decode_container(next(p for p in replies if p[:1] == b'\x47'))[3]
        deposited, = [item for item in contents if item not in initial]
        self.assertEqual(deposited.template_id, equipped.template_id)
        self.assertNotIn(equipped.instance_id,
                         [item.instance_id for item in decode_item_list(field.combat.inventories[identity])[1]])
        self.assertFalse(any(p[:1] in (b'\x30', b'\x47')
                             for p in fixture.hub.queues[fixture.owners[1]]))
        restored = fixture.restore().battles[fixture.owners[0]]['field']
        self.assertEqual(restored.loot.boxes[position], field.loot.boxes[position])
        self.assertEqual(restored.combat.inventories[identity],
                         field.combat.inventories[identity])
        self.assertEqual(restored.actor(identity).weapons,
                         (field.combat.catalog.weapons[300],))


if __name__ == '__main__':
    unittest.main()
