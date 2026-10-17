"""Boundaries for original Silver ABI; native execution has a separate tool.

These tests reject malformed client commands and distinguish authoritative
identities/economic influence from optional crest resources.
"""
import math
import struct
import unittest

from tio.protocol import alliances, assault, clan_ratings
from tio.protocol.binary import PacketError, Reader


class ClanWarfareProtocolTests(unittest.TestCase):
    def test_room_requests_require_exact_native_shape(self):
        requests=((0x1d,None),(0x1e,17),(0x1f,None),(0x20,29),
                  (0x21,0),(0x21,1),(0x22,None),(0x23,None))
        for op,value in requests:
            packet=assault.encode_request(op,value)
            self.assertEqual(assault.decode_request(packet),(op,value))
            with self.assertRaises(PacketError):assault.decode_request(packet+b'\0')
            for length in range(len(packet)):
                with self.assertRaises(PacketError):assault.decode_request(packet[:length])
        for packet in (b'\xc8\x21\2',b'\xc8\x20\1',b'\xc8\x18'):
            with self.assertRaises(PacketError):assault.decode_request(packet)

    def test_alliance_invitation_only_native_decisions(self):
        for value in (0,1):
            self.assertEqual(alliances.decode_request(bytes((0xaf,4,value))),(4,value))
        for packet in (b'\xaf\4\2',b'\xaf\4',b'\xaf\4\1\0',b'\xaf\7',b'\xaf\6'):
            with self.assertRaises(PacketError):alliances.decode_request(packet)

    def test_alliance_command_names_are_bounded_and_terminated(self):
        self.assertEqual(alliances.decode_request(b'\xaf\1'+b'A'*64+b'\0'),(1,b'A'*64))
        for packet in (b'\xaf\1\0',b'\xaf\1A',b'\xaf\1'+b'A'*65+b'\0',b'\xaf\2A\0B'):
            with self.assertRaises(PacketError):alliances.decode_request(packet)
        with self.assertRaises(PacketError):alliances.encode_invitation(b'A\0B',b'C')

    def test_rating_pages_are_top_three_pages_and_two_domains(self):
        for page in range(3):
            for selector in range(2):
                self.assertEqual(clan_ratings.decode_request(clan_ratings.encode_request(page,selector)),(page,selector))
        for packet in (b'\x82\3\0',b'\x82\0\2',b'\x82\0',b'\x82\0\0\0'):
            with self.assertRaises(PacketError):clan_ratings.decode_request(packet)

    def test_clan_influence_is_not_encoded_as_a_crest(self):
        row=clan_ratings.ClanRating(17,b'C',b'A',3,10,1,901,
                                   crest_id=29,alliance_crest_id=31)
        payload=clan_ratings.encode_ratings(0,0,(row,))
        # Six numeric fields after id, names, counts and level.
        self.assertEqual(struct.unpack('<6I',payload[-24:]),(29,901,0,31,0,0))

    def test_alliance_uses_leading_clan_identity_and_independent_crests(self):
        clan=alliances.AllianceClan(17,b'C',1,901,b'A',crest_id=29)
        row=alliances.AllianceInfo(123,b'X',1,17,901,0,(clan,),31)
        r=Reader(alliances.encode_info(row));self.assertEqual(r.read(2),b'\xaf\x0d')
        self.assertEqual(r.u32(),17)
        self.assertEqual(r.read(2),b'X\0');self.assertEqual(r.u8(),1)
        self.assertEqual((r.u32(),r.u32(),r.u8(),r.u16()),(31,901,0,1))
        self.assertEqual(r.u32(),17);self.assertEqual(r.read(2),b'C\0')
        self.assertEqual((r.u8(),r.u32(),r.u16(),r.u32()),(1,29,0,901))

    def test_alliance_ranking_count_and_leading_clan_name(self):
        clan=alliances.AllianceClan(17,b'Clan',1,901,b'Character')
        row=alliances.AllianceInfo(123,b'X',1,17,901,0,(clan,),0,3)
        payload=alliances.encode_ratings((row,))
        self.assertEqual(payload[-6:],b'\3Clan\0')
        self.assertNotIn(b'Character',payload)

    def test_flags_have_finite_native_floats(self):
        for value in (math.nan,math.inf,-math.inf,1e100):
            with self.assertRaises(PacketError):assault.encode_flag_status(value,2,0)
        self.assertEqual(assault.encode_flag_status(18,22,0),b'\xc8\x2e'+struct.pack('<ffI',18,22,0))
        self.assertEqual(assault.encode_flag_increment(18,22,7,2),b'\xc8\x31'+struct.pack('<ffII',18,22,7,2))

    def test_zone_optional_time_fields_do_not_confuse_zero_and_absent(self):
        absent=assault.ZoneInfo(0,100,None,200,4,6,7,9,3)
        present=assault.ZoneInfo(0,100,0,200,4,6,7,9,3,0)
        self.assertEqual(len(assault.encode_zone_body(present))-len(assault.encode_zone_body(absent)),8)
        with self.assertRaises(PacketError):assault.encode_zone_body(assault.ZoneInfo(7,100,None,200,4,6,7,9,3))

    def test_empty_result_retains_two_team_records(self):
        row=assault.TeamResult(0,0,0)
        self.assertEqual(assault.encode_battle_over(6,row,row),b'\xc8\x32'+struct.pack('<I',6)+bytes(40))
        with self.assertRaises(PacketError):assault.encode_battle_over(6,assault.TeamResult(4,0,0),row)
        with self.assertRaises(PacketError):assault.encode_battle_over(6,assault.TeamResult(1,0,math.nan),row)


if __name__=='__main__':unittest.main()
