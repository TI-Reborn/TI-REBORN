"""Disposable registered accounts and native protocol checks, not GUI acceptance."""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import random
import shutil
import sqlite3
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.accounts import Accounts
from server.battle_journal import BattleJournal
from server.contracts_service import ContractsService
from server.team_arena import TeamArena
from tio import battle_checkpoints
from tio.arena_service import ArenaService
from tio.characters import CharacterStore
from tio.locations import LocationStore, center
from tio.owned_pets import OwnedPetStore
from tio.protocol.battle_move import BattleMove, encode_move_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.item_list import encode_item_list
from tio.protocol.character_create import CharacterCreateRequest
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.survival_service import SurvivalService
from tio.wallets import WalletStore
from wallet_fixture import fund_wallet


class Session(SimpleNamespace):
    __hash__ = object.__hash__
    __eq__ = object.__eq__


class ContractsCombatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed_temp = tempfile.TemporaryDirectory()
        cls.seed = Path(cls.seed_temp.name) / 'registered.sqlite3'
        accounts = Accounts(cls.seed)
        characters = CharacterStore(cls.seed)
        LocationStore(cls.seed)
        source = json.loads((Path(__file__).resolve().parents[1] / 'evidence/owned_pet_trial.json').read_text())
        pet = decode_pet_info(bytes.fromhex(source['packet_hex']), human_equipment=True)
        for login in ('alice', 'bravo', 'charlie', 'delta'):
            accounts.create(login, 'LocalContracts123!')
            characters.create(login, CharacterCreateRequest(login.title().encode(), 0, (0, 0, 0, 0)))
            fund_wallet(cls.seed, login, credits=10000, gold=10000)
            for identity in (1, 2):
                raw = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c43eb': identity,
                    '0x8c44a6': 1 if identity == 1 else 0, '0x8c4ab1': pet.fields['0x8c4a07']}))
                OwnedPetStore(cls.seed).ensure(login, raw, encode_item_list(identity, ()), human=True)

    @classmethod
    def tearDownClass(cls):
        cls.seed_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'local.sqlite3'
        shutil.copyfile(self.seed, self.path)
        self.now = 1000.0
        self.clock = lambda: self.now
        self.hub = TeamArena(clock=self.clock)
        self.service = ContractsService(self.hub, self.path, clock=self.clock)
        self.hub.journal = BattleJournal(self.hub, self.path, wall=self.clock)
        self.sessions = []
        self.owners = []
        for login in ('alice', 'bravo', 'charlie', 'delta'):
            event = threading.Event()
            session = Session(account=login, authenticated_account=login, database=self.path,
                probe_character_id=1, probe_character_name=login.title().encode(),
                stopping=event, stop=event.set, arena=ArenaService(clock=self.clock), survival=SurvivalService())
            session.locations = self.service.locations(LocationStore(self.path, clock=self.clock))
            self.sessions.append(session)
            self.owners.append(self.hub.identity(session))

    def group(self, count=2, selected=(1,)):
        self.service.parties.create('alice', selected)
        for session in self.sessions[1:count]:
            invite = self.service.parties.invite('alice', session.account)
            self.service.parties.accept(session.account, invite['id'], selected)
        party = self.service.parties.info('alice')
        self.contract = self.service.contracts.accept(party, 'alice', 'camp', 'request-one')
        for session in self.sessions[:count]:
            self.service.parties.ready(session.account, True)
        target = self.contract['target']
        self.service.travel.travel('alice', struct.pack('<Bii', 0x1b, target['x'], target['y']))
        route = self.service.travel.route(party['id'])
        self.now = route[5] + .1
        self.assertTrue(self.service.travel.arrive('alice'))
        return self.service.parties.info('alice')

    def start(self, count=2, selected=(1,), load=True):
        self.party = self.group(count, selected)
        battle = self.hub.start_contract(self.sessions[0], self.service)
        self.assertIs(self.hub.battles[self.owners[0]], battle)
        if load:
            for session in self.sessions[:count]:
                self.hub.handle(session, b'\x36')
            self.hub.tick()
        return battle

    def clear_enemies(self, battle):
        with self.hub.journal.unit(battle):
            field = battle['field']
            for owner in battle['bots']:
                for identity in field.actor_ids(owner):
                    field._actors[identity] = replace(field.actor(identity), health=0)

    def rows(self, table):
        with closing(sqlite3.connect(self.path)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                return ()
            return tuple(db.execute('SELECT * FROM ' + table).fetchall())

    def test_two_real_accounts_share_field_unique_actor_ownership_and_private_views(self):
        battle = self.start()
        field = battle['field']
        first, second = self.owners[:2]
        self.assertIs(self.hub.battles[first], self.hub.battles[second])
        self.assertEqual(battle['humans'], {first, second})
        self.assertEqual(len(field.combat.persistence), 2)
        actors = (field.actor_ids(first)[0], field.actor_ids(second)[0])
        self.assertNotEqual(*actors)
        self.assertTrue(field.allied(first, second))
        self.assertFalse(field.allied(first, next(iter(battle['bots']))))
        self.assertEqual(tuple(field.combat.storage_ids[i] for i in actors), (1, 1))
        self.assertEqual({account for _, account in field.combat.persistence.values()}, {'alice', 'bravo'})
        self.assertIsNone(self.service.contracts.target_for('charlie'))
        self.assertEqual(len(battle_checkpoints.read(self.path)), 1)
        self.assertEqual(self.service.parties.info('alice')['state'], 'battle')
        before = field.actor(actors[1])
        with self.assertRaises(ValueError):
            self.hub.perform_action(battle, first, encode_move_request(BattleMove(actors[1], ((before.x+1, before.y),))))
        self.assertEqual(self.hub.battles[first]['field'].actor(actors[1]), before)

    def test_four_real_accounts_eight_fighters_have_one_mission_without_mirror_saves(self):
        before = self.rows('characters')
        battle = self.start(4, (1, 2), load=False)
        self.assertEqual(len(battle['humans']), 4)
        self.assertEqual(len(battle['field'].combat.persistence), 8)
        self.assertEqual(len(battle['room'].members), 5)
        self.assertEqual(self.rows('characters'), before)
        for owner in self.owners:
            self.assertEqual(len(battle['field'].actor_ids(owner)), 2)
            self.assertIn(b'\x41', self.hub.queues[owner])
        self.assertFalse(self.rows('team_ranked_matches'))

    def test_start_authorization_presence_position_and_live_roster_are_rechecked(self):
        party = self.group()
        for session in (self.sessions[1], self.sessions[2]):
            with self.assertRaises(ValueError):
                self.hub.start_contract(session, self.service)
        self.service.parties.ready('bravo', False)
        with self.assertRaisesRegex(ValueError, 'готовы'):
            self.hub.start_contract(self.sessions[0], self.service)
        self.service.parties.ready('bravo', True)
        self.service.parties.set_online('bravo', False)
        with self.assertRaisesRegex(ValueError, 'сети'):
            self.hub.start_contract(self.sessions[0], self.service)
        self.service.parties.set_online('bravo', True)
        self.service.parties.ready('alice', True)
        self.service.parties.ready('bravo', True)
        with closing(sqlite3.connect(self.path)) as db, db:
            LocationStore._save(db, 'bravo', None, 0, 200)
        with self.assertRaisesRegex(ValueError, 'цели'):
            self.hub.start_contract(self.sessions[0], self.service)
        target = self.contract['target']
        with closing(sqlite3.connect(self.path)) as db, db:
            LocationStore._save(db, 'bravo', None, target['x'], target['y'])
            raw = db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1', ('bravo',)).fetchone()[0]
            pet = decode_pet_info(raw, human_equipment=True)
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',
                       (encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4ab1': 0})), 'bravo'))
        with self.assertRaisesRegex(ValueError, 'живые'):
            self.hub.start_contract(self.sessions[0], self.service)
        self.assertFalse(self.hub.battles)
        self.assertEqual(self.service.contracts.active(party['id'])['state'], 'arrived')
        self.assertFalse(battle_checkpoints.read(self.path))

    def test_failed_builder_rolls_back_contract_party_checkpoint_and_packets(self):
        party = self.group()
        prior = {owner: tuple(queue) for owner, queue in self.hub.queues.items()}
        with patch('tio.contract_scene.prepare', side_effect=ValueError('fixture build failed')):
            with self.assertRaisesRegex(ValueError, 'fixture'):
                self.hub.start_contract(self.sessions[0], self.service)
        self.assertFalse(self.hub.battles)
        self.assertEqual(self.service.parties.info('alice')['state'], 'at_target')
        self.assertEqual(self.service.contracts.active(party['id'])['state'], 'arrived')
        self.assertEqual({owner: tuple(queue) for owner, queue in self.hub.queues.items()}, prior)
        self.assertFalse(battle_checkpoints.read(self.path))

    def test_victory_paid_once_to_each_frozen_account_and_returns_party_city(self):
        battle = self.start(selected=(1, 2))
        before = {account: WalletStore(self.path).ensure(account).credits for account in ('alice', 'bravo')}
        self.clear_enemies(battle)
        self.hub.finish(battle)
        self.assertTrue(battle['finished'])
        self.assertEqual(battle['contract_receipt']['state'], 'completed')
        for account in ('alice', 'bravo'):
            self.assertEqual(WalletStore(self.path).ensure(account).credits-before[account], 150)
        self.assertFalse(self.service.contracts.pending_awards(battle['contract_id']))
        self.assertEqual(sum(row[4] for row in self.rows('pve_contract_awards')), 2)
        for owner in self.owners[:2]:
            report = battle['settlement_inputs'][owner][1]
            self.assertEqual(sum(report['experience_report'].values()), 60)
            self.assertNotIn('rank_report', report)
            self.assertNotIn('statistics_report', report)
            self.assertNotIn('ranked_report', report)
            self.assertNotIn('team_ranked_report', report)
            self.assertEqual(report['experience_report'], {1: 30, 2: 30})
            summary = battle['result_packets'][owner][-1]
            self.assertEqual(summary[0], 0x4c)
            self.assertEqual(summary[28], 2)
        self.assertFalse(self.rows('reward_pairs'))
        after = self.rows('battle_rewards')
        self.hub.finish_contract(battle)
        for owner in self.owners[:2]:
            self.hub.settle(battle, owner, 1)
        self.assertEqual(self.rows('battle_rewards'), after)
        party = self.service.parties.info('alice')
        self.assertEqual(party['state'], 'city')
        self.assertFalse(any(member['ready'] for member in party['members']))
        for session in self.sessions[:2]:
            self.assertEqual(session.locations.current(session.account), 3)
            self.assertEqual(session.locations.position(session.account), center(3))
            self.assertTrue(self.hub.handle(session, b'\x2a\x01'))
            self.assertFalse(self.hub.busy(session))

    def test_settlement_failure_rolls_back_wallet_intents_terminal_state_and_memory(self):
        battle = self.start()
        self.clear_enemies(battle)
        before = self.rows('wallets')
        with patch('tio.battle_rewards.settle', side_effect=ValueError('fixture wallet failed')):
            with self.assertRaises(Exception):
                self.hub.finish_contract(battle)
        live = self.hub.battles[self.owners[0]]
        self.assertFalse(live['finished'])
        self.assertEqual(self.rows('wallets'), before)
        self.assertEqual(self.service.contracts.active(self.party['id'])['state'], 'active')
        self.assertFalse(self.service.contracts.pending_awards(live['contract_id']))
        self.hub.finish_contract(live)
        self.assertTrue(live['finished'])

    def test_premium_scales_combat_experience_but_keeps_contract_quote_fixed(self):
        from tio.premium import purchase, encode_purchase, OFFERS
        purchase(self.path, 'alice', encode_purchase(1, OFFERS[1][1]), now=int(time.time()))
        battle = self.start(selected=(1, 2))
        field = battle['field']
        owner = self.owners[0]
        attacker = field.actor(field.actor_ids(owner)[0])
        victim = field.actor(field.actor_ids(next(iter(battle['bots'])))[0])
        with self.hub.journal.unit(battle):
            field.combat.experience.damage(field.combat, attacker, victim, 10)
        earned = field.combat.experience.report(field.combat, owner)[attacker.actor_id]
        self.assertGreater(earned, 0)
        before = WalletStore(self.path).ensure('alice').credits
        self.clear_enemies(battle)
        self.hub.finish_contract(battle)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits-before, 150)
        with closing(sqlite3.connect(self.path)) as db:
            gains = dict(db.execute('SELECT pet_id,gain FROM experience_battle_audit WHERE account=? AND match_id=?',
                                    ('alice', battle['match_id'])))
        self.assertEqual(gains[1], earned*3//2+30)
        self.assertEqual(gains[2], 30)

    def staged_winning_intents(self):
        battle = self.start()
        self.clear_enemies(battle)
        with self.hub.journal.unit(battle):
            self.service.contracts.transition(battle['contract_id'], 'active', 'completed', match_id=battle['match_id'])
            battle['contract_result'] = 1
        return battle, self.hub.contract_settlement_inputs(battle, self.owners[0])

    def test_tampered_quote_or_bonus_rolls_back_claim_and_wallet(self):
        from tio.battle_rewards import settle
        battle, values = self.staged_winning_intents()
        before = self.rows('wallets')
        intents = self.service.contracts.pending_awards(battle['contract_id'])
        for key in ('credits', 'experience', 'bonus_experience'):
            tampered = deepcopy(values)
            report = tampered['contract_report']
            if key == 'bonus_experience':
                report[key][1] += 1
            else:
                report[key] += 1
            with self.subTest(field=key), self.assertRaises(ValueError):
                settle(self.path, 'alice', battle['match_id'], 1, **tampered)
            self.assertEqual(self.rows('wallets'), before)
            self.assertEqual(self.service.contracts.pending_awards(battle['contract_id']), intents)
            self.assertFalse(self.rows('battle_rewards'))
        settle(self.path, 'alice', battle['match_id'], 1, **values)
        self.assertEqual(WalletStore(self.path).ensure('alice').credits, 10150)
        self.assertEqual([row['owner'] for row in self.service.contracts.pending_awards(battle['contract_id'])], ['bravo'])

    def test_wrong_match_or_owner_cannot_claim_another_participants_intent(self):
        from tio.battle_rewards import settle
        battle, values = self.staged_winning_intents()
        intents = self.service.contracts.pending_awards(battle['contract_id'])
        before = self.rows('wallets')
        for owner, match in (('alice', 'another-match'), ('charlie', battle['match_id']), ('bravo', battle['match_id'])):
            with self.subTest(owner=owner, match=match), self.assertRaises(ValueError):
                settle(self.path, owner, match, 1, **values)
            self.assertEqual(self.rows('wallets'), before)
            self.assertEqual(self.service.contracts.pending_awards(battle['contract_id']), intents)
            self.assertFalse(self.rows('battle_rewards'))

    def test_participant_exit_aborts_everyone_no_rewards_or_early_city_return(self):
        battle = self.start()
        before = self.rows('wallets')
        with self.assertRaises(ValueError):
            self.hub.contract_to_city(battle, self.owners[0])
        self.hub.handle(self.sessions[1], b'\x2a\x01')
        self.assertTrue(battle['finished'])
        self.assertEqual(battle['contract_receipt']['outcome'], 'aborted')
        self.assertEqual(self.rows('wallets'), before)
        self.assertFalse(self.hub.battles)
        self.assertFalse(self.service.contracts.pending_awards(battle['contract_id']))
        self.assertEqual(self.service.parties.info('alice')['state'], 'city')
        for session in self.sessions[:2]:
            self.assertEqual(session.locations.current(session.account), 3)
        self.assertFalse(battle_checkpoints.read(self.path))

    def test_loading_timeout_aborts_entire_party_without_awards(self):
        battle = self.start(load=False)
        self.now = battle['deadline'] + 1
        self.hub.tick()
        self.assertTrue(battle['finished'])
        self.assertEqual(battle['contract_abort_reason'], 'loading_timeout')
        self.assertEqual(self.service.parties.info('alice')['state'], 'city')
        self.assertFalse(self.service.contracts.pending_awards(battle['contract_id']))

    def mission_via_another_city(self):
        self.service.parties.create('alice', (1,))
        invite = self.service.parties.invite('alice', 'bravo')
        self.service.parties.accept('bravo', invite['id'], (1,))
        self.party = self.service.parties.info('alice')
        contract = self.service.contracts.accept(self.party, 'alice', 'camp', 'via-city-two')
        self.assertEqual(contract['town_id'], 3)
        for account in ('alice', 'bravo'):
            self.service.parties.ready(account, True)
        self.service.travel.travel('alice', struct.pack('<Bii', 0x1b, *center(2)))
        route = self.service.travel.route(self.party['id'])
        self.now = route[5] + .1
        self.service.travel.arrive('alice')
        self.assertEqual(self.service.parties.info('alice')['town_id'], 2)
        self.assertEqual(self.service.parties.info('alice')['state'], 'city')
        for account in ('alice', 'bravo'):
            self.service.parties.ready(account, True)
        target = contract['target']
        self.service.travel.travel('alice', struct.pack('<Bii', 0x1b, target['x'], target['y']))
        route = self.service.travel.route(self.party['id'])
        self.now = route[5] + .1
        self.service.travel.arrive('alice')
        self.assertEqual(self.service.parties.info('alice')['town_id'], 2)
        self.assertEqual(self.service.contracts.active(self.party['id'])['state'], 'arrived')
        return self.hub.start_contract(self.sessions[0], self.service)

    def assert_origin_city_accepts_next_group_actions(self, battle):
        self.assertEqual(battle['city_id'], 3)
        party = self.service.parties.info('alice')
        self.assertEqual((party['state'], party['town_id']), ('city', 3))
        self.assertFalse(any(member['ready'] for member in party['members']))
        for session in self.sessions[:2]:
            self.assertEqual(session.locations.current(session.account), 3)
            self.assertEqual(session.locations.position(session.account), center(3))
            self.service.parties.ready(session.account, True)
        invitation = self.service.parties.invite('alice', 'charlie')
        self.service.parties.accept('charlie', invitation['id'], (1,))
        for account in ('alice', 'bravo', 'charlie'):
            self.service.parties.ready(account, True)
        self.service.travel.travel('alice', struct.pack('<Bii', 0x1b, -220, -280))
        self.assertIsNotNone(self.service.travel.route(party['id']))
        self.assertEqual(self.service.parties.info('alice')['state'], 'travelling')

    def test_victory_returns_group_to_contract_origin_after_visiting_another_city(self):
        battle = self.mission_via_another_city()
        self.clear_enemies(battle)
        self.hub.finish_contract(battle)
        for session in self.sessions[:2]:
            self.hub.handle(session, b'\x2a\x01')
        self.assert_origin_city_accepts_next_group_actions(battle)

    def test_abort_returns_group_to_contract_origin_after_visiting_another_city(self):
        battle = self.mission_via_another_city()
        self.hub.abort_contract(battle, 'participant_left')
        self.assert_origin_city_accepts_next_group_actions(battle)

    def test_recovery_resumes_same_scene_seed_roster_and_once_awards(self):
        battle = self.start()
        match, ground = battle['match_id'], battle['ground']
        recovered = TeamArena(clock=self.clock)
        service = ContractsService(recovered, self.path, clock=self.clock)
        recovered.journal = BattleJournal(recovered, self.path, wall=self.clock)
        self.assertEqual(recovered.journal.recover(), [match])
        restored = recovered.battles[self.owners[0]]
        self.assertIs(restored, recovered.battles[self.owners[1]])
        self.assertEqual(restored['ground'], ground)
        self.assertEqual(restored['contract_id'], battle['contract_id'])
        self.assertEqual(restored['contract_roster'], battle['contract_roster'])
        self.assertEqual(service.parties.info('alice')['state'], 'battle')
        for session in self.sessions[:2]:
            session.locations = service.locations(LocationStore(self.path, clock=self.clock))
            self.assertTrue(recovered.resume(session))
            recovered.handle(session, b'\x36')
        with recovered.journal.unit(restored):
            for owner in restored['bots']:
                for identity in restored['field'].actor_ids(owner):
                    restored['field']._actors[identity] = replace(restored['field'].actor(identity), health=0)
        recovered.finish_contract(restored)
        self.assertEqual(len(self.rows('battle_rewards')), 2)
        self.assertFalse(service.contracts.pending_awards(restored['contract_id']))
        again = TeamArena(clock=self.clock)
        again.journal = BattleJournal(again, self.path, wall=self.clock)
        self.assertEqual(again.journal.recover(), [match])
        self.assertEqual(len(self.rows('battle_rewards')), 2)
        self.assertEqual(set(again.completed), set(self.owners[:2]))

    def test_npc_bot_uses_shared_actions_without_player_save_or_inventory_leaks(self):
        from server.battle_events import BotEventArena
        from tio.training_bot import play_turn
        battle = self.start()
        with self.hub.journal.unit(battle):
            turn = battle['arena']._turns.get(battle['room'].room_id)
            if turn:
                self.hub.perform_action(battle, turn[0], encode_end_turn())
            field = battle['field']
            field.blocked = frozenset()
            field.transparent_obstacles = frozenset()
            field.doors.states = {}
            field.doors.solid = frozenset()
            for index, owner in enumerate(self.owners[:2]):
                identity = field.actor_ids(owner)[0]
                field._actors[identity] = replace(field.actor(identity), x=12, y=12+index, sight_radius=30)
            bot = next(iter(battle['bots']))
            for index, identity in enumerate(field.actor_ids(bot)):
                field._actors[identity] = replace(field.actor(identity), x=15+index, y=12, sight_radius=30)
            field.combat.rng = random.Random(1)
            for view in battle['views'].values():
                view.refresh()
            for queue in self.hub.queues.values():
                queue.clear()
            play_turn(BotEventArena(self.hub, battle), battle['room'].room_id, bot)
        for owner in self.owners[:2]:
            packets = tuple(self.hub.queues[owner])
            self.assertTrue(any(packet[0] in (0x3d, 0x4b) for packet in packets))
            for packet in packets:
                if packet[0] == 0x30:
                    self.assertIn(int.from_bytes(packet[1:5], 'little'), battle['field'].actor_ids(owner))
        self.assertEqual(len(self.rows('owned_pets')), 8)
        self.assertEqual(len(battle['field'].combat.persistence), 2)


if __name__ == '__main__':
    unittest.main()
