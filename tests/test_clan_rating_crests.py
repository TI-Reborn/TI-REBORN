"""Stored clan/alliance image IDs share the classic original rating transport."""
from types import SimpleNamespace
import unittest
from tests import test_alliance_crests as fixtures
from tio.db_transaction import transaction
from tio.clan_benefits import set_crest
from tio.protocol.clan_ratings import encode_request
from tio.protocol.binary import Reader
from server.alliance_service import classic_ratings


class ClanRatingCrestTests(unittest.TestCase):
    def test_actual_saved_images_project_both_ids_without_changing_player_data(self):
        f=fixtures.AllianceCrestTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        f.create();f.join()
        with transaction(f.path) as db:clan=set_crest(db,'alice',fixtures.bmp(8),'clan:image')
        alliance=f.store.set_crest('alice',fixtures.bmp(9),'alliance:image')
        before=f.path.read_bytes()
        r=Reader(classic_ratings(SimpleNamespace(database=f.path),encode_request(0,0)))
        self.assertEqual(r.read(3),b'\x83\0\0')
        rows={}
        for _ in range(r.u32()):
            identity=r.u32()
            for _ in range(2):
                while r.u8():pass
            r.u16();r.u16();r.u8()
            rows[identity]=tuple(r.u32() for _ in range(6))
        r.finish()
        row=rows[f.ids['alice']]
        self.assertEqual(row[0],clan['crest_id'])
        self.assertEqual(row[3],alliance['crest_id'])
        self.assertNotEqual(row[0],row[3])
        self.assertEqual(rows[f.ids['carol']][3],0)
        self.assertEqual(f.path.read_bytes(),before)
