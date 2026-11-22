import tempfile
import unittest
from contextlib import closing
import sqlite3
import struct
from pathlib import Path

from tio.tournaments import Bracket, standings, save_standings
from tio.protocol import tournaments as wire


class TournamentTests(unittest.TestCase):
    def test_eight_humans_fill_all_slots_and_each_plays_three_rounds(self):
        accounts = tuple(f'player{i}' for i in range(8))
        bracket = Bracket.create(accounts)
        self.assertEqual(bracket.slots, accounts)
        for stage in range(3):
            pairs = bracket.pairs(stage)
            self.assertCountEqual([slot for pair in pairs for slot in pair], range(8))
            for index, (first, _) in enumerate(pairs):
                bracket.resolve(stage, index, first)
        self.assertEqual(bracket.placements(), (0, 4, 2, 6, 1, 5, 3, 7))

    def test_bots_fill_vacancies_without_acquiring_accounts_or_statistics(self):
        bracket = Bracket.create(('alice', 'bob'))
        self.assertEqual(bracket.slots.count(None), 6)
        for stage in range(3):
            for index, (_, second) in enumerate(bracket.pairs(stage)):
                bracket.resolve(stage, index, second)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.sqlite3'
            self.assertEqual(standings(path, 'alice'), (0,) * 8)
            save_standings(path, 'event', bracket)
            save_standings(path, 'event', bracket)
            self.assertEqual(sum(standings(path, 'alice')), 1)
            self.assertEqual(sum(standings(path, 'bob')), 1)
            self.assertEqual(standings(path, 'AI bot 1'), (0,) * 8)

    def test_replayed_result_cannot_change_the_winner(self):
        bracket = Bracket.create(('alice',))
        with self.assertRaises(ValueError):
            bracket.pairs(1)
        with self.assertRaises(ValueError):
            bracket.resolve(0, 0, 7)
        bracket.resolve(0, 0, 0)
        bracket.resolve(0, 0, 0)
        with self.assertRaises(ValueError):
            bracket.resolve(0, 0, 1)

    def test_final_round_retries_with_offline_recipients_after_mail_failure(self):
        from dataclasses import replace
        from tio.mail import MailStore
        from tio.tournaments import advance, create_event, initialise, read_event, record_result

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'game.sqlite3'
            initialise(path)
            bracket = Bracket.create(('alice', 'bob'))
            event = create_event(path, bracket.slots, (b'Alice', b'Bob') + (b'Bot',) * 6, 100)
            for stage in range(3):
                for index, (first, _) in enumerate(bracket.pairs(stage)):
                    bracket.resolve(stage, index, first)
                    record_result(path, event.identity, stage, index, first)
                if stage < 2:
                    event = advance(path, replace(event, bracket=bracket), 100)
            mail = MailStore(path)
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("""CREATE TRIGGER fail_delivery BEFORE INSERT ON mail_messages
                    WHEN NEW.recipient='bob' BEGIN SELECT RAISE(ABORT, 'delivery failed'); END""")
            event = read_event(path, event.identity)
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'delivery failed'):
                advance(path, event, 200, now=150)
            self.assertEqual(read_event(path, event.identity).stage, 2)
            self.assertEqual(standings(path, 'alice'), (0,) * 8)
            self.assertEqual(mail.listing('alice', now=151), ())
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('DROP TRIGGER fail_delivery')
            advance(path, read_event(path, event.identity), 200, now=150)
            self.assertEqual(mail.listing('alice', now=151)[0]['credits'], 45000)
            self.assertEqual(mail.listing('bob', now=151)[0]['credits'], 15000)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM mail_messages').fetchone(), (2,))


