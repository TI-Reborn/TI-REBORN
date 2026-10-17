"""Territory bands must allow admitted assaults without opening city arenas."""
import unittest
from unittest.mock import patch

from tio.cities import require_arena
from tio.team_scene import require_assault_location
from tio.territories import CONFIG,load_config
from tio.world_completion import location


class AssaultLocationAdmissionTests(unittest.TestCase):
    def test_every_enabled_capture_territory_accepts_its_full_level_band(self):
        _,territories=load_config(CONFIG)
        for town,row in territories.items():
            if not row['enabled']:continue
            with self.subTest(town=town):
                lo,hi=row['levels']
                self.assertEqual(require_assault_location(town,(lo,hi),location(town)),location(town))
                for levels in ((),(lo-1,),(hi+1,),(True,),('4',)):
                    with self.assertRaises(ValueError):require_assault_location(town,levels,location(town))
                with self.assertRaises(ValueError):require_arena(town,(lo,hi))

    def test_training_admission_keeps_its_separate_non_capture_bands(self):
        for town,lo,hi in ((19,4,6),(20,7,10),(21,11,15),(22,16,20)):
            with self.subTest(town=town):
                self.assertFalse(require_assault_location(town,(lo,hi),location(town))['capture'])
                with self.assertRaises(ValueError):require_assault_location(town,(lo-1,),location(town))

    def test_disabled_unknown_or_ordinary_city_cannot_use_assault_bypass(self):
        _,territories=load_config(CONFIG)
        territories[11]=dict(territories[11],enabled=False)
        with patch('tio.territories.load_config',return_value=({},territories)):
            with self.assertRaises(ValueError):require_assault_location(11,(4,),None)
        for town in (0,3,10,18,65535):
            with self.assertRaises(ValueError):require_assault_location(town,(4,),location(town))


if __name__=='__main__':unittest.main()
