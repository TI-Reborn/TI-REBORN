"""Queue/membership authority over ordinary disposable character saves.

The harness isolates the new mixin from root-owned combat integration. Levels
are awarded through the normal XP settlement store. Only checkpoint ownership
is an explicit local operator fixture, not a player-facing admission shortcut.
"""
from collections import deque
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest

from server.mine_requests import MineRequests, revalidate_owned
from tio.characters import CharacterStore
from tio.clans import ClansStore
from tio.db_transaction import transaction
from tio.level_progression import FLOORS, settle_experience
from tio.locations import LocationStore, center
from tio.matchmaking import SurvivalQueue
from tio.mine_claims import MineClaimsStore
from tio.onboarding import prepare
from tio.owned_pets import OwnedPetStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.mine_requests import QueueMember, queue_change, decode_queue_change, decode_request
from tio.protocol.pet_info import decode_pet_info, encode_pet_info


class Hub(MineRequests):
    def __init__(self):
        self.lock = threading.RLock(); self.players = {}; self.battles = {}; self.offline = {}
        self.queues = {}; self.other_busy = set(); self.fail_join = False; self.fail_commit = False
        self.clock = lambda: 100.
        self.init_mine_requests()

    def put(self, owner, *packets):
        if owner in self.queues and owner not in self.offline:
            self.queues[owner].extend(packets)

    def busy(self, session):
        owner = next(o for o, s in self.players.items() if s is session)
        return owner in self.other_busy or owner in self.battles or self.mine_waiting(owner)

    def mine_instances(self, town):
        return tuple(b for b in {id(b): b for b in self.battles.values()}.values()
                     if b['city_id'] == town and not b['finished'])

    def mine_seat(self, battle, role):
        roles = battle['field'].mining.roles
        count = sum(roles[o] == role for o in battle['mine_active'])
        return not battle['finished'] and count < (2 if role == 2 else 1)

    def join_mine(self, battle, owner, ticket, role):
        if self.fail_join:
            raise sqlite3.OperationalError('isolated storage failure')
        battle['field'].mining.roles[owner] = role; battle['mine_active'].add(owner)
        battle['reward_roster'][owner] = (self.players[owner].account, ticket.levels, role == 2)
        self.battles[owner] = battle

    @contextmanager
    def mine_unit(self, battle):
        before = deepcopy(battle); maps = dict(self.battles)
        try:
            with transaction(next(iter(battle['field'].combat.persistence.values()))[0]):
                yield
                if self.fail_commit:
                    raise sqlite3.OperationalError('isolated commit failure')
        except BaseException:
            battle.clear(); battle.update(before); self.battles = maps
            raise


class MineRequestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'state.db'; self.hub = Hub(); self.characters = CharacterStore(self.path)
        self.owners = []
        for name in ('Alice', 'Bobby', 'Clara', 'David', 'Emily', 'Frank'):
            self.add_player(name)
        clans = ClansStore(self.path); self.clans = clans
        self.clan = clans.create('Alice', b'Mine Guards')
        for name in ('Clara', 'David'):
            clans.invite('Alice', name.encode()); clans.accept(name, 1)
        self.claim = MineClaimsStore(self.path).admin_set_claim(13, self.clan, tax_percent=10,
            expected_revision=0, actor='test:operator', reason='isolated queue fixture')
        self.battle = dict(kind='mine', city_id=13, finished=False, mine_active={self.owners[0]},
            reward_roster={self.owners[0]: ('Alice', (4,), 0)}, mine_claim=self.claim,
            field=SimpleNamespace(mining=SimpleNamespace(roles={self.owners[0]: 1}),
                combat=SimpleNamespace(persistence={1: (self.path, 'Alice')})))
        self.hub.battles[self.owners[0]] = self.battle

    def add_player(self, login, *, slot=1, name=None, path=None):
        path = path or self.path; characters = CharacterStore(path)
        name = name or login
        characters.create(login, CharacterCreateRequest(name.encode(), 0, (1, 0, 0, 0)))
        account = characters.owner(login, slot); prepare(path, account)
        with transaction(path) as db:
            for pet_id, _, _ in OwnedPetStore(path).list(account):
                settle_experience(db, account, 'earned-level-four-' + name, {pet_id: FLOORS[3]})
        locations = LocationStore(path)
        with transaction(path) as db:
            locations._save(db, account, 13, *center(13))
        owner = 0x10000001 + len(self.hub.players)
        session = SimpleNamespace(database=path, account=account, probe_character_id=1,
            probe_character_name=name.encode(), locations=locations)
        self.hub.players[owner] = session; self.hub.queues[owner] = deque(); self.owners.append(owner)
        return owner

    def ticket(self, owner):
        s = self.hub.players[owner]
        return SurvivalQueue(group_wait=0).join(owner, OwnedPetStore(s.database).list(s.account))

    def enqueue(self, index, role):
        owner = self.owners[index]
        return self.hub.enqueue_mine_request(owner, 13, self.ticket(owner), role)

    def last_rows(self, owner):
        packet = next(p for p in reversed(self.hub.queues[owner]) if p.startswith(b'\xb0\x18'))
        return decode_queue_change(packet)

    def test_native_abi_and_strict_c2s_validation(self):
        rows = (QueueMember(1, 3, 0, True), QueueMember(0x10000003, 2, 5), QueueMember(7, 3, -1))
        raw = queue_change(rows)
        self.assertEqual(raw, b'\xb0\x18' + struct.pack('<I', 3) + b''.join(
            struct.pack('<IIiB', r.player_id, r.role, r.order, r.ready) for r in rows))
        self.assertEqual(decode_queue_change(raw), rows)
        for invalid in [raw[:-1], raw + b'\0', b'\xb0\x18' + struct.pack('<I', 513)]:
            with self.assertRaises(ValueError): decode_queue_change(invalid)
        for rows in [(QueueMember(1, 3, -2),), (QueueMember(0, 3, 0),),
                     (QueueMember(1, 4, 0),), (QueueMember(1, 3, 0), QueueMember(1, 2, 0))]:
            with self.assertRaises(ValueError): queue_change(rows)
        for raw, result in [(b'\xb0\x14\3', ('join', 3)), (b'\xb0\x19', ('cancel', None)),
                            (b'\xb0\x2c', ('list', None)), (b'\xb0\x1c', ('list', None))]:
            self.assertEqual(decode_request(raw), result)
        for raw in (b'\xb0\x28\3', b'\xb0\x14\0', b'\xb0\x19\0', b'\xb0'):
            with self.assertRaises(ValueError): decode_request(raw)

    def test_defenders_fifo_wait_for_help_then_only_one_admitted(self):
        first = self.enqueue(2, 3); second = self.enqueue(3, 3)
        self.assertLess(first.sequence, second.sequence)
        self.assertEqual(self.hub.try_mine_requests(self.battle), ())
        self.battle['mine_help'] = {3: True}
        self.assertEqual(self.hub.try_mine_requests(self.battle), (first.owner,))
        self.assertFalse(self.battle['mine_help'][3]); self.assertTrue(self.hub.mine_waiting(second.owner))
        self.assertEqual(self.hub.try_mine_requests(self.battle), ())

    def test_first_raider_immediate_second_requires_first_raider_help(self):
        first = self.enqueue(1, 2); second = self.enqueue(4, 2)
        self.assertEqual(self.hub.try_mine_requests(self.battle), (first.owner,))
        self.assertTrue(self.hub.mine_waiting(second.owner))
        self.battle['mine_help'] = {2: True}
        self.assertEqual(self.hub.try_mine_requests(self.battle), (second.owner,))
        self.assertFalse(self.battle['mine_help'][2])

    def test_private_own_ids_role_positions_and_waiting_counts(self):
        first = self.enqueue(1, 2); second = self.enqueue(2, 3); third = self.enqueue(4, 2)
        rows = self.last_rows(second.owner)
        self.assertEqual(rows, (QueueMember(first.owner, 2, 0), QueueMember(1, 3, 0), QueueMember(third.owner, 2, 1)))
        second_rows = self.last_rows(first.owner)
        self.assertEqual(second_rows[0].player_id, 1); self.assertEqual(second_rows[1].player_id, second.owner)
        state = self.hub.queue_packets(second.owner, 13)[1]
        self.assertEqual(struct.unpack('<BBBB5h', state)[4:], (1, 0, 0, 1, 2))

    def test_cancel_disconnect_and_restart_drop_only_requests(self):
        request = self.enqueue(1, 2); self.enqueue(2, 3)
        with closing(sqlite3.connect(self.path)) as db:
            before = tuple(db.execute('SELECT * FROM wallets ORDER BY account'))
        self.assertTrue(self.hub.cancel_mine_request(request.owner)); self.assertFalse(self.hub.cancel_mine_request(request.owner))
        self.assertEqual(self.last_rows(request.owner), (QueueMember(1, 2, -1),))
        self.assertIn(b'\xb0\x1b\1\0\0\0', self.hub.queues[request.owner])
        other = self.owners[2]; self.hub.offline[other] = 100.
        self.assertTrue(self.hub.cancel_mine_request(other))
        self.assertFalse(self.hub.mine_waiting(other))
        self.hub.init_mine_requests(); self.assertFalse(self.hub.mine_requests)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(tuple(db.execute('SELECT * FROM wallets ORDER BY account')), before)

    def test_duplicate_request_preserves_fifo_but_other_role_rejected(self):
        first = self.enqueue(1, 2); self.enqueue(4, 2)
        self.assertIs(self.enqueue(1, 2), first)
        with self.assertRaises(ValueError):
            self.hub.enqueue_mine_request(first.owner, 13, self.ticket(first.owner), 3)
        self.assertEqual(self.hub.mine_requests[first.owner], first)

    def test_real_account_other_slot_cannot_queue_or_reenter_same_round(self):
        alternate = self.add_player('Bobby', slot=2, name='BobbyTwo')
        first = self.enqueue(1, 2)
        with self.assertRaises(ValueError):
            self.hub.enqueue_mine_request(alternate, 13, self.ticket(alternate), 2)
        self.hub.cancel_mine_request(first.owner)
        # Retired participants remain in the reward roster after battle exit.
        self.battle['reward_roster'][first.owner] = ('Bobby', (4,), 1)
        self.hub.enqueue_mine_request(alternate, 13, self.ticket(alternate), 2)
        self.assertEqual(self.hub.try_mine_requests(self.battle), ())
        self.assertFalse(self.hub.mine_waiting(alternate))

    def test_busy_foreign_ticket_wrong_city_and_fake_owner_rejected(self):
        owner = self.owners[1]; ticket = self.ticket(owner)
        self.hub.other_busy.add(owner)
        with self.assertRaises(ValueError): self.hub.enqueue_mine_request(owner, 13, ticket, 2)
        self.hub.other_busy.clear()
        for town, raw in [(14, ticket), (13, replace(ticket, character_id=self.owners[2]))]:
            with self.assertRaises(ValueError): self.hub.enqueue_mine_request(owner, town, raw, 2)
        s = self.hub.players[owner]; s.account = 'MissingSave'
        with self.assertRaises(ValueError): self.hub.enqueue_mine_request(owner, 13, ticket, 2)

    def test_roster_health_and_selection_revalidated_at_admission(self):
        first = self.enqueue(1, 2); self.enqueue(4, 2)
        s = self.hub.players[first.owner]
        with transaction(self.path) as db:
            raw, = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1', (s.account,)).fetchone()
            pet = decode_pet_info(raw, human_equipment=True)
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                       (encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4ab1': 0})), s.account))
        self.assertEqual(self.hub.try_mine_requests(self.battle), (self.owners[4],))
        self.assertFalse(self.hub.mine_waiting(first.owner))
        with self.assertRaises(ValueError): revalidate_owned(self.path, s.account, first.ticket)

    def test_current_clan_membership_checked_again_before_help_admission(self):
        first = self.enqueue(2, 3); self.enqueue(3, 3)
        self.clans.remove('Clara'); self.battle['mine_help'] = {3: True}
        self.assertEqual(self.hub.try_mine_requests(self.battle), (self.owners[3],))
        self.assertFalse(self.hub.mine_waiting(first.owner))

    def test_foreign_database_queue_not_admitted_or_exposed(self):
        foreign = self.add_player('Georg', path=self.path.parent / 'other.db')
        self.hub.enqueue_mine_request(foreign, 13, self.ticket(foreign), 2)
        local = self.enqueue(1, 2)
        self.assertEqual(self.last_rows(local.owner), (QueueMember(1, 2, 0),))
        self.assertEqual(self.hub.try_mine_requests(self.battle), (local.owner,))
        self.assertTrue(self.hub.mine_waiting(foreign))

    def test_join_or_commit_failure_preserves_queue_help_and_authority(self):
        request = self.enqueue(2, 3); self.battle['mine_help'] = {3: True}
        for flag in ('fail_join', 'fail_commit'):
            setattr(self.hub, flag, True)
            with self.assertRaises(sqlite3.OperationalError): self.hub.try_mine_requests(self.battle)
            self.assertEqual(self.hub.mine_requests[request.owner], request)
            self.assertNotIn(request.owner, self.hub.battles)
            self.assertTrue(self.battle['mine_help'][3])
            setattr(self.hub, flag, False)
        self.assertEqual(self.hub.try_mine_requests(self.battle), (request.owner,))

    def test_changed_level_or_new_busy_reason_invalidates_entry(self):
        first = self.enqueue(1, 2); second = self.enqueue(4, 2); self.enqueue(5, 2)
        with transaction(self.path) as db:
            settle_experience(db, 'Bobby', 'later-earned-level-seven', {1: FLOORS[6] - FLOORS[3]})
        self.hub.other_busy.add(second.owner)
        self.assertEqual(self.hub.try_mine_requests(self.battle), (self.owners[5],))
        self.assertFalse(self.hub.mine_waiting(first.owner)); self.assertFalse(self.hub.mine_waiting(second.owner))

    def test_no_defense_permission_and_wrong_band_rejected_on_enqueue(self):
        with self.assertRaises(ValueError): self.enqueue(1, 3)
        owner = self.owners[1]
        with transaction(self.path) as db:
            settle_experience(db, 'Bobby', 'earned-level-seven', {1: FLOORS[6] - FLOORS[3]})
        with self.assertRaises(ValueError):
            self.hub.enqueue_mine_request(owner, 13, self.ticket(owner), 2)

    def test_offline_entry_dropped_before_admitting_next(self):
        first = self.enqueue(1, 2); second = self.enqueue(4, 2)
        self.hub.offline[first.owner] = 100.
        self.assertEqual(self.hub.try_mine_requests(self.battle), (second.owner,))
        self.assertFalse(self.hub.mine_waiting(first.owner))


if __name__ == '__main__': unittest.main()
