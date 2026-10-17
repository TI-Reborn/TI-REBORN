"""Shared native main-table lobbies, account admission and unchanged saves."""
from contextlib import closing
from dataclasses import replace
import sqlite3
import unittest

import test_shared_team_arena as fixture
from tio.owned_pets import OwnedPetStore
from tio.protocol.arena import decode_battle_settings_body,decode_room_list as decode_groups
from tio.protocol.battle_members import decode_battle_members
from tio.protocol.item_list import encode_item_list
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.wagers import decode_room_list,encode_join,encode_kick


class NativeTeamLobbyListTests(unittest.TestCase):
    setUp=fixture.SharedTeamTests.setUp
    send=fixture.SharedTeamTests.send
    create=fixture.SharedTeamTests.create
    add_selected=fixture.SharedTeamTests.add_selected

    def owner(self,index):return self.hub.identity(self.sessions[index])

    def listed(self,index=3):
        packets=self.send(index,b'\xba\x01')
        return decode_room_list(next(p for p in packets if p[:2]==b'\xc8\x2c'))

    def update_pet(self,index,identity=1,**changes):
        account=self.sessions[index].account
        _,raw,_=next(r for r in OwnedPetStore(self.path).list(account) if r[0]==identity)
        pet=decode_pet_info(raw,human_equipment=True)
        packet=encode_pet_info(replace(pet,fields={**pet.fields,**changes}))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,account,identity))

    def add_reserve(self,index,*,level=1):
        account=self.sessions[index].account
        raw=OwnedPetStore(self.path).list(account)[0][1]
        pet=decode_pet_info(raw,human_equipment=True)
        packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c43eb':2,'0x8c44a6':0,'0x8c4aef':level}))
        OwnedPetStore(self.path).ensure(account,packet,encode_item_list(2,()),human=True)

    def error(self,packets):return next(p for p in packets if p[:1]==b'\xf0')[13:-2].decode('utf-16-le')

    def test_main_table_contains_both_modes_with_exact_starter_bounds_and_slots(self):
        team=self.create(0,1);wall=self.create(1,4)
        records=self.listed()
        self.assertEqual([(r.identity,r.mode,r.capacity,r.members,r.status,r.stake) for r in records],
                         [(team.identity,1,2,1,0,0),(wall.identity,4,4,1,0,0)])
        self.assertTrue(all((r.creator_level-r.level_delta,r.creator_level+r.level_delta)==(1,3) for r in records))
        self.assertIn('свободно 1/2',records[0].creator_name.decode('cp1251'))
        groups=decode_groups(next(p for p in self.send(3,b'\xba\x01') if p[:2]==b'\xba\x02'))
        self.assertTrue(all((r.unknown_u8_1a,r.unknown_u8_1b)==(1,3) for r in groups))

    def test_main_join_opens_real_shared_room_and_updates_creator(self):
        room=self.create(0)
        packets=self.send(1,encode_join(room.identity))
        settings=decode_battle_settings_body(next(p[1:] for p in packets if p[:1]==b'\x6c'))
        self.assertEqual(settings.unknown_bytes[:3],bytes((1,3,1)))
        self.assertIs(self.hub.lobbies.room(self.owner(1)),room)
        members=decode_battle_members(next(p for p in packets if p[:1]==b'\x25'))[2]
        self.assertEqual({r.name for r in members},{b'alice',b'bob'})
        self.assertTrue(any(p[:1]==b'\x25' for p in self.hub.queues[self.owner(0)]))

    def test_full_lobby_is_visible_occupied_and_stale_join_is_rejected(self):
        room=self.create(0);self.send(1,encode_join(room.identity))
        record=self.listed()[0]
        self.assertEqual((record.capacity,record.members,record.status),(2,2,0))
        self.assertIn('занято 2/2',record.creator_name.decode('cp1251'))
        self.assertIn('заполнена',self.error(self.send(2,encode_join(room.identity))))
        self.assertIsNone(self.hub.lobbies.room(self.owner(2)))
        self.assertNotIn(self.owner(2),self.hub.tickets)

    def test_searching_lobby_stays_visible_and_ready_cancel_reopens_it(self):
        room=self.create(0);self.send(0,b'\x2e')
        record=self.listed()[0]
        self.assertEqual((record.identity,record.status,record.members),(room.identity,2,1))
        self.assertIn('поиск 1/2',record.creator_name.decode('cp1251'))
        self.assertIn('ищет бой',self.error(self.send(1,encode_join(room.identity))))
        self.send(0,b'\x2c\0')
        self.assertEqual(self.listed()[0].status,0)
        self.assertIn('свободно',self.listed()[0].creator_name.decode('cp1251'))
        self.assertTrue(any(p[:1]==b'\x6c' for p in self.send(1,encode_join(room.identity))))

    def test_reserve_join_and_four_real_accounts_start_without_changing_saved_squads(self):
        self.add_reserve(1);self.update_pet(1,**{'0x8c4aef':4})
        before=OwnedPetStore(self.path).list(self.sessions[1].account)
        first=self.create(0);second=self.create(2)
        self.send(1,encode_join(first.identity));self.send(3,encode_join(second.identity))
        ticket=self.hub.tickets[self.owner(1)]
        self.assertEqual((ticket.actors,ticket.levels),((2,),(1,)))
        self.assertEqual(OwnedPetStore(self.path).list(self.sessions[1].account),before)
        packets=tuple(self.hub.queues[self.owner(0)])
        members=decode_battle_members(next(p for p in reversed(packets) if p[:1]==b'\x25'))[2]
        reserve_member=next(m for m in members if m.name==b'bob')
        self.assertEqual(reserve_member.group1[0].level,1)
        for index in (1,3):self.send(index,b'\x2c\1')
        for index in (0,2):self.send(index,b'\x2e')
        battle=self.hub.battles[self.owner(1)]
        self.assertEqual(len(battle['humans']),4);self.assertFalse(battle['bots'])
        actor=battle['field'].actor_ids(self.owner(1))[0]
        self.assertEqual(battle['field'].combat.storage_ids[actor],2)
        self.assertEqual(OwnedPetStore(self.path).list(self.sessions[1].account),before)
        self.assertFalse(self.hub.lobbies.rooms);self.assertFalse(self.hub.lobby_auto_rosters)

    def test_no_starter_fighters_rejects_join_with_required_range(self):
        room=self.create(0);self.update_pet(1,**{'0x8c4aef':4})
        self.assertIn('уровней 1–3',self.error(self.send(1,encode_join(room.identity))))
        self.assertIsNone(self.hub.lobbies.room(self.owner(1)))
        self.assertEqual(room.members,[self.owner(0)])

    def test_healthy_reserve_is_used_when_selected_fighter_is_wounded(self):
        room=self.create(0);self.add_reserve(1);self.update_pet(1,**{'0x8c4ab1':1})
        self.send(1,encode_join(room.identity))
        self.assertEqual(self.hub.tickets[self.owner(1)].actors,(2,))

    def test_team_requires_requested_number_of_eligible_owned_fighters(self):
        self.add_selected(0,3);self.send(0,b'\xba\3\1\3')
        room=self.hub.lobbies.room(self.owner(0))
        self.assertIn('3 полностью здоровых',self.error(self.send(1,encode_join(room.identity))))
        self.assertIsNone(self.hub.lobbies.room(self.owner(1)))

    def test_frozen_auto_roster_is_revalidated_before_ready_search(self):
        room=self.create(0);self.add_reserve(1);self.update_pet(1,**{'0x8c4aef':4})
        self.send(1,encode_join(room.identity));self.send(1,b'\x2c\1')
        self.update_pet(1,2,**{'0x8c4aef':4})
        self.assertIn('уровней 1–3',self.error(self.send(0,b'\x2e')))
        self.assertFalse(room.searching);self.assertFalse(self.hub.battles)

    def test_push_updates_on_create_fill_and_close_and_skips_identical_list(self):
        viewer=self.owner(3);self.hub.tick();self.hub.queues[viewer].clear()
        self.hub.tick();self.assertFalse(self.hub.queues[viewer])
        room=self.create(0);self.hub.tick()
        self.assertEqual(decode_room_list(self.hub.queues[viewer].pop())[0].members,1)
        self.send(1,encode_join(room.identity));self.hub.tick()
        self.assertEqual(decode_room_list(self.hub.queues[viewer].pop())[0].members,2)
        self.send(0,b'\x2a\1');self.hub.tick()
        self.assertEqual(decode_room_list(self.hub.queues[viewer].pop()),())

    def test_native_kick_requires_captain_and_releases_slot(self):
        room=self.create(0);self.send(1,encode_join(room.identity))
        self.assertIn('создатель',self.error(self.send(1,encode_kick(self.owner(0)))))
        self.send(0,encode_kick(self.owner(1)))
        self.assertIsNone(self.hub.lobbies.room(self.owner(1)))
        self.assertNotIn(self.owner(1),self.hub.lobby_auto_rosters)
        self.assertIn('свободно 1/2',self.listed()[0].creator_name.decode('cp1251'))

    def test_ordinary_and_wager_main_rows_keep_unique_ids_and_correct_join_route(self):
        from tio.protocol.arena import ArenaCreateRequest,encode_create_request
        ordinary=self.create(0)
        self.send(1,encode_create_request(ArenaCreateRequest(1,2,4,2,40,1,1,0,100)))
        wager=self.hub.wager_lobbies.room(self.owner(1))
        self.assertEqual({r.identity for r in self.listed()},{ordinary.identity,wager.identity})
        self.send(2,encode_join(wager.identity));self.send(3,encode_join(ordinary.identity))
        self.assertIs(self.hub.wager_lobbies.room(self.owner(2)),wager)
        self.assertIs(self.hub.lobbies.room(self.owner(3)),ordinary)

    def test_unknown_and_malformed_main_join_do_not_create_lobbies(self):
        for packet in (encode_join(1000),b'\x29',b'\x29\1\0\0\0\0'):
            self.assertTrue(any(p[:1]==b'\xf0' for p in self.send(0,packet)))
        self.assertFalse(self.hub.lobbies.rooms);self.assertFalse(self.hub.tickets)

    def test_other_matchmaking_pool_is_not_listed(self):
        self.create(0)
        class Locations:
            def current(self,account):return 2
        self.sessions[3].locations=Locations()
        self.assertEqual(self.listed(),())

    def test_wall_eight_real_accounts_join_two_lobbies_and_start_without_bots(self):
        from tio.arena_service import ArenaService
        from tio.survival_service import SurvivalService
        from wallet_fixture import fund_wallet
        for name in ('erin','frank','grace','helen'):
            session=fixture.Session();session.account=name;session.database=self.path
            session.probe_character_id=1;session.probe_character_name=name.encode()
            session.locations=None;session.arena=ArenaService();session.survival=SurvivalService()
            fund_wallet(self.path,name,credits=10_000,gold=10_000)
            pet=OwnedPetStore(self.path).list(self.sessions[0].account)[0][1]
            OwnedPetStore(self.path).ensure(name,pet,encode_item_list(1,()),human=True)
            self.sessions.append(session)
        first=self.create(0,4);second=self.create(4,4)
        for index in (1,2,3):self.send(index,encode_join(first.identity))
        for index in (5,6,7):self.send(index,encode_join(second.identity))
        for index in (1,2,3,5,6,7):self.send(index,b'\x2c\1')
        self.assertEqual((len(first.members),len(second.members)),(4,4))
        for index in (0,4):self.send(index,b'\x2e')
        battle=self.hub.battles[self.owner(0)]
        self.assertEqual(len(battle['humans']),8);self.assertFalse(battle['bots'])
        self.assertEqual(len(battle['field']._actors),8)
        self.assertTrue(all(self.hub.battles[self.owner(i)] is battle for i in range(8)))

    def test_long_captain_name_keeps_status_suffix_within_native_string_limit(self):
        self.sessions[0].probe_character_name=b'A'*255
        self.create(0)
        name=self.listed()[0].creator_name
        self.assertEqual(len(name),255)
        self.assertTrue(name.endswith(' · свободно 1/2'.encode('cp1251')))
