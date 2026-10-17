"""Detroit production checks using temporary saved accounts and native packets.

Normal imports exercise the installed runtime. TIO_DETROIT_CANDIDATE=1 opts
into the local source overlay before deployment; no hosted data is touched.
"""
from contextlib import ExitStack, closing, contextmanager
from dataclasses import replace
import importlib
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

import test_shared_team_arena as fixture
from server.accounts import Accounts
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import (ArenaCreateRequest, decode_battle_settings_body,
                                encode_create_request)
from tio.protocol.battle_attack import AttackRequest, encode_attack_request
from tio.protocol.battle_ground import decode_battle_ground, encode_battle_ground
from tio.protocol.pet_info import decode_pet_info, encode_pet_info
from tio.protocol.wagers import encode_join
from tio.wallets import WalletStore
from tio.weapon_proficiency import skill_signature

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'reports/gameplay-completion/stage8-world/runtime'
CANDIDATE = RUNTIME.parent / 'detroit-wager-candidate'
RUNTIME_MODULES = ('tio.world_completion', 'tio.map_generation', 'tio.cities',
                   'tio.locations', 'tio.combat', 'tio.reward_policy',
                   'tio.battle_rewards', 'tio.team_scene', 'server.world_runtime',
                   'server.battle_journal', 'server.wager_arena', 'server.team_arena')

# Pinned once from the unmodified stage8 original whole-map generator. Ground
# wire excludes spawns, so the static deployment and layout are checked too.
ORIGINAL_MAPS = {
    38: dict(sha256='0ea40b2c1a1ea7adae84ad244d3ef48da06612a011efa42eeabd3f4af8a5c8d7',
             file='junktown/detroit_small_01.s',
             player_spawns=((2, 19), (1, 19), (2, 18), (2, 20), (3, 19), (1, 18)),
             bot_spawns=((35, 19), (34, 19), (35, 18), (35, 20), (36, 19), (34, 18))),
    50: dict(sha256='1fb50dc8bb914704e1ac7e8e77d192a3eb225f7f4756c8d43ead16c921fc4f6f',
             file='junktown/detroit_large_02.s',
             player_spawns=((2, 25), (1, 25), (2, 24), (2, 26), (3, 25), (1, 24)),
             bot_spawns=((47, 25), (46, 25), (47, 24), (47, 26), (48, 25), (46, 24))),
}


@contextmanager
def runtime_under_test():
    """Use production imports by default, without changing any import cache."""
    if os.environ.get('TIO_DETROIT_CANDIDATE') == '1':
        with candidate_runtime() as modules:
            yield modules
    else:
        yield {name: importlib.import_module(name) for name in RUNTIME_MODULES}


@contextmanager
def candidate_runtime():
    """Restore imported modules and package attributes after each isolated test."""
    modules = {}
    with ExitStack() as stack:
        def load(name, path):
            package, attribute = name.rsplit('.', 1)
            parent = importlib.import_module(package)
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            stack.enter_context(patch.dict(sys.modules, {name: module}))
            stack.enter_context(patch.object(parent, attribute, module, create=True))
            spec.loader.exec_module(module)
            # The captured runtime is a source overlay, not a full checkout.
            # Supply the repository's unchanged configuration dependencies.
            module.__file__ = str(ROOT / Path(*name.split('.')).with_suffix('.py'))
            if hasattr(module, 'ROOT'):
                module.ROOT = ROOT
            modules[name] = module
            return module

        load('tio.world_completion', CANDIDATE / 'tio/world_completion.py')
        load('tio.map_generation', CANDIDATE / 'tio/map_generation.py')
        for name in ('tio.cities', 'tio.locations', 'tio.combat',
                     'tio.reward_policy', 'tio.battle_rewards', 'tio.team_scene',
                     'server.world_runtime', 'server.battle_journal'):
            load(name, RUNTIME / Path(*name.split('.')).with_suffix('.py'))
        load('server.wager_arena', CANDIDATE / 'server/wager_arena.py')
        load('server.team_arena', RUNTIME / 'server/team_arena.py')
        # Checkpoint registry must resolve the overlay classes, including when
        # another test populated its process-wide cache before this module.
        from tio.battle_snapshot import registry
        registry.cache_clear()
        try:
            yield modules
        finally:
            registry.cache_clear()


