"""Prompt warehouse replies without skipping authority or external updates."""
from dataclasses import replace
import socket
import sqlite3
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server import warehouse_capacity
from server.economy_runtime import refresh_inventory
from server.multi import configure_keepalive
from tio.db_transaction import transaction
from tio.battle_recovery import RecoveryStore, save_wounds
from tio.owned_pets import OwnedPetStore
from tio.protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.warehouse import decode_warehouse_list
from tio.protocol.warehouse_capacity import OPT_IN
from tio.protocol.transport import InitialCipher, InitialFrameReader, encode_initial_frame
from tio.protocol.warehouse_transfer import WarehouseTransfer, encode_warehouse_transfer
from tio.warehouse import WarehouseStore
import test_ranked as fixture


class WarehouseLatencyTests(unittest.TestCase):
    def setUp(self):
        self.base = fixture.RankedServerTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.case = self.base.case
        self.path = self.base.path
        self.session = self.case.sessions[0]
        self.other = self.case.sessions[1]
        WarehouseStore(self.path)
        router = SimpleNamespace(lock=threading.RLock(), team_arena=self.base.hub,
                                 active_accounts={s.account: s for s in self.case.sessions})
        for session in self.case.sessions:
            session.router = router
            session.authenticated_account = session.account
            session.owned_pet_probe = True
        self.item = ItemRecord(300, 301, bytes(2), 1, 0, 0, (300, 300, 300),
                               bytes(4), None, bytes(3))
        with transaction(self.path) as database:
            database.execute('CREATE TABLE characters(account TEXT, slot INTEGER)')
            database.executemany('INSERT INTO characters VALUES (?,1)',
                                 ((s.account,) for s in self.case.sessions))
            database.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                             (encode_item_list(1, (self.item,)), self.session.account))

    def transfer(self, *, deposit=True):
        selected = ((300, 1),)
        packet = encode_warehouse_transfer(WarehouseTransfer(
            0, 1, selected if deposit else (), () if deposit else selected))
        return warehouse_capacity.transfer(self.session, packet, capacity=32)

    def test_personal_query_never_inspects_another_sessions_location(self):
        class UnrelatedLocation:
            def current(self, account):
                raise AssertionError('Unrelated session was queried')
        self.other.locations = UnrelatedLocation()
        replies = warehouse_capacity.query(self.session, b'\x69\0')
        self.assertEqual(decode_warehouse_list(replies[-1])[3], ())

    def test_own_retained_battle_still_blocks_transfers(self):
        self.base.hub.private[self.session.account] = object()
        with self.assertRaises(ValueError):
            self.transfer()
        self.assertEqual(WarehouseStore(self.path).items(self.session.account), ())

    def test_transfer_returns_new_lists_even_while_passive_poll_is_throttled(self):
        warehouse_capacity.opt_in(self.session, OPT_IN)
        warehouse_capacity.query(self.session, b'\x69\0')
        warehouse_capacity.state(self.session).next_poll = float('inf')
        replies = self.transfer()
        bag = next(packet for packet in replies if packet[:1] == b'\x30')
        stock = next(packet for packet in replies if packet[:1] == b'\x6a')
        self.assertEqual(decode_item_list(bag)[1], ())
        self.assertEqual([item.instance_id for item in decode_warehouse_list(stock)[3]], [300])

    def test_passive_marked_stock_does_not_replace_the_warehouse_with_an_empty_list(self):
        from tio.protocol.item_marks import metadata, project_warehouse
        from tio.protocol.warehouse import encode_private_warehouse_snapshot

        self.transfer()
        warehouse_capacity.opt_in(self.session, OPT_IN)
        warehouse_capacity.query(self.session, b'\x69\0')
        owner = self.session.account
        marked = replace(self.item, unknown_bytes_02=b'\0\0\1\0')
        with transaction(self.path) as db:
            db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=?',
                       (encode_item_list(0, (marked,)), owner))
        packet, = encode_private_warehouse_snapshot((marked,))
        projected = project_warehouse(packet, {300: ('Owner', 60)})
        self.assertEqual(metadata(projected), {300: ('Owner', 60)})

        cipher = InitialCipher('S2C')
        frame = warehouse_capacity.frames(self.session, projected, cipher)
        replies = InitialFrameReader(InitialCipher('S2C')).feed(frame)
        stock = next(p for p in replies if p[:1]==b'\x6a')
        self.assertEqual([item.instance_id for item in decode_warehouse_list(stock)[3]], [300])
        self.assertTrue(warehouse_capacity.state(self.session).enabled)

    def test_own_transfer_does_not_trigger_duplicate_full_inventory_push(self):
        refresh_inventory(self.session, force=True)
        self.transfer()
        self.assertEqual(refresh_inventory(self.session), ())
        self.transfer(deposit=False)
        self.assertEqual(refresh_inventory(self.session), ())

    def test_external_pet_change_is_not_hidden_by_transfer_acknowledgement(self):
        refresh_inventory(self.session, force=True)
        with transaction(self.path) as database:
            saved = database.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',
                                     (self.session.account,)).fetchone()[0]
            pet = decode_pet_info(saved, human_equipment=True)
            changed = replace(pet, fields={**pet.fields, '0x8c4ab1': 1})
            database.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                             (encode_pet_info(changed), self.session.account))
        self.transfer()
        replies = refresh_inventory(self.session)
        pet = next(packet for packet in replies if packet[:1] == b'\x66')
        self.assertEqual(decode_pet_info(pet, human_equipment=True).fields['0x8c4ab1'], 1)

    def test_explicit_external_invalidation_still_forces_a_refresh(self):
        refresh_inventory(self.session, force=True)
        self.session._economy_inventory_digest = None
        self.transfer()
        self.assertTrue(refresh_inventory(self.session))

    def test_transfer_reply_projections_share_one_sql_connection(self):
        from server.economy_runtime import project_packet
        from tio.weight import city_weight_update
        replies = self.transfer()

        def encode_reply(packet, cipher):
            suffix = (city_weight_update(self.path, self.session.account, packet)
                      if packet[:1] == b'\x30' else None)
            packet = project_packet(self.path, self.session.account, packet)
            frame = encode_initial_frame(packet, cipher)
            return frame + (encode_initial_frame(suffix, cipher) if suffix else b'')

        with patch('tio.db_transaction.sqlite3.connect', wraps=sqlite3.connect) as opened:
            frame = warehouse_capacity.encode_transfer_replies(
                self.path, replies, InitialCipher('S2C'), encode_reply)
        self.assertEqual(opened.call_count, 1)
        packets = InitialFrameReader(InitialCipher('S2C')).feed(frame)
        bag = next(packet for packet in packets if packet[:1] == b'\x30')
        stock = next(packet for packet in packets if packet[:1] == b'\x6a')
        self.assertEqual(decode_item_list(bag)[1], ())
        self.assertEqual([item.instance_id for item in decode_warehouse_list(stock)[3]], [300])

    def recovery_clock(self, hp):
        with transaction(self.path) as database:
            save_wounds(database, self.session.account, {1: hp})
        now = [1000.0]
        recovery = RecoveryStore(self.path, clock=lambda: now[0])
        return recovery, now

    def test_healthy_background_recovery_does_not_commit_unchanged_rows(self):
        pet = OwnedPetStore(self.path).list(self.session.account)[0][1]
        maximum = decode_pet_info(pet, human_equipment=True).fields['0x8c4a07']
        recovery, now = self.recovery_clock(maximum)
        recovery.refresh(self.session.account)
        with sqlite3.connect(self.path) as observer:
            self.addCleanup(observer.close)
            version = observer.execute('PRAGMA data_version').fetchone()
            now[0] += 1
            self.assertEqual(recovery.refresh(self.session.account), ())
            self.assertEqual(observer.execute('PRAGMA data_version').fetchone(), version)

    def test_recovery_remainder_survives_read_only_idle_refreshes(self):
        recovery, now = self.recovery_clock(10)
        recovery.refresh(self.session.account)
        with sqlite3.connect(self.path) as observer:
            self.addCleanup(observer.close)
            version = observer.execute('PRAGMA data_version').fetchone()
            now[0] += 9
            self.assertEqual(recovery.refresh(self.session.account), ())
            self.assertEqual(observer.execute('PRAGMA data_version').fetchone(), version)
        now[0] += 1
        self.assertTrue(recovery.refresh(self.session.account))
        pet = OwnedPetStore(self.path).list(self.session.account)[0][1]
        self.assertEqual(decode_pet_info(pet, human_equipment=True).fields['0x8c4ab1'], 11)

    def test_paused_background_recovery_keeps_wounds_and_resets_on_resume(self):
        recovery, now = self.recovery_clock(10)
        recovery.refresh(self.session.account, blocked=True)
        with sqlite3.connect(self.path) as observer:
            self.addCleanup(observer.close)
            version = observer.execute('PRAGMA data_version').fetchone()
            now[0] += 300
            self.assertEqual(recovery.refresh(self.session.account, blocked=True), ())
            self.assertEqual(observer.execute('PRAGMA data_version').fetchone(), version)
        self.assertEqual(recovery.refresh(self.session.account), ())
        now[0] += 10
        self.assertTrue(recovery.refresh(self.session.account))
        pet = OwnedPetStore(self.path).list(self.session.account)[0][1]
        self.assertEqual(decode_pet_info(pet, human_equipment=True).fields['0x8c4ab1'], 11)

    def test_external_inventory_change_is_not_hidden_by_transfer_acknowledgement(self):
        refresh_inventory(self.session, force=True)
        self.transfer()
        extra = replace(self.item, instance_id=400)
        with transaction(self.path) as database:
            database.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=1',
                             (encode_item_list(1, (extra,)), self.session.account))
        replies = refresh_inventory(self.session)
        bag = next(packet for packet in replies if packet[:1] == b'\x30')
        self.assertEqual([item.instance_id for item in decode_item_list(bag)[1]], [400])


class GameSocketLatencyTests(unittest.TestCase):
    def test_game_socket_has_nodelay_and_bounded_keepalive(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            with socket.create_connection(listener.getsockname()) as client:
                connection, _ = listener.accept()
                with connection:
                    configure_keepalive(connection)
                    self.assertEqual(connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY), 1)
                    self.assertEqual(connection.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 1)
