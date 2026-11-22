"""Regressions for the remaining player reports, using isolated saved accounts."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import struct
import unittest


class RangeReturnTests(unittest.TestCase):
    def setUp(self):
        from test_shooting_range import RangeTests
        self.fixture = RangeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_training_does_not_reuse_an_earlier_road_encounter_return(self):
        from tio.protocol.system_message import (
            encode_current_town, encode_open_town_view)
        from tio.shooting_range import POLICY
        from tio.locations import SHOOTING_RANGE
        f = self.fixture
        f.arena._return_maps[42] = (-81, -243)
        f.arena._map_returned.add(42)
        f.start()
        f.now[0] += POLICY['session_seconds'] + 1
        self.assertTrue(f.arena.finish_training(42, f.path, 'alice'))
        replies = f.arena.finish_results(42, b'\x2a\x01')
        self.assertEqual(replies[1:], (
            encode_current_town(SHOOTING_RANGE), encode_open_town_view()))
        self.assertNotIn(42, f.arena._map_returned)

    def test_failed_token_admission_releases_the_waiting_room_and_travel(self):
        from server.battle_journal import PrivateJournal
        from tio.shooting_range import CREATE_REQUEST
        from tio.protocol.system_message import encode_leave_room
        f = self.fixture
        PrivateJournal(f.arena, f.path, 'alice')
        f.service.admission.pay('alice', 0, 'previous-visit')
        money = f.service.admission.assets('alice')
        f.service.handle('alice', 42, b'Alice', CREATE_REQUEST)
        started, replies = f.service.handle('alice', 42, b'Alice', b'\x2e\0')
        self.assertIsNone(started)
        self.assertIn(encode_leave_room(), replies)
        self.assertTrue(any('жетон'.encode('utf-16-le') in p for p in replies))
        self.assertEqual(f.arena.rooms.snapshot(), ())
        self.assertFalse(f.arena._fields)
        self.assertEqual(f.service.admission.assets('alice'), money)
        self.assertTrue(f.locations.travel(
            'alice', struct.pack('<Bii', 0x1b, -81, -243), 42))

    def test_range_and_encounter_fields_keep_the_selected_portrait(self):
        from tio import avatars
        from tio.abilities import AbilityCatalog, AbilityLevel
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from tools.encounter_scene import prepare_encounter
        from tools.shooting_range_scene import prepare_range
        from pathlib import Path
        import json
        f = self.fixture
        with closing(sqlite3.connect(f.path)) as db, db:
            avatars.ensure(db)
            db.execute('INSERT INTO pet_avatars VALUES (?,?,?)',
                       ('alice', f.identity, 10007))
        root = Path(__file__).resolve().parents[1]
        rows = json.loads((root/'config/abilities.json').read_text())['records']
        catalog = AbilityCatalog(AbilityLevel(
            r['id'], r['level'], r['fields']) for r in rows)
        ticket = SurvivalQueue().join(42, OwnedPetStore(f.path).list('alice'))
        for prepare, options in ((prepare_range, {'clock': lambda: f.now[0]}),
                                 (prepare_encounter, {'seed': 7})):
            with self.subTest(scene=prepare.__name__):
                scene = prepare(f.path, 'alice', ticket, catalog, **options)
                self.assertEqual(scene.field.avatar_ids[f.identity], 10007)


class WeaponSkillTests(unittest.TestCase):
    def test_slash_is_only_shown_with_the_equipped_primary_hammer(self):
        from tio.protocol.abilities import AbilityEntry
        from tio.protocol.item_list import encode_item_list
        from tio.weapon_effects import battle_skills
        from test_enhancement import item
        learned = (AbilityEntry(22, 1, 0, 1),)
        for template, slot in ((335, 16), (335, 128), (335, 0), (336, 16)):
            with self.subTest(template=template, slot=slot):
                inventory = encode_item_list(1, (replace(
                    item(1, template), unknown_u8_01=int(bool(slot)),
                    location_raw=slot),))
                expected = learned if template == 335 and slot == 16 else ()
                self.assertEqual(battle_skills(learned, inventory, True), expected)


class PrivateDogTurnTests(unittest.TestCase):
    def prepare(self):
        from test_shooting_range import RangeTests
        from tio.abilities import AbilityCatalog, AbilityLevel
        from tio.matchmaking import SurvivalQueue
        from tio.owned_pets import OwnedPetStore
        from server.battle_journal import PrivateJournal
        from tools.encounter_scene import prepare_encounter
        from pathlib import Path
        import json
        import random
        f = RangeTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        rows = json.loads((Path(__file__).resolve().parents[1]/
                           'config/abilities.json').read_text())['records']
        catalog = AbilityCatalog(AbilityLevel(
            r['id'], r['level'], r['fields']) for r in rows)
        ticket = SurvivalQueue().join(42, OwnedPetStore(f.path).list('alice'))
        PrivateJournal(f.arena, f.path, 'alice')
        scene = prepare_encounter(f.path, 'alice', ticket, catalog, seed=7)
        scene.field.combat.rng = random.Random(7)
        room, _ = f.arena.start_survival(42, b'Alice', scene)
        f.arena.member_loaded(42, b'\x36')
        return f, room.room_id, scene.bot_owner

    def test_busy_after_npc_actions_rolls_back_before_retrying_the_whole_turn(self):
        from server.battle_journal import play_private_turn
        from tio.training_bot import play_turn
        from tio.owned_pets import OwnedPetStore
        from unittest.mock import patch
        f, room, bot = self.prepare()
        attempts = []
        def busy_once(arena, room_id, owner, **options):
            replies = play_turn(arena, room_id, owner, **options)
            field = arena._fields[room_id]
            attempts.append((replies, dict(field._actors),
                             OwnedPetStore(f.path).list('alice')))
            if len(attempts) == 1:
                raise sqlite3.OperationalError('database is locked')
            return replies
        with patch('tio.training_bot.play_turn', side_effect=busy_once):
            replies = play_private_turn(f.arena, room, bot)
        self.assertTrue(replies)
        self.assertEqual(attempts[0], attempts[1])
        self.assertEqual(OwnedPetStore(f.path).list('alice'), attempts[1][2])
        self.assertNotIn(room, f.arena._turns)
        self.assertEqual(f.arena._last_turn[room], bot)

    def test_persistent_busy_has_a_bound_and_preserves_the_checkpoint(self):
        from server.battle_journal import play_private_turn
        from tio.battle_snapshot import dumps
        from unittest.mock import patch
        f, room, bot = self.prepare()
        before = dumps(f.arena, clock=f.arena._clock, wall=lambda: 1000)
        with closing(sqlite3.connect(f.path)) as db:
            saved = db.execute('SELECT * FROM battle_checkpoints').fetchall()
        with patch('tio.training_bot.play_turn', side_effect=
                   sqlite3.OperationalError('database is locked')) as turn:
            with self.assertRaises(sqlite3.OperationalError):
                play_private_turn(f.arena, room, bot)
        self.assertEqual(turn.call_count, 3)
        self.assertEqual(dumps(f.arena, clock=f.arena._clock, wall=lambda: 1000), before)
        with closing(sqlite3.connect(f.path)) as db:
            self.assertEqual(db.execute('SELECT * FROM battle_checkpoints').fetchall(), saved)


class UpgradeMenuTests(unittest.TestCase):
    def setUp(self):
        from test_enhancement import EnhancementTests
        self.fixture = EnhancementTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_menu_request_uses_one_ordinary_kit_in_the_owned_bag(self):
        from test_enhancement import request, item
        from tio.protocol.item_list import decode_item_list
        f = self.fixture
        f.seed(item(1001, 301), item(1002, 30, count=2))
        result = f.store.handle('alice', request(kit=None))
        target, kit = decode_item_list(f.saved())[1]
        self.assertEqual((result.level, target.unknown_bytes_03[0], kit.count),
                         (1, 1, 1))

    def test_missing_or_foreign_kit_cannot_be_used_by_the_menu(self):
        from test_enhancement import request, item
        from tio.owned_pets import OwnedPetStore
        from tio.protocol.item_list import encode_item_list
        f = self.fixture
        f.seed(item(1001, 301))
        OwnedPetStore(f.path).ensure('bob', f.pet,
            encode_item_list(1, (item(1002, 30),)), human=True)
        before = f.saved()
        bob_before = OwnedPetStore(f.path).inventory('bob', 1)
        with self.assertRaisesRegex(ValueError, 'Upgrade Kit required'):
            f.store.handle('alice', request(kit=None))
        self.assertEqual(f.saved(), before)

        self.assertEqual(OwnedPetStore(f.path).inventory('bob', 1), bob_before)

    def test_an_explicit_stale_kit_does_not_fall_back_to_a_different_one(self):
        from test_enhancement import request
        f = self.fixture
        before = f.saved()
        with self.assertRaises(ValueError):
            f.store.handle('alice', request(kit=9999))
        self.assertEqual(f.saved(), before)


class ClanMemberCountTests(unittest.TestCase):
    def test_native_row_reads_current_members_before_capacity_in_its_caption(self):
        from tio.protocol.clan_ratings import ClanRating, encode_ratings
        packet = encode_ratings(0, 0, (
            ClanRating(7, b'C', b'A', 1, 10, 1, 123),))
        # Reader 6E6FFE stores the first word at +208, the second at +206.
        # Caption 841CE0/841D0C prints +206 / +208.
        capacity, current = struct.unpack_from('<HH', packet, 15)
        self.assertEqual(f'{current}/{capacity}', '1/10')



if __name__ == '__main__':
    unittest.main()