class TournamentServerTests(unittest.TestCase):
    def setUp(self):
        from server.battle_journal import BattleJournal
        from server.tournament_arena import TournamentArena
        from test_ranked import RankedServerTests
        self.base = RankedServerTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.case = self.base.case
        self.hub, self.path = self.base.hub, self.base.path
        self.wall = 1000
        self.hub.journal = BattleJournal(self.hub, self.path, wall=lambda: self.wall)
        self.tournaments = self.hub.tournaments = TournamentArena(self.hub, self.path, wall=lambda: self.wall)

    def advance(self, seconds):
        self.wall += seconds
        self.case.now += seconds
        self.hub.tick()

    def ready(self, index):
        responses = self.case.send(index, wire.READY+b'\1\0'+struct.pack('<III', 1, 1, 0)+b'\0')
        self.assertIn(b'\xc6\x42', responses)

    def assert_registered(self, index):
        status = self.case.send(index, wire.REGISTER)
        self.assertTrue(any(packet[:4] == b'\xc6\x39\1\1' and packet[-5] == 1 for packet in status), status)

    def test_shared_round_saves_progress_and_sends_it_once(self):
        from dataclasses import replace
        from unittest.mock import patch
        from server.tournament_arena import PREPARATION_SECONDS, REGISTRATION_SECONDS
        from tio import battle_settlement, ranks
        from tio.level_progression import FLOORS, LEVEL, XP
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.battle_attack import AttackRequest, encode_attack_request
        from tio.protocol.pet_info import decode_pet_info, encode_pet_info
        from tio.visibility import field_sight
        from tio.weapon_proficiency import SAVED, number

        store = OwnedPetStore(self.path)
        _, raw, inventory = store.list('alice')[0]
        pet = decode_pet_info(raw, human_equipment=True)
        raw = encode_pet_info(replace(pet, fields={**pet.fields, XP: FLOORS[4] - 1}))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE owned_pets SET pet_packet=? WHERE account='alice'", (raw,))
        for index in (0, 1):
            self.assert_registered(index)
        with patch.object(self.tournaments.random, 'shuffle'):
            self.advance(REGISTRATION_SECONDS)
        for index in (0, 1):
            self.ready(index)
        self.advance(PREPARATION_SECONDS)
        alice, bob = (self.hub.identities[s] for s in self.case.sessions[:2])
        battle = self.hub.battles[alice]
        self.assertIs(battle, self.hub.battles[bob])
        for index in (0, 1):
            self.case.send(index, b'\x36')
        self.hub.tick()
        field = battle['field']
        attacker, = field.actor_ids(alice)
        victim, = field.actor_ids(bob)
        x, y = next((x, y) for x in range(2, field.width - 2) for y in range(2, field.height - 2)
                    if not {(x, y), (x + 1, y)} & field.blocked
                    and field_sight(field, (x, y), (x + 1, y)))
        field._actors[attacker] = replace(field.actor(attacker), x=x, y=y)
        field._actors[victim] = replace(field.actor(victim), x=x + 1, y=y, health=1)
        with patch('random.Random.randrange', return_value=0), \
                patch('random.Random.randint', side_effect=lambda low, high: low):
            attack_replies = self.case.send(0, encode_attack_request(AttackRequest(attacker, x + 1, y)))
        errors = [p[13:-2].decode('utf-16-le', errors='replace') for p in attack_replies if p[0] == 0xf0]
        self.assertEqual(field.actor(victim).health, 0, errors)
        self.hub.tick()
        self.assertTrue(battle['finished'])
        replies = tuple(self.hub.queues[alice])
        self.hub.queues[alice].clear()
        summary, = (p for p in replies if p[0] == 0x4c)
        self.assertEqual(summary[28], 1)
        identity, gain = struct.unpack_from('<II', summary, 29)
        self.assertEqual(identity, attacker)
        self.assertGreater(gain, 0)
        self.assertTrue(any(p[0] == 0x4e for p in replies))

        saved = store.list('alice')[0]
        fields = decode_pet_info(saved[1], human_equipment=True).fields
        self.assertEqual(fields[XP], FLOORS[4] - 1 + gain)
        self.assertEqual(fields[LEVEL], 5)
        self.assertEqual(fields['0x8c4ab1'], fields['0x8c4a07'])
        self.assertGreater(number(fields[SAVED[0]]), number(pet.fields[SAVED[0]]))
        self.assertGreater(ranks.signed(fields['0x8c4bd0']), 0)
        self.assertGreater(fields['0x8c4bbc'], 1)
        self.assertEqual(saved[2], inventory)
        bob_fields = decode_pet_info(store.list('bob')[0][1], human_equipment=True).fields
        self.assertGreater(bob_fields[XP], FLOORS[3])
        self.assertEqual(bob_fields['0x8c4ab1'], bob_fields['0x8c4a07'])
        self.assertNotIn(summary, self.case.send(0, b'\x2a\x01'))
        battle_settlement.apply(self.path, battle['match_id'], 'alice')
        self.assertEqual(store.list('alice')[0], saved)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(dict(db.execute('SELECT account,credits FROM battle_rewards')), {'alice': 0, 'bob': 0})
            self.assertEqual(db.execute('SELECT COUNT(*) FROM experience_battle_audit').fetchone(), (2,))
        self.case.send(1, b'\x2a\x01')
        self.advance(1)
        self.ready(0)
        self.ready(1)

    def test_failed_rank_write_rolls_back_tournament_skill_and_experience(self):
        from unittest.mock import patch
        from tio import battle_settlement
        from tio.db_transaction import transaction
        from tio.owned_pets import OwnedPetStore
        from tio.rule_catalogs import proficiency_rules
        from tio.weapon_proficiency import saved_skills

        store = OwnedPetStore(self.path)
        original = store.list('alice')[0]
        pet = original[1]
        trained = proficiency_rules().train(pet, True, 'Melee', 5, True)
        report = dict(tournament_proficiency={1: (saved_skills(pet, True), saved_skills(trained, True))},
                      experience_report={1: 10}, rank_report={1: (10, False)})
        battle_settlement.enqueue(self.path, 'round', [('alice', 1, report)])
        with transaction(self.path):
            with patch('tio.ranks.settle_ranks', side_effect=ValueError('rank write failed')):
                with self.assertRaisesRegex(ValueError, 'rank write failed'):
                    battle_settlement.apply(self.path, 'round', 'alice')
        self.assertEqual(store.list('alice')[0], original)
        battle_settlement.apply(self.path, 'round', 'alice')
        self.assertNotEqual(store.list('alice')[0], original)

    def test_human_bot_battle_plays_loads_and_persists_all_rounds(self):
        from server.tournament_arena import PREPARATION_SECONDS, REGISTRATION_SECONDS
        from test_ranked_squads import move_to_exit
        self.assert_registered(0)
        self.advance(REGISTRATION_SECONDS)
        event, = self.tournaments.events.values()
        self.assertEqual(event.bracket.slots.count(None), 7)
        status = self.case.send(0, wire.BRACKET + struct.pack('<Q', event.identity))
        self.assertTrue(any(packet.startswith(b'\xc6\x55') for packet in status))
        owner = self.hub.identities[self.case.sessions[0]]
        for stage in range(3):
            self.ready(0)
            self.advance(PREPARATION_SECONDS)
            battle = self.hub.battles[owner]
            self.assertEqual(battle['tournament'][1], stage)
            self.assertEqual(battle['room'].request.mode, 20)
            self.assertEqual(len(battle['points'].positions), 1)
            bot, = battle['bots']
            field = battle['field']
            actor, = field.actor_ids(bot)
            self.assertTrue(field.actor(actor).weapons)
            self.case.send(0, b'\x36')
            move_to_exit(battle, owner)
            self.case.send(0, b'\x2a\x01')
            self.assertTrue(battle['finished'])
            self.hub.to_city(owner)
            self.advance(1)
        self.assertEqual(standings(self.path, 'alice'), (0, 0, 0, 0, 0, 0, 0, 1))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tournament_results').fetchone(), (12,))
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='ranked_matches'").fetchone())

    def test_armed_bot_uses_ammunition_on_an_authoritative_turn(self):
        from dataclasses import replace
        from server.tournament_arena import PREPARATION_SECONDS, REGISTRATION_SECONDS
        from tio.protocol.item_list import decode_item_list
        self.assert_registered(0)
        self.advance(REGISTRATION_SECONDS)
        self.ready(0)
        self.advance(PREPARATION_SECONDS)
        owner = self.hub.identities[self.case.sessions[0]]
        battle = self.hub.battles[owner]
        bot, = battle['bots']
        field = battle['field']
        actor, = field.actor_ids(bot)
        opponent, = field.actor_ids(owner)
        for x in range(2, field.width - 6):
            if all((x+i, 2) not in field.blocked for i in range(6)):
                break
        else:
            self.fail('Tournament map has no open line along its deployment boundary')
        field._actors[actor] = replace(field.actor(actor), x=x, y=2)
        field._actors[opponent] = replace(field.actor(opponent), x=x + 3, y=2)
        inventory = lambda: decode_item_list(field.combat.inventories[actor])[1]
        before = sum(item.count for item in inventory() if item.template_id in field.combat.catalog.ammunition)
        self.case.send(0, b'\x36')
        battle['ranked_side'] = 1 - field.teams[bot]
        self.hub.tick()
        after = sum(item.count for item in inventory() if item.template_id in field.combat.catalog.ammunition)
        self.assertGreater(before, after)

    def test_eight_registered_accounts_start_four_shared_battles(self):
        from dataclasses import replace
        from server.tournament_arena import PREPARATION_SECONDS
        from tio.mail import MailStore
        from tio.owned_pets import OwnedPetStore
        from tio.tournaments import advance, read_event
        from wallet_fixture import fund_wallet
        from test_shared_team_arena import Session
        example = self.case.sessions[0]
        pet_store = OwnedPetStore(self.path)
        _, pet, inventory = pet_store.list(example.account)[0]
        for index in range(4):
            session = Session()
            session.account = f'extra{index}'
            session.database = self.path
            session.probe_character_id = 1
            session.probe_character_name = session.account.encode()
            session.locations = example.locations
            session.arena = type(example.arena)()
            session.survival = type(example.survival)()
            fund_wallet(self.path, session.account, credits=100, gold=0)
            pet_store.ensure(session.account, pet, inventory, human=True)
            with closing(sqlite3.connect(self.path)) as db, db:
                session.locations._save(db, session.account, 2, -367, -424)
            self.case.sessions.append(session)
        for index in range(8):
            self.assert_registered(index)
        self.advance(1)
        event, = self.tournaments.events.values()
        mail = MailStore(self.path)
        for stage in range(3):
            for index in range(8):
                self.ready(index)
            self.advance(PREPARATION_SECONDS)
            battles = {id(battle): battle for battle in self.hub.battles.values()}
            self.assertEqual(len(battles), 4)
            for battle in battles.values():
                self.assertEqual(battle['tournament'][1], stage)
                self.assertFalse(battle['bots'])
                a, b = battle['humans']
                self.assertIs(self.hub.battles[a], self.hub.battles[b])
                field = battle['field']
                for actor in field.actor_ids(b):
                    field._actors[actor] = replace(field.actor(actor), health=0)
            self.advance(1)
            for index in range(8):
                self.assertTrue(any(p.startswith(b'\x4c') for p in self.case.send(index, b'\x2a\1')))
            self.advance(1)
            if stage < 2:
                for session in self.case.sessions:
                    self.assertEqual(mail.listing(session.account, now=self.wall), ())
        with closing(sqlite3.connect(self.path)) as db:
            placed = db.execute('SELECT account, place FROM tournament_placements ORDER BY place').fetchall()
        self.assertEqual([place for _, place in placed], list(range(1, 9)))
        completed = read_event(self.path, event.identity)
        with self.assertRaisesRegex(ValueError, 'Stale tournament round'):
            advance(self.path, replace(completed, stage=2), self.wall)
        prizes = [(45000, 3), (35000, 2), (25000, 1), (20000, 0),
                  (15000, 0), (10000, 0), (7500, 0), (5000, 0)]
        for (account, place), (credits, injections) in zip(placed, prizes):
            with self.subTest(place=place):
                letter, = mail.listing(account, now=self.wall)
                self.assertEqual(letter['credits'], credits)
                self.assertIn(f'Ваше место: {place} из 8.', letter['body'])
                items = mail.read(account, letter['id'], now=self.wall)['items']
                self.assertEqual([(item.template_id, item.count) for item in items],
                                 [(35, injections)] if injections else [])
