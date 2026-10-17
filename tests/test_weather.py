"""Shared weather, recipient visibility, shelter and checkpoint continuity."""
from copy import copy
from dataclasses import replace
import unittest
from unittest.mock import patch
from test_battle_item_effects import BattleItemFixture
from tio import weather, battle_snapshot, battle_item_effects as effects
from tio.protocol.weather import encode_weather,decode_weather
from tio.protocol.binary import PacketError


class WeatherTests(BattleItemFixture):
    def wet(self, blocker=()):
        self.prepare(blocker=blocker)
        self.field.scene_metadata={'profile':'reservation','seed':0,'objects':[]}
        while not weather.raining(self.field):self.field.scene_metadata['seed']+=1
        effects.initialize(self.combat)

    def test_codec_rejects_wrong_lengths_flags_duplicate_coordinates_and_dry_data(self):
        packet=encode_weather(True,3,((1,2),(3,4)))
        self.assertEqual(decode_weather(packet),(True,3,((1,2),(3,4))))
        for bad in (packet[:-1],packet+b'\0',b'\xfb\2'+packet[2:],b'\xfb\1\2'+packet[3:]):
            with self.assertRaises(PacketError):decode_weather(bad)
        for args in ((False,1,()),(False,0,((1,2),)),(True,0,((255,2),)),(True,0,((1,2),(1,2)))):
            with self.assertRaises(PacketError):encode_weather(*args)

    def test_shared_match_seed_recipient_cells_and_reconnect_do_not_change_combat(self):
        self.wet();before=battle_snapshot.dumps(self.field,clock=lambda:1,wall=lambda:1)
        alice=decode_weather(weather.packet(self.field,7));bob=decode_weather(weather.packet(self.field,8))
        self.assertTrue(alice[0] and bob[0]);self.assertEqual(alice[1],bob[1]);self.assertNotEqual(alice[2],bob[2])
        self.assertFalse(decode_weather(weather.packet(self.field,999))[0])
        self.assertEqual(battle_snapshot.dumps(self.field,clock=lambda:1,wall=lambda:1),before)
        restored,_=battle_snapshot.loads(before)
        self.assertEqual(weather.packet(restored,7),weather.packet(self.field,7))
        self.field._ability_turns={1:4,2:4}
        self.assertEqual(decode_weather(weather.packet(self.field,7))[1],2)

    def test_fog_cover_smoke_and_replayed_observer_coordinates_are_respected(self):
        self.wet(blocker={(4,y) for y in range(20)})
        self.field._actors[3]=replace(self.field.actor(3),health=0)
        self.assertTrue(all(x<4 for x,y in decode_weather(weather.packet(self.field,7))[2]))
        replay=copy(self.field);replay._actors=dict(self.field._actors)
        replay._actors[1]=replace(replay.actor(1),x=20,y=3)
        self.assertTrue(all(x>4 for x,y in decode_weather(weather.packet(replay,7))[2]))
        self.combat.item_effects['areas'][1]=dict(kind='smoke',center=(2,3),radius=3,source=1,owner=7,expiry=3)
        self.assertFalse(decode_weather(weather.packet(self.field,7))[0])

    def test_mines_training_and_unseeded_scenes_are_dry(self):
        self.wet()
        for metadata in ({'profile':'mine','seed':self.field.scene_metadata['seed']},
                         {**self.field.scene_metadata,'town_id':3}, {'profile':'reservation'}):
            with patch.object(self.field,'scene_metadata',metadata):
                self.assertEqual(decode_weather(weather.packet(self.field,7)),(False,0,()))
        self.assertIs(weather.policy()['snow_enabled'],False)

    def test_enclosed_rooms_and_building_rectangles_shelter_rain(self):
        walls={(x,y) for x in range(5,10) for y in range(5,10) if x in (5,9) or y in (5,9)}
        self.wet(blocker=walls)
        self.assertIn((7,7),weather.sheltered(self.field))
        self.field.scene_metadata['objects']=[{'file':'house.s','x':0,'y':0}]
        with patch.object(weather,'fragments',return_value={'house.s':{'width':4,'height':4}}):
            self.assertIn((2,2),weather.sheltered(self.field))
            self.assertFalse(any(x<4 and y<4 for x,y in decode_weather(weather.packet(self.field,7))[2]))


if __name__=='__main__':unittest.main()
