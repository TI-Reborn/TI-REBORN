"""Main native Team/Wall wager rows include live occupancy and countdown state."""
from contextlib import closing
import sqlite3
import unittest

import test_shared_team_arena as fixture
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.item_list import encode_item_list
from tio.protocol.wagers import decode_room_list,encode_join
from tio.wallets import WalletStore


class NativeWagerCaptionTests(unittest.TestCase):
    setUp=fixture.SharedTeamTests.setUp
    send=fixture.SharedTeamTests.send

    def owner(self,index):
        return self.hub.identity(self.sessions[index])

    def create(self,index=0,*,mode=1,count=2,stake=100):
        replies=self.send(index,encode_create_request(ArenaCreateRequest(mode,2,count,2,40,1,1,0,stake)))
        self.assertTrue(any(p[:1]==b'\x6c' for p in replies))
        return self.hub.wager_lobbies.room(self.owner(index))

    def listing(self,index=3):
        return decode_room_list(next(p for p in self.send(index,b'\xba\x01') if p[:2]==b'\xc8\x2c'))

    def test_free_team_caption_uses_authoritative_counts_and_preserves_settings(self):
        room=self.create()
        row=self.listing()[0]
        self.assertEqual(row.creator_name,'alice · свободно 1/2'.encode('cp1251'))
        self.assertEqual((row.identity,row.creator_level,row.mode,row.capacity,row.members,row.status,row.soldiers,row.map_size,row.level_delta,row.stake),
                         (room.identity,room.creator_level,1,2,1,0,1,2,0,100))
        self.assertEqual(WalletStore(self.path).ensure('alice').credits,10_000)
        self.assertIsNone(room.starts_at)

    def test_full_team_remains_visible_and_stale_third_join_is_rejected(self):
        room=self.create();self.send(1,encode_join(room.identity))
        row=self.listing()[0]
        self.assertEqual((row.capacity,row.members,row.status),(2,2,0))
        self.assertEqual(row.creator_name,'alice · занято 2/2'.encode('cp1251'))
        self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(2,encode_join(room.identity))))
        self.assertEqual(room.members,[self.owner(0),self.owner(1)])

    def test_team_countdown_is_visible_starting_and_cancel_reopens_without_roster_changes(self):
        before={s.account:OwnedPetStore(self.path).list(s.account) for s in self.sessions}
        room=self.create();self.send(1,encode_join(room.identity));self.send(1,b'\x2c\1');self.send(0,b'\x2e')
        self.assertIsNotNone(room.starts_at)
        row=self.listing()[0]
        self.assertEqual((row.members,row.capacity,row.status),(2,2,2))
        self.assertTrue(row.creator_name.endswith(' · занято 2/2'.encode('cp1251')))
        self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(2,encode_join(room.identity))))
        self.send(1,b'\x2c\0')
        self.assertIsNone(room.starts_at)
        self.assertEqual(self.listing()[0].status,0)
        self.send(1,b'\x2a\1')
        self.assertTrue(self.listing()[0].creator_name.endswith(' · свободно 1/2'.encode('cp1251')))
        self.assertEqual({s.account:OwnedPetStore(self.path).list(s.account) for s in self.sessions},before)
        self.assertEqual([WalletStore(self.path).ensure(s.account).credits for s in self.sessions],[10_000]*4)

    def test_wall_caption_uses_real_eight_player_capacity(self):
        room=self.create(mode=4,count=8)
        self.send(1,encode_join(room.identity))
        row=self.listing()[0]
        self.assertEqual((row.mode,row.capacity,row.members,row.status),(4,8,2,0))
        self.assertTrue(row.creator_name.endswith(' · свободно 2/8'.encode('cp1251')))

    def test_eight_real_wall_members_and_countdown_stay_visible(self):
        from tio.arena_service import ArenaService
        from tio.survival_service import SurvivalService
        from wallet_fixture import fund_wallet
        pet=OwnedPetStore(self.path).list('alice')[0][1]
        for name in ('erin','frank','grace','helen'):
            s=fixture.Session();s.account=name;s.database=self.path;s.probe_character_id=1
            s.probe_character_name=name.encode();s.locations=None;s.arena=ArenaService();s.survival=SurvivalService()
            fund_wallet(self.path,name,credits=10_000,gold=10_000)
            OwnedPetStore(self.path).ensure(name,pet,encode_item_list(1,()),human=True)
            self.sessions.append(s)
        room=self.create(mode=4,count=8)
        for index in range(1,8):self.send(index,encode_join(room.identity))
        for index in range(1,8):self.send(index,b'\x2c\1')
        self.assertEqual(len(set(room.accounts.values())),8)
        row=self.listing(0)[0]
        self.assertTrue(row.creator_name.endswith(' · занято 8/8'.encode('cp1251')))
        self.send(0,b'\x2e')
        row=self.listing(0)[0]
        self.assertEqual((row.members,row.capacity,row.status),(8,8,2))
        self.assertTrue(row.creator_name.endswith(' · занято 8/8'.encode('cp1251')))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status,pot FROM wager_matches').fetchone(),('held',800))

    def test_survival_wager_caption_and_countdown_filter_are_unchanged(self):
        room=self.create(mode=0)
        self.assertEqual(self.listing()[0].creator_name,b'alice')
        self.send(1,encode_join(room.identity));self.send(1,b'\x2c\1');self.send(0,b'\x2e')
        self.assertIsNotNone(room.starts_at)
        self.assertEqual(self.listing(),())

    def test_long_cp1251_captain_name_preserves_complete_status_suffix(self):
        self.sessions[0].probe_character_name='Я'.encode('cp1251')*255
        self.create()
        name=self.listing()[0].creator_name
        self.assertEqual(len(name),255)
        self.assertTrue(name.endswith(' · свободно 1/2'.encode('cp1251')))
        self.assertTrue(name.decode('cp1251').startswith('Я'))

    def test_other_matchmaking_pool_stays_filtered(self):
        self.create()
        class Locations:
            def current(self,account):return 2
        self.sessions[3].locations=Locations()
        self.assertEqual(self.listing(),())


if __name__=='__main__':
    unittest.main()
