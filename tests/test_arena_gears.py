import struct
import unittest
from pathlib import Path
from unittest.mock import patch
from tio.protocol.ranked import encode_gears,decode_gears
from tio.protocol.binary import PacketError
from tio.arena_gears import catalogue_packet
import test_multi_account
import test_ranked


class CatalogueTests(unittest.TestCase):
    def test_wire_and_invalid_lengths(self):
        packet=encode_gears((301,210))
        self.assertEqual(packet,b'\xc6\x18'+struct.pack('<III',2,301,210))
        self.assertEqual(decode_gears(packet),(301,210))
        for end in range(len(packet)):
            with self.assertRaises(PacketError):decode_gears(packet[:end])
        for ids in ((),(301,301),(0,),(65500,),(True,),range(1,4098)):
            with self.assertRaises(PacketError):encode_gears(ids)
        with self.assertRaises(PacketError):decode_gears(packet+b'\0')

    def test_real_supported_templates(self):
        from tio.city_catalogs import CityCatalogs
        from tio.weapons import WeaponCatalog
        from tio.armor import ArmorCatalog
        shops=CityCatalogs(Path(__file__).resolve().parents[1]/'config/city_catalogs.json')
        ids=set(decode_gears(catalogue_packet()))
        self.assertIn(301,ids)
        self.assertLessEqual(ids,{o.item_id for offers in shops.items.values() for o in offers})
        self.assertLessEqual(ids,set(WeaponCatalog().weapons)|set(ArmorCatalog().items))

    def test_ranked_refresh_delivers_catalogue_before_rating(self):
        case=test_ranked.RankedServerTests();case.setUp();self.addCleanup(case.doCleanups)
        for request in (b'\xc6\x02',b'\xc6\x20'):
            replies=case.case.send(0,request)
            self.assertEqual(decode_gears(replies[0]),decode_gears(catalogue_packet()))
            self.assertEqual(replies[1][:2],b'\xc6\x03')
        self.assertFalse(case.hub.ranked_waiting)

    def test_combat_rating_refresh_does_not_touch_destroyed_city_controls(self):
        case=test_ranked.RankedServerTests();case.setUp();self.addCleanup(case.doCleanups)
        case.start()
        for request in (b'\xc6\x02',b'\xc6\x20'):
            replies=case.case.send(0,request)
            self.assertFalse(any(p.startswith(b'\xc6\x18') for p in replies))
            self.assertTrue(any(p.startswith(b'\xc6\x03') for p in replies))

    def test_two_accounts_town_ready_refresh_and_relogin(self):
        case=test_multi_account.MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups);case.start()
        for account,name in (('alice','Alice'),('bob','Bob')):
            peer=case.handoff(case.begin(account));case.enter(peer,name)
            for _ in range(2):
                peer.send(b'\x50\x03')
                self.assertEqual(decode_gears(peer.until(b'\xc6\x18')),decode_gears(catalogue_packet()))
                case.ping(peer)
            peer.send(b'\x50\x02');case.ping(peer)
            peer.send(b'\xc6\x20')
            self.assertEqual(decode_gears(peer.until(b'\xc6\x18')),decode_gears(catalogue_packet()))
            self.assertTrue(peer.until(b'\xc6\x03').startswith(b'\xc6\x03'))
        # A fresh session gets the catalogue again; no process-local per-owner latch.
        for connection in case.clients:connection.close()
        case.clients=[]
        import time
        deadline=time.monotonic()+5
        while case.server.multi.active_accounts and time.monotonic()<deadline:time.sleep(.01)
        peer=case.handoff(case.begin('alice'));case.enter(peer,'Alice')
        peer.send(b'\x50\x03');self.assertTrue(decode_gears(peer.until(b'\xc6\x18')))