class DetroitMapTests(unittest.TestCase):
    def setUp(self):
        self.modules = self.enterContext(runtime_under_test())
        self.world = self.modules['tio.world_completion']
        self.maps = self.modules['tio.map_generation']

    def assert_original(self, generated, extent, deployment):
        pinned = ORIGINAL_MAPS[extent]
        self.assertEqual(hashlib.sha256(encode_battle_ground(generated.arena.ground)).hexdigest(),
                         pinned['sha256'])
        self.assertEqual(generated.layout, dict(width=extent, height=extent,
            ground_id=2, ground_brush_id=6,
            player_spawns=pinned['player_spawns'][:deployment],
            bot_spawns=pinned['bot_spawns'][:deployment],
            objects=[dict(file=pinned['file'], x=0, y=0)]))
        self.assertEqual((generated.profile, generated.variant, generated.surroundings),
                         ('detroit', 'original_whole_map', None))

    def test_ordinary_and_size_one_preserve_exact_whole_map_and_wire(self):
        for mode, extent in ((0, 38), (7, 38), (1, 50), (4, 50)):
            for size in (1, 6):
                with self.subTest(mode=mode, deployment=size):
                    original = self.world.generate_world_map(
                        18, seed=23, mode=mode, deployment_size=size, map_size=None)
                    self.assert_original(original, extent, size)
                    for map_size in (None, 1):
                        result = self.world.generate_world_map(
                            18, seed=23, mode=mode, deployment_size=size,
                            map_size=map_size)
                        self.assertEqual(result, original)
                        self.assertEqual(encode_battle_ground(result.arena.ground),
                                         encode_battle_ground(original.arena.ground))
                        self.assertEqual((result.arena.ground.width,
                                          result.arena.ground.height), (extent, extent))
                        self.assertEqual(self.maps.generate_map(
                            'detroit', seed=23, mode=mode, deployment_size=size,
                            map_size=map_size), result)

    def test_selected_sizes_preserve_intact_art_collision_and_connected_deployment(self):
        expected = {38: (38, 47, 57, 66), 50: (50, 62, 75, 87)}
        for mode, base in ((0, 38), (7, 38), (1, 50), (4, 50)):
            original = self.world.generate_world_map(
                18, seed=41, mode=mode, deployment_size=6, map_size=None)
            self.assert_original(original, base, 6)
            for map_size, extent in enumerate(expected[base], 1):
                with self.subTest(mode=mode, map_size=map_size):
                    result = self.world.generate_world_map(
                        18, seed=41, mode=mode, deployment_size=6, map_size=map_size)
                    arena = result.arena
                    ground = decode_battle_ground(encode_battle_ground(arena.ground))
                    offset = (extent-base)//2
                    shift = lambda p: (p[0]+offset, p[1]+offset)
                    self.assertEqual((ground.width, ground.height), (extent, extent))
                    self.assertEqual(set(ground.first_layer), {6})
                    self.assertEqual(ground.second_layer, bytes(extent*extent))
                    self.assertEqual(result.layout['objects'], [dict(
                        file=original.layout['objects'][0]['file'], x=offset, y=offset)])
                    self.assertEqual(tuple((e.name, e.unknown_u8_01, e.unknown_u8_02)
                                           for e in ground.entries), tuple(
                        (e.name, e.unknown_u8_01+offset, e.unknown_u8_02+offset)
                        for e in original.arena.ground.entries))
                    self.assertEqual(arena.blocked, frozenset(map(shift, original.arena.blocked)))
                    self.assertEqual(arena.transparent_obstacles,
                                     frozenset(map(shift, original.arena.transparent_obstacles)))
                    self.assertEqual(arena.containers, tuple(map(shift, original.arena.containers)))
                    self.assertEqual(arena.doors, tuple((x+offset, y+offset, opened)
                        for x, y, opened in original.arena.doors))
                    spawns = arena.player_spawns+arena.bot_spawns
                    self.assertEqual(len(set(spawns)), 12)
                    self.assertTrue(all(0 <= x < extent and 0 <= y < extent
                                        and (x, y) not in arena.blocked for x, y in spawns))
                    self.assertTrue(set(spawns).isdisjoint({(x, y) for x, y, _ in arena.doors}))
                    reached = self.maps.reachable_cells(arena)
                    self.assertTrue(self.maps.connected(arena, reached))
                    # The expanded brush canvas must connect to the playable
                    # original interior, rather than merely surround sealed art.
                    self.assertTrue(set(map(shift, original.arena.player_spawns+
                                             original.arena.bot_spawns)) <= reached)
                    if extent > base:
                        self.assertTrue(any(x < offset or y < offset or
                            x >= offset+base or y >= offset+base for x, y in reached))
                    self.assertEqual(self.maps.generate_map('detroit', seed=41,
                        mode=mode, deployment_size=6, map_size=map_size), result)

    def test_malformed_sizes_and_unsupported_deployment_reject_before_generation(self):
        for value in (False, True, 0, 5, -1, 1.0, '2', [], {}):
            with self.subTest(map_size=value):
                for generate in (lambda: self.world.generate_world_map(18, map_size=value),
                                 lambda: self.maps.generate_map('detroit', map_size=value)):
                    with self.assertRaises(ValueError):
                        generate()
        for kwargs in (dict(deployment_size=7), dict(deployment_size=True), dict(mode=True),
                       dict(mode=21), dict(seed=-1), dict(seed=True), dict(seed=2**64)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.world.generate_world_map(18, map_size=2, **kwargs)
        for town in (4, 7, 19):
            with self.subTest(town=town), self.assertRaises(ValueError):
                self.world.generate_world_map(town, map_size=2)


class DetroitSavedAccountWagerTests(unittest.TestCase):
    send = fixture.SharedTeamTests.send

    def setUp(self):
        fixture.SharedTeamTests.setUp(self)
        self.modules = self.enterContext(runtime_under_test())
        self.hub = self.modules['server.team_arena'].TeamArena(clock=lambda: self.now)
        self.wall = 1_800_000_000
        self.hub.journal = self.modules['server.battle_journal'].BattleJournal(
            self.hub, self.path, wall=lambda: self.wall)
        locations = self.modules['tio.locations'].LocationStore(self.path)
        for session in self.sessions:
            Accounts(self.path).create(session.account, 'DetroitTest0123', character=session.account)
            identity, raw, _ = OwnedPetStore(self.path).list(session.account)[0]
            pet = decode_pet_info(raw, human_equipment=True)
            raw = encode_pet_info(replace(pet, fields={**pet.fields, '0x8c4aef': 4}))
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                           (raw, session.account, identity))
                locations._save(db, session.account, 18, *self.modules['tio.locations'].center(18))
            session.locations = locations

    def balances(self, count=2):
        return tuple(WalletStore(self.path).ensure(s.account).credits for s in self.sessions[:count])

    def escrow(self, match):
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT status,pot FROM wager_matches WHERE match_id=?', (match,)).fetchone()

    def launch(self, mode, map_size, count=2):
        balances = self.balances(count)
        replies = self.send(0, encode_create_request(ArenaCreateRequest(
            mode, map_size, count, 2, 40, 1, 1, 0, 100)))
        self.assertTrue(any(p[0] == 0x6c for p in replies), replies)
        settings = decode_battle_settings_body(next(p[1:] for p in replies if p[0] == 0x6c))
        self.assertEqual((settings.mode, settings.map_size, settings.stake), (mode, map_size, 100))
        owner = self.hub.identities[self.sessions[0]]
        room = self.hub.wager_lobbies.room(owner)
        for index in range(1, count):
            replies = self.send(index, encode_join(room.identity))
            self.assertTrue(any(p[0] == 0x6c for p in replies), replies)
        self.assertEqual(self.balances(count), balances)
        for index in range(1, count):
            self.send(index, b'\x2c\x01')
        self.send(0, b'\x2e')
        self.assertEqual(self.escrow(room.match_id), ('held', 100*count))
        self.assertEqual(self.balances(count), tuple(b-100 for b in balances))
        self.send(0, b'\x2e')
        self.assertEqual(self.balances(count), tuple(b-100 for b in balances))
        self.now += 4.99
        self.hub.tick()
        self.assertFalse(self.hub.battles)
        self.now += .02
        self.hub.tick()
        owners = tuple(self.hub.identities[s] for s in self.sessions[:count])
        self.assertTrue(all(o in self.hub.battles for o in owners))
        battle = self.hub.battles[owners[0]]
        self.assertTrue(all(self.hub.battles[o] is battle for o in owners))
        self.assertFalse(battle['bots'])
        self.assertEqual(self.escrow(room.match_id), ('loading', 100*count))
        for index in range(count):
            self.send(index, b'\x36')
        self.hub.tick()
        self.assertEqual(self.escrow(room.match_id), ('active', 100*count))
        self.assertTrue(battle['field'].combat.wager)
        self.launch_balances = balances
        return owners, battle

    def test_four_saved_accounts_share_large_free_for_all_scene_and_whole_pot(self):
        owners, battle = self.launch(0, 4, count=4)
        field = battle['field']
        self.assertEqual((field.width, field.height), (66, 66))
        self.assertEqual(field.teams, dict(zip(owners, range(4))))
        self.assertEqual(len(field.living_sides()), 4)
        self.assertEqual({a.owner_id for a in field._actors.values()}, set(owners))
        positions = {(a.x, a.y) for a in field._actors.values()}
        self.assertEqual(len(positions), 4)
        self.assertTrue(positions.isdisjoint(field.blocked))
        before = [OwnedPetStore(self.path).list(s.account)[0][1] for s in self.sessions]
        for index in (1, 2, 3):
            self.send(index, b'\x2a\x01')
        self.hub.tick()
        self.assertTrue(battle['finished'])
        self.assertEqual(self.balances(4), (10300, 9900, 9900, 9900))
        self.hub.finish(battle)
        self.assertEqual(self.balances(4), (10300, 9900, 9900, 9900))
        self.assertEqual([OwnedPetStore(self.path).list(s.account)[0][1]
                          for s in self.sessions], before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT sum(amount),count(*) FROM wager_receipts').fetchone(), (400, 4))

    def test_native_two_account_size_selection_reserves_starts_and_pays_once(self):
        # Both native ordinary wager modes use their original Detroit fragment.
        for mode, sizes in ((0, (1, 2, 3, 4)), (1, (1, 4))):
            for map_size in sizes:
                with self.subTest(mode=mode, map_size=map_size):
                    owners, battle = self.launch(mode, map_size)
                    settled_balances = (self.launch_balances[0]+100, self.launch_balances[1]-100)
                    expected = ((38, 47, 57, 66) if mode == 0 else (50, 62, 75, 87))[map_size-1]
                    ground = decode_battle_ground(battle['ground'])
                    self.assertEqual((ground.width, ground.height), (expected, expected))
                    self.assertEqual(set(ground.first_layer), {6})
                    self.assertEqual(battle['field'].scene_metadata['town_id'], 18)
                    self.assertEqual({a.owner_id for a in battle['field']._actors.values()}, set(owners))
                    before = [OwnedPetStore(self.path).list(s.account)[0][1] for s in self.sessions[:2]]
                    self.send(1, b'\x2a\x01')
                    self.hub.tick()
                    self.assertTrue(battle['finished'])
                    self.assertEqual(self.balances(), settled_balances)
                    self.hub.finish(battle)
                    self.hub.finish(battle)
                    self.assertEqual(self.balances(), settled_balances)
                    self.assertEqual(self.escrow(battle['match_id']), ('settled', 200))
                    self.assertEqual([OwnedPetStore(self.path).list(s.account)[0][1]
                                      for s in self.sessions[:2]], before)
                    with closing(sqlite3.connect(self.path)) as db:
                        self.assertEqual(db.execute('SELECT sum(amount),count(*) FROM wager_receipts '
                            'WHERE match_id=?', (battle['match_id'],)).fetchone(), (200, 2))
                        self.assertEqual(db.execute('SELECT count(*) FROM wager_leases').fetchone()[0], 0)
                    for index in (0, 1):
                        if owners[index] in self.hub.results:
                            self.send(index, b'\x2a\x01')

    def test_successful_native_attack_keeps_saved_skills_xp_and_rank_after_retry(self):
        owners, battle = self.launch(0, 4)
        field = battle['field']
        attacker = field.actor_ids(owners[0])[0]
        victim = field.actor_ids(owners[1])[0]
        field.blocked = frozenset()
        field.doors.states = {}
        field._actors[attacker] = replace(field.actor(attacker), x=5, y=5, sight_radius=30)
        field._actors[victim] = replace(field.actor(victim), x=5, y=6, sight_radius=30)
        for view in battle['views'].values():
            view.refresh()
        # Retain a serializable RNG for real journal checkpoints.
        field.combat.rng.seed(1)
        before = [OwnedPetStore(self.path).list(s.account)[0][1] for s in self.sessions[:2]]
        with patch('tio.weapon_proficiency.ProficiencyRules.train',
                   side_effect=AssertionError('Wager trained a weapon skill')):
            replies = self.send(0, encode_attack_request(AttackRequest(attacker, 5, 6)))
        self.assertTrue(any(p[0] == 0x4b for p in replies), replies)
        self.assertLess(field.actor(victim).health, field.actor(victim).max_health)
        self.send(1, b'\x2a\x01')
        self.hub.tick()
        self.hub.finish(battle)
        self.hub.finish(battle)
        self.assertEqual(self.balances(), (10100, 9900))
        for session, raw in zip(self.sessions[:2], before):
            after = OwnedPetStore(self.path).list(session.account)[0][1]
            self.assertEqual(skill_signature(after, True), skill_signature(raw, True))
            old = decode_pet_info(raw, human_equipment=True).fields
            saved = decode_pet_info(after, human_equipment=True).fields
            self.assertEqual(tuple(saved[k] for k in ('0x8c4b05', '0x8c4bbc', '0x8c4bd0')),
                             tuple(old[k] for k in ('0x8c4b05', '0x8c4bbc', '0x8c4bd0')))
        with closing(sqlite3.connect(self.path)) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('battle_experience', 'battle_rank_rewards', 'team_ranked_matches',
                          'ranked_matches', 'player_battle_statistics', 'reward_pairs', 'world_city_matches'):
                if table in tables:
                    self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0, table)
            self.assertEqual(db.execute('SELECT sum(amount),count(*) FROM wager_receipts').fetchone(), (200, 2))

    def test_malformed_native_map_size_has_no_lobby_escrow_or_wallet_change(self):
        for map_size in (0, 5, 255):
            with self.subTest(map_size=map_size):
                replies = self.send(0, encode_create_request(ArenaCreateRequest(
                    0, map_size, 2, 2, 40, 1, 1, 0, 100)))
                self.assertTrue(any(p[0] == 0xf0 for p in replies), replies)
                self.assertFalse(self.hub.wager_lobbies.rooms)
                self.assertFalse(self.hub.battles)
                self.assertEqual(self.balances(), (10000, 10000))
                with closing(sqlite3.connect(self.path)) as db:
                    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    for table in ('wager_matches', 'wager_members', 'wager_leases', 'wager_receipts'):
                        if table in tables:
                            self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0], 0)

    def test_invalid_wager_scale_rejects_native_admission_without_database_mutation(self):
        wagers_path = ROOT / 'config/wagers.json'
        original_read = Path.read_text
        policy = json.loads(original_read(wagers_path))
        for scale in ([5, 0], [3, 4], [4, 1]):
            with self.subTest(scale=scale):
                malformed = {**policy, 'map_scales': {**policy['map_scales'], '2': scale}}
                def read(path, *args, **kwargs):
                    return json.dumps(malformed) if path == wagers_path else original_read(path, *args, **kwargs)
                before = self.path.read_bytes()
                with patch.object(Path, 'read_text', read):
                    replies = self.send(0, encode_create_request(ArenaCreateRequest(
                        0, 2, 2, 2, 40, 1, 1, 0, 100)))
                self.assertTrue(any(p[0] == 0xf0 for p in replies), replies)
                self.assertFalse(self.hub.wager_lobbies.rooms)
                self.assertFalse(self.hub.battles)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.balances(), (10000, 10000))


if __name__ == '__main__':
    unittest.main()
