from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from tio.db_transaction import transaction
from tio.pve_contracts import ContractStore, DEFAULT_CATALOG, load_catalog, validate_catalog


class FixedRandom:
    def randrange(self, maximum):
        return 42


def party(identity='party-one', leader='alice', state='city', revision=1):
    return dict(id=identity, leader=leader, town_id=3, state=state, revision=revision,
                members=[dict(owner='alice', login='alice', selected=(11,), online=True, ready=False),
                         dict(owner='bob', login='bob', selected=(21, 22), online=True, ready=False)])


class SnapshotStore:
    def __init__(self, snapshot):
        self.current = deepcopy(snapshot)
        self.connections = []

    def snapshot(self, identity, connection=None):
        self.connections.append(connection)
        return deepcopy(self.current) if identity == self.current['id'] else None


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'contracts.db'
        self.now = [1000.0]
        self.store = ContractStore(self.path, clock=lambda: self.now[0], rng=FixedRandom())
        self.party = party()

    def accept(self, template='camp', request='request-one', snapshot=None):
        return self.store.accept(snapshot or self.party, 'alice', template, request)

    def start(self):
        record = self.accept()
        self.store.transition(record['id'], 'accepted', 'travelling')
        self.store.transition(record['id'], 'travelling', 'arrived')
        snapshot = deepcopy(self.party)
        snapshot['state'] = 'at_target'
        snapshot['revision'] += 2
        for member in snapshot['members']:
            member['ready'] = True
        return self.store.start(record['id'], snapshot, 'alice', 'match-one'), snapshot

    def complete(self):
        record, _ = self.start()
        return self.store.transition(record['id'], 'active', 'completed', match_id='match-one')

    def test_catalogue_is_safe_private_design_and_caller_cannot_mutate_it(self):
        from tio.locations import TOWNS
        before = dict(TOWNS)
        records = self.store.catalog()
        self.assertEqual([r['id'] for r in records], ['camp', 'depot', 'checkpoint'])
        self.assertEqual([r['zone_id'] for r in records], [23, 24, 25])
        records[0]['reward']['credits'] = 123456
        self.assertEqual(self.store.catalog()[0]['reward']['credits'], 150)
        self.assertEqual(TOWNS, before)
        self.assertIn('emulator design', self.store.policy['source'])
        with closing(sqlite3.connect(self.path)) as db:
            names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertTrue(names)
        self.assertTrue(all(name.startswith('pve_contract_') for name in names))

    def test_repeated_accept_freezes_seed_template_roster_and_quote(self):
        first = self.accept()
        self.assertEqual(first['seed'], 42)
        self.assertEqual(first['state'], 'accepted')
        self.assertEqual(first['roster'][0], dict(owner='alice', login='alice', selected=[11]))
        self.assertEqual(first['rewards'][0]['credits'], 150)
        self.store.templates['camp']['reward']['credits'] = 999
        self.assertEqual(self.accept(), first)
        reopened = ContractStore(self.path, clock=lambda: self.now[0])
        self.assertEqual(reopened.active(self.party['id']), first)
        self.assertEqual(reopened.accept(self.party, 'alice', 'camp', 'request-one'), first)
        reduced = deepcopy(reopened.policy)
        reduced['version'] += 1
        reduced['templates'] = reduced['templates'][1:]
        changed_catalog = ContractStore(self.path, clock=lambda: self.now[0], catalog=reduced)
        self.assertEqual(changed_catalog.accept(self.party, 'alice', 'camp', 'request-one'), first)
        with self.assertRaisesRegex(ValueError, 'reused'):
            self.accept('depot')
        with self.assertRaisesRegex(ValueError, 'active'):
            self.accept(request='another-request')

    def test_only_current_leader_in_city_with_real_distinct_online_accounts(self):
        with self.assertRaisesRegex(ValueError, 'leader'):
            self.store.accept(self.party, 'bob', 'camp', 'bob-request')
        for mutation in (
                lambda p: p.update(state='travelling'),
                lambda p: p.update(town_id=17),
                lambda p: p['members'][1].update(online=False),
                lambda p: p['members'][1].update(owner='@character:alice:2', login='alice'),
                lambda p: p['members'][1].update(owner='@character:bob:2', login='alice'),
                lambda p: p['members'][1].update(selected=[]),
                lambda p: p['members'][1].update(selected=[21, 21]),
                lambda p: p['members'][1].update(online=1),
                lambda p: p.update(members=p['members'][:1])):
            snapshot = deepcopy(self.party)
            mutation(snapshot)
            with self.assertRaises(ValueError):
                self.accept(snapshot=snapshot)
        self.assertIsNone(self.store.active(self.party['id']))
        snapshot = deepcopy(self.party)
        snapshot['members'][1].update(owner='@character:bob:2')
        record = self.accept(snapshot=snapshot)
        self.assertEqual(record['roster'][0]['owner'], '@character:bob:2')

    def test_durable_party_snapshot_checked_inside_same_unit(self):
        authority = SnapshotStore(self.party)
        store = ContractStore(self.path, clock=lambda: self.now[0], party_store=authority)
        stale = deepcopy(self.party)
        stale['revision'] = 0
        with self.assertRaisesRegex(ValueError, 'changed'):
            store.accept(stale, 'alice', 'camp', 'one')
        with transaction(self.path) as db:
            store.accept(self.party, 'alice', 'camp', 'one')
            self.assertIs(authority.connections[-1], db)
        authority.current['members'][1]['selected'] = [21]
        with self.assertRaisesRegex(ValueError, 'changed'):
            store.cancel(self.party, 'alice')

    def test_real_party_store_integer_identity_snapshot_start_and_private_membership(self):
        from tio.travel_party import PartyStore
        from tio.protocol.pet_info import PetInfo, decode_pet_info, encode_pet_info
        seed = json.loads((Path(__file__).resolve().parents[1] / 'evidence/owned_pet_trial.json').read_text())
        fields = decode_pet_info(bytes.fromhex(seed['packet_hex']), human_equipment=True).fields
        packet = encode_pet_info(PetInfo(True, {**fields, '0x8c43eb': 1, '0x8c4ab1': 100, '0x8c44a6': 1}))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE accounts(login TEXT PRIMARY KEY)')
            db.execute('CREATE TABLE characters(account TEXT,slot INTEGER)')
            db.execute('CREATE TABLE owned_pets(account TEXT,pet_id INTEGER,human INTEGER,pet_packet BLOB)')
            for owner in ('alice', 'bob'):
                db.execute('INSERT INTO accounts VALUES (?)', (owner,))
                db.execute('INSERT INTO characters VALUES (?,1)', (owner,))
                db.execute('INSERT INTO owned_pets VALUES (?,1,1,?)', (owner, packet))
        authority = PartyStore(self.path, clock=lambda: self.now[0])
        initial = authority.create('alice', (1,))
        invitation = authority.invite('alice', 'bob')
        joined = authority.accept('bob', invitation['id'], (1,))
        self.assertIs(type(joined['id']), int)
        contract = self.store.accept(joined, 'alice', 'camp', 'real-party')
        self.assertEqual(contract['party_id'], str(joined['id']))
        self.assertEqual(self.store.active(joined['id'])['id'], contract['id'])
        self.assertEqual(self.store.target_for('bob')['instance_id'], contract['id'])
        stale = deepcopy(joined)
        stale['revision'] = initial['revision']
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.store.accept(stale, 'alice', 'camp', 'stale')
        self.store.transition(contract['id'], 'accepted', 'arrived')
        authority.change_state(joined['id'], 'at_target', 'city')
        authority.ready('alice', True)
        authority.ready('bob', True)
        active = self.store.start(contract['id'], authority.info('alice'), 'alice', 'real-match')
        self.assertEqual(active['state'], 'active')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM travel_party_members WHERE owner=?', ('bob',))
        self.assertIsNone(self.store.target_for('bob'))

    def test_targets_are_frozen_owner_private_and_slots_cannot_rejoin(self):
        record = self.accept()
        self.assertEqual(self.store.target_for('alice'), record['target'])
        self.assertEqual(self.store.target_for('bob'), record['target'])
        self.assertIsNone(self.store.target_for('charlie'))
        self.assertIsNone(self.store.target_for('@character:alice:2'))
        other = party('party-two')
        other['members'][0]['owner'] = '@character:alice:2'
        other['leader'] = '@character:alice:2'
        with self.assertRaisesRegex(ValueError, 'Account already'):
            self.store.accept(other, other['leader'], 'depot', 'one')
        other['members'][0].update(owner='ALICE', login='ALICE')
        other['leader'] = 'ALICE'
        with self.assertRaisesRegex(ValueError, 'Account already'):
            self.store.accept(other, other['leader'], 'depot', 'one')

    def test_competing_accepts_have_exactly_one_instance(self):
        def accept(request):
            try:
                return self.store.accept(self.party, 'alice', 'camp', request)['id']
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(accept, ('one', 'two')))
        self.assertEqual(sum(value is not None for value in values), 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pve_contract_instances').fetchone()[0], 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = 'one' if values[0] else 'two'
            same = list(pool.map(accept, (winner, winner)))
        self.assertEqual(same[0], same[1])

    def test_state_cas_and_start_roster_presence_readiness_match_guard(self):
        record = self.accept()
        with self.assertRaises(ValueError):
            self.store.transition(record['id'], 'accepted', 'completed')
        with self.assertRaisesRegex(ValueError, 'Use start'):
            self.store.transition(record['id'], 'arrived', 'active')
        self.store.transition(record['id'], 'accepted', 'arrived')
        snapshot = deepcopy(self.party)
        snapshot['state'] = 'at_target'
        with self.assertRaisesRegex(ValueError, 'online and ready'):
            self.store.start(record['id'], snapshot, 'alice', 'match-one')
        for member in snapshot['members']:
            member['ready'] = True
        changed = deepcopy(snapshot)
        changed['members'][1]['selected'] = [21]
        with self.assertRaisesRegex(ValueError, 'roster changed'):
            self.store.start(record['id'], changed, 'alice', 'match-one')
        with self.assertRaisesRegex(ValueError, 'leader'):
            self.store.start(record['id'], snapshot, 'bob', 'match-one')
        active = self.store.start(record['id'], snapshot, 'alice', 'match-one')
        self.assertEqual(active['battle_roster'], active['roster'])
        self.assertEqual(self.store.start(record['id'], snapshot, 'alice', 'match-one'), active)
        with self.assertRaisesRegex(ValueError, 'another battle'):
            self.store.start(record['id'], snapshot, 'alice', 'match-other')
        with self.assertRaisesRegex(ValueError, 'cannot be cancelled'):
            self.store.cancel(snapshot, 'alice')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            self.store.transition(record['id'], 'active', 'completed', match_id='other')

    def test_prebattle_expiry_hides_target_and_allows_new_request(self):
        record = self.accept()
        self.now[0] = record['expires_at']
        self.assertIsNone(self.store.active(self.party['id']))
        self.assertIsNone(self.store.target_for('alice'))
        self.assertEqual(self.store.get(record['id'])['state'], 'expired')
        self.assertEqual(self.accept()['state'], 'expired')
        fresh = self.accept(request='fresh')
        self.assertNotEqual(fresh['id'], record['id'])
        self.assertEqual(fresh['state'], 'accepted')
        self.assertFalse(self.store.pending_awards(record['id']))

    def test_started_battle_does_not_expire_and_loss_never_creates_awards(self):
        record, _ = self.start()
        self.now[0] = record['expires_at'] + 1000
        self.assertEqual(self.store.active(self.party['id'])['state'], 'active')
        failed = self.store.transition(record['id'], 'active', 'failed', outcome='aborted')
        self.assertEqual(failed['outcome'], 'aborted')
        self.assertFalse(self.store.pending_awards(record['id']))
        self.assertIsNone(self.store.target_for('alice'))

    def test_cancel_authorization_terminal_retry_and_no_awards(self):
        record = self.accept()
        with self.assertRaisesRegex(ValueError, 'leader'):
            self.store.cancel(self.party, 'bob')
        cancelled = self.store.cancel(self.party, 'alice')
        self.assertEqual(cancelled['state'], 'cancelled')
        self.assertIsNone(self.store.cancel(self.party, 'alice'))
        self.assertEqual(self.accept(), cancelled)
        self.assertFalse(self.store.pending_awards(record['id']))

    def test_winning_intents_once_per_login_and_claim_joins_settlement(self):
        complete = self.complete()
        intents = self.store.pending_awards(complete['id'])
        self.assertEqual([award['owner'] for award in intents], ['alice', 'bob'])
        self.assertEqual(sum(award['credits'] for award in intents), 300)
        self.store.transition(complete['id'], 'active', 'completed', match_id='match-one')
        self.assertEqual(self.store.pending_awards(complete['id']), intents)
        with self.assertRaisesRegex(ValueError, 'settlement transaction'):
            self.store.claim_award(complete['id'], 'alice')
        with self.assertRaisesRegex(RuntimeError, 'wallet failure'):
            with transaction(self.path) as db:
                award = self.store.claim_award(complete['id'], 'alice')
                self.assertEqual(award, intents[0])
                db.execute('CREATE TABLE test_wallets(owner TEXT PRIMARY KEY,credits INTEGER)')
                db.execute('INSERT INTO test_wallets VALUES (?,?)', ('alice', award['credits']))
                raise RuntimeError('wallet failure')
        self.assertEqual(self.store.pending_awards(complete['id']), intents)
        with transaction(self.path) as db:
            self.assertIsNone(self.store.claim_award(complete['id'], 'charlie'))
            award = self.store.claim_award(complete['id'], 'alice')
            db.execute('CREATE TABLE test_wallets(owner TEXT PRIMARY KEY,credits INTEGER)')
            db.execute('INSERT INTO test_wallets VALUES (?,?)', ('alice', award['credits']))
            self.assertIsNone(self.store.claim_award(complete['id'], 'alice'))
        reopened = ContractStore(self.path, clock=lambda: self.now[0])
        self.assertEqual([award['owner'] for award in reopened.pending_awards(complete['id'])], ['bob'])
        with transaction(self.path):
            self.assertIsNone(reopened.claim_award(complete['id'], 'alice'))

    def test_outer_rollback_removes_complete_action(self):
        with self.assertRaises(RuntimeError):
            with transaction(self.path):
                self.accept()
                raise RuntimeError('unit failed')
        self.assertIsNone(self.store.active(self.party['id']))
        self.assertEqual(self.accept()['state'], 'accepted')

    def test_malformed_catalogue_and_unsafe_bounds_fail_before_schema_write(self):
        source = load_catalog()
        changes = (
            lambda c: c.update(version=True),
            lambda c: c.update(arrival_ttl_seconds=0),
            lambda c: c.update(safe_margin=0),
            lambda c: c['templates'][0].update(zone_id=17),
            lambda c: c['templates'][0].update(bounds=[-600, -245, -270, -225]),
            lambda c: c['templates'][0].update(bounds=[-171, -335, -136, -300]),
            lambda c: c['templates'][0].update(bounds=[-190, -354, -180, -344]),
            lambda c: c['templates'][0].update(bounds=[0, 0, 0, 0]),
            lambda c: c['templates'][0].update(levels=[20, 1]),
            lambda c: c['templates'][0].update(recommended_party_size=[1, 4]),
            lambda c: c['templates'][0]['reward'].update(credits=-1),
            lambda c: c['templates'][0]['enemies'].update(unknown=1),
            lambda c: c['templates'][0].update(map_profile='../escape'),
            lambda c: c['templates'][1].update(zone_id=c['templates'][0]['zone_id']),
            lambda c: c['templates'][1].update(id='camp'),
            lambda c: c['templates'][1].update(bounds=c['templates'][0]['bounds']))
        for index, change in enumerate(changes):
            malformed = deepcopy(source)
            change(malformed)
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_catalog(malformed)
        broken = Path(self.temp.name) / 'bad.json'
        broken.write_text('{bad', encoding='utf-8')
        untouched = Path(self.temp.name) / 'untouched.db'
        with self.assertRaises(ValueError):
            ContractStore(untouched, catalog_path=broken)
        self.assertFalse(untouched.exists())

    def test_invalid_clock_seed_and_request_are_rejected(self):
        for request in ('', 'a' * 129, 'bad\nrequest'):
            with self.assertRaises(ValueError):
                self.accept(request=request)
        self.now[0] = float('nan')
        with self.assertRaisesRegex(ValueError, 'clock'):
            self.accept()
        self.now[0] = 1000
        self.store.rng = type('BadRandom', (), {'randrange': lambda self, n: -1})()
        with self.assertRaisesRegex(ValueError, 'seed'):
            self.accept()
        self.assertIsNone(self.store.active(self.party['id']))


if __name__ == '__main__':
    unittest.main()
