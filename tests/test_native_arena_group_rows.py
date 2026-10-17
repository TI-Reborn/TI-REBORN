"""BA02 layout read by actual native Players/Soldiers columns and status names."""
import unittest

import test_shared_team_arena as fixture
from tio.protocol.arena import ArenaCreateRequest,encode_create_request,decode_room_list
from tio.protocol.wagers import encode_join


class NativeArenaGroupRowsTests(unittest.TestCase):
    setUp=fixture.SharedTeamTests.setUp
    send=fixture.SharedTeamTests.send
    create=fixture.SharedTeamTests.create
    add_selected=fixture.SharedTeamTests.add_selected

    def owner(self,index):return self.hub.identity(self.sessions[index])

    def listing(self,index=3):
        return decode_room_list(next(p for p in self.send(index,b'\xba\x01') if p[:2]==b'\xba\x02'))

    def slots(self,row):
        return row.unknown_u8_1d,row.unknown_u8_1c,row.unknown_u8_18,row.unknown_u8_1e

    def wager(self,mode=1,count=2):
        self.send(0,encode_create_request(ArenaCreateRequest(mode,2,count,2,40,1,1,0,100)))
        return self.hub.wager_lobbies.room(self.owner(0))

    def test_ordinary_team_and_wall_have_human_capacity_and_one_fighter(self):
        first=self.create(0,1);second=self.create(1,4)
        rows=self.listing()
        self.assertEqual([(r.unknown_u32_00,r.category,self.slots(r)) for r in rows],
                         [(first.identity,1,(1,2,1,0)),(second.identity,4,(1,4,1,0))])
        self.assertEqual(rows[0].name,'alice · свободно 1/2'.encode('cp1251'))
        self.assertEqual(rows[1].name,'bob · свободно 1/4'.encode('cp1251'))
        self.assertTrue(all((r.unknown_u8_1a,r.unknown_u8_1b)==(1,3) for r in rows))

    def test_soldier_column_counts_fighters_independently_of_players(self):
        self.add_selected(0,3)
        replies=self.send(0,encode_create_request(ArenaCreateRequest(1,0,4,2,80,3,3,0,0)))
        self.assertTrue(any(p[:1]==b'\x6c' for p in replies))
        self.assertEqual(self.slots(self.listing()[0]),(1,2,3,0))

    def test_full_team_stays_visible_with_occupied_caption(self):
        room=self.create(0);self.send(1,encode_join(room.identity))
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(2,2,1,0))
        self.assertEqual(row.name,'alice · занято 2/2'.encode('cp1251'))

    def test_search_stays_visible_with_starting_status_and_reopens_on_cancel(self):
        room=self.create(0);self.send(0,b'\x2e')
        row=self.listing()[0]
        self.assertTrue(room.searching)
        self.assertEqual(self.slots(row),(1,2,1,2))
        self.assertEqual(row.name,'alice · поиск 1/2'.encode('cp1251'))
        self.send(0,b'\x2c\0')
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(1,2,1,0))
        self.assertTrue(row.name.endswith(' · свободно 1/2'.encode('cp1251')))

    def test_leaving_a_full_team_releases_the_displayed_slot(self):
        room=self.create(0);self.send(1,encode_join(room.identity));self.send(1,b'\x2a\1')
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(1,2,1,0))
        self.assertTrue(row.name.endswith(' · свободно 1/2'.encode('cp1251')))

    def test_wager_team_has_correct_players_soldiers_and_capacity(self):
        room=self.wager();self.send(1,encode_join(room.identity))
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(2,2,1,0))
        self.assertEqual(row.name,'alice · занято 2/2'.encode('cp1251'))
        self.assertEqual((row.unknown_u8_1a,row.unknown_u8_1b,row.unknown_u8_20),(1,1,2))

    def test_wager_wall_uses_eight_human_slots_and_one_fighter(self):
        room=self.wager(4,8);self.send(1,encode_join(room.identity))
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(2,8,1,0))
        self.assertTrue(row.name.endswith(' · свободно 2/8'.encode('cp1251')))

    def test_wager_countdown_is_visible_starting_and_cancel_resets_status(self):
        room=self.wager();self.send(1,encode_join(room.identity));self.send(1,b'\x2c\1');self.send(0,b'\x2e')
        row=self.listing()[0]
        self.assertIsNotNone(room.starts_at)
        self.assertEqual(self.slots(row),(2,2,1,2))
        self.assertTrue(row.name.endswith(' · занято 2/2'.encode('cp1251')))
        self.send(1,b'\x2c\0')
        self.assertEqual(self.slots(self.listing()[0]),(2,2,1,0))

    def test_other_wager_mode_retains_previous_fields_and_countdown_filter(self):
        room=self.wager(0)
        row=self.listing()[0]
        self.assertEqual(self.slots(row),(0,1,1,0))
        self.assertEqual(row.name,b'alice')
        self.send(1,encode_join(room.identity));self.send(1,b'\x2c\1');self.send(0,b'\x2e')
        self.assertEqual(self.listing(),())

    def test_cp1251_name_truncation_keeps_exact_complete_status(self):
        self.sessions[0].probe_character_name='Я'.encode('cp1251')*255
        self.create(0)
        name=self.listing()[0].name
        self.assertEqual(len(name),255)
        self.assertTrue(name.endswith(' · свободно 1/2'.encode('cp1251')))

    def test_other_pool_is_hidden_for_waiting_and_searching_rooms(self):
        self.create(0);self.send(0,b'\x2e')
        class Locations:
            def current(self,account):return 2
        self.sessions[3].locations=Locations()
        self.assertEqual(self.listing(),())


if __name__=='__main__':unittest.main()
