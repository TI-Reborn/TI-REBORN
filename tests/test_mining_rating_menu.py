"""Opening global ratings must not require or enter a mine checkpoint."""
import unittest
from unittest.mock import Mock
from tio.mining_service import MiningService


class MiningRatingMenuTests(unittest.TestCase):
    def service(self):
        service=object.__new__(MiningService)
        service.locations=Mock()
        service.arena=Mock()
        service.arena._durable=None
        service.market=Mock();service.market.ratings.return_value=()
        return service

    def test_all_role_rating_pages_are_public_reads_in_any_location(self):
        for town in (3,13,None):
            service=self.service();service.locations.current.return_value=town
            for selector in (1,2,3):
                started,replies=service.handle('alice',42,b'Alice',bytes((0xb0,0x28,selector)))
                self.assertIsNone(started)
                self.assertEqual(replies,(bytes((0xb0,0x29,selector,0,0)),))
            service.locations.current.assert_not_called()
            self.assertEqual(service.arena.mock_calls,[])
            self.assertEqual([c.args[0] for c in service.market.ratings.call_args_list],[1,2,3])

    def test_malformed_rating_request_does_not_reach_admission(self):
        service=self.service()
        for packet in (b'\xb0\x28',b'\xb0\x28\1\0'):
            with self.assertRaisesRegex(ValueError,'rating request'):
                service.handle('alice',42,b'Alice',packet)
        service.locations.current.assert_not_called()

    def test_actual_mine_entry_still_requires_checkpoint(self):
        service=self.service();service.locations.current.return_value=3
        with self.assertRaisesRegex(ValueError,'checkpoint first'):
            service.handle('alice',42,b'Alice',b'\xb0\x14\1')
