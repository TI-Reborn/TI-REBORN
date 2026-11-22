"""Idle city heartbeats must not reload unchanged native portraits."""
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class AvatarSyncTests(unittest.TestCase):
    def test_unchanged_heartbeats_do_not_resend_or_query_portraits(self):
        from server.avatar_service import sync
        class Session:
            database = 'unused.db'
            account = 'alice'
            owned_pet_probe = True
            router = SimpleNamespace(team_arena=SimpleNamespace(lock=threading.RLock()))
        session = Session()
        presence = SimpleNamespace(lock=threading.RLock(), messages={session: []})
        with patch('server.economy_runtime.city_idle', return_value=True), \
                patch('server.avatar_service.snapshot', return_value=b'\xfc\x01\0\0') as read:
            for _ in range(10):
                sync(presence, session)
        self.assertEqual(presence.messages[session], [b'\xfc\x01\0\0'])
        self.assertEqual(read.call_count, 1)

    def test_reserve_and_ready_profiles_keep_each_owners_saved_avatar(self):
        from test_avatars import AvatarTests
        from tio import avatars
        from tio.protocol.pet_info import decode_pet_info
        from tio.squad import SquadStore

        fixture = AvatarTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        squad = SquadStore(fixture.path)
        avatars.assign(fixture.path, 'alice', 1, 10007, allowed=True)
        avatars.assign(fixture.path, 'bob', 1, 10003, allowed=True)
        for slot in (0, 1, 0, 1):
            for account, avatar in (('alice', 10007), ('bob', 10003)):
                raw, = squad.assign(account, 1, slot)
                before = fixture.store.list(account)
                projected = avatars.project_city_pet(fixture.path, account, raw)
                pet = decode_pet_info(projected, human_equipment=True)
                original = decode_pet_info(raw, human_equipment=True)
                self.assertEqual(pet.fields, {**original.fields, '0x8c4ba9': avatar})
                self.assertEqual(pet.fields['0x8c44a6'], slot)
                self.assertEqual(fixture.store.list(account), before)
                self.assertEqual(original.fields['0x8c4ba9'], 0)
                self.assertEqual(avatars.project_city_pet(
                    fixture.path, account, projected), projected)

    def test_unselected_and_unowned_profiles_do_not_gain_foreign_avatar(self):
        from test_avatars import AvatarTests
        from tio import avatars

        fixture = AvatarTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        raw = fixture.store.list('alice')[0][1]
        self.assertEqual(avatars.project_city_pet(fixture.path, 'alice', raw), raw)
        avatars.assign(fixture.path, 'alice', 1, 10007, allowed=True)
        self.assertEqual(avatars.project_city_pet(fixture.path, 'bob', raw), raw)
        self.assertEqual(avatars.project_city_pet(fixture.path, 'unknown', raw), raw)
