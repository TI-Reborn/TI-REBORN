from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import unittest
from pathlib import Path
import test_shared_team_arena as helpers
from tio.locations import LocationStore,center,town_packets,town_at
from tio.cities import CITIES
from tio.map_generation import generate_map,connected,reachable_cells
from tio.owned_pets import OwnedPetStore
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.town_info import decode_town_info
from tio.reward_policy import RewardContext,calculate


class CityTests(unittest.TestCase):
    setUp=helpers.SharedTeamTests.setUp
    send=helpers.SharedTeamTests.send

    def locate(self,index,town,level):
        s=self.sessions[index];s.locations=LocationStore(self.path)
        with closing(sqlite3.connect(self.path)) as db,db:
            LocationStore._save(db,s.account,town,*center(town))
            raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(s.account,)).fetchone()[0]
            pet=decode_pet_info(raw,human_equipment=True)
            raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':level}))
            db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(raw,s.account))

    def test_city_bounds_entry_and_manual_levels(self):
        for town,city in CITIES.items():
            self.assertEqual(town_at(*center(town)),town)
            self.assertEqual(decode_town_info(town_packets(town)[0]).unknown_bytes[:2],city.levels)
        import xml.etree.ElementTree as ET
        towns=ET.parse(Path(__file__).resolve().parents[1]/'evidence/zones_diagnostic.xml').getroot()
        for row in towns:
            i=int(row.attrib['id'])
            if i not in CITIES:continue
            values={v.attrib['key']:v.attrib['val'] for v in row}
            self.assertEqual(values['enabled'],'1')
            self.assertEqual((int(values['minlevel']),int(values['maxlevel'])),CITIES[i].levels)

    def test_cross_city_survival_shared_map_return_and_snapshot(self):
        self.locate(0,2,4);self.locate(1,5,4)
        before=OwnedPetStore(self.path).list('alice')
        self.send(0,b'\xba\3\0\1');self.send(1,b'\xba\3\0\1')
        owners=[self.hub.identities[s] for s in self.sessions[:2]]
        b=self.hub.battles[owners[0]]
        self.assertIs(b,self.hub.battles[owners[1]])
        self.assertEqual(b['city_id'],2)
        self.assertEqual(b['field'].scene_metadata['profile'],'denver')
        self.assertFalse(b['bots'])
        self.assertEqual(b['return_towns'],dict(zip(owners,(2,5))))
        self.assertEqual(OwnedPetStore(self.path).list('alice'),before)
        from tio.battle_snapshot import dumps,loads
        restored=loads(dumps({'battle':b}))[0]['battle']
        self.assertEqual(restored['city_id'],2)
        self.assertEqual(restored['field'].combat.city_kill_bonus,10)
        self.assertEqual(restored['return_towns'],b['return_towns'])

    def test_admission_band_and_noncombat_city_rejections(self):
        for town,level in ((2,3),(3,4),(9,4),(17,4)):
            self.locate(0,town,level)
            replies=self.send(0,b'\xba\3\0\1')
            self.assertTrue(any(p[0]==0xf0 for p in replies),(town,level,replies))
            self.assertFalse(self.hub.survival_queue.tickets)
        self.locate(0,2,6);self.locate(1,8,7)
        self.send(0,b'\xba\3\0\1');self.send(1,b'\xba\3\0\1')
        self.assertFalse(self.hub.battles)

    def test_cross_city_team_with_four_real_accounts(self):
        for i,town in enumerate((5,8,2,5)):self.locate(i,town,4)
        for i in (0,1):self.send(i,b'\xba\3\1\1')
        for i,c in ((2,0),(3,1)):
            room=self.hub.lobbies.room(self.hub.identities[self.sessions[c]])
            self.send(i,b'\xba\4'+room.identity.to_bytes(4,'little'));self.send(i,b'\x2c\1')
        for i in (0,1):self.send(i,b'\x2e')
        b=self.hub.battles[self.hub.identities[self.sessions[0]]]
        self.assertFalse(b['bots']);self.assertEqual(len(b['humans']),4)
        self.assertEqual(b['field'].scene_metadata['profile'],'new_york')
        self.assertEqual(b['field'].width,57)

    def test_city_rank_bonus_and_lobby_isolation(self):
        self.locate(0,2,4);self.locate(1,5,4)
        self.send(0,b'\xba\3\0\1');self.send(1,b'\xba\3\0\1')
        b=self.hub.battles[self.hub.identities[self.sessions[0]]];combat=b['field'].combat
        owner=self.hub.identities[self.sessions[0]];killer=b['field'].actor_ids(owner)[0]
        victim=b['field'].actor_ids(self.hub.identities[self.sessions[1]])[0]
        combat.rank_kills.append((killer,victim))
        from tio.ranks import battle_report,kill_points
        expected=kill_points(*combat.rank_profiles[killer],*combat.rank_profiles[victim])+10
        self.assertEqual(battle_report(combat,owner)[killer][0],expected)
        self.locate(2,3,1);self.locate(3,8,4)
        self.send(2,b'\xba\3\1\1')
        room=self.hub.lobbies.room(self.hub.identities[self.sessions[2]])
        replies=self.send(3,b'\xba\4'+room.identity.to_bytes(4,'little'))
        self.assertTrue(any(p[0]==0xf0 for p in replies))
        self.assertIsNone(self.hub.lobbies.room(self.hub.identities[self.sessions[3]]))

    def test_profit_multiplier_survives_outbox_and_repeat_calculation(self):
        from tio.battle_settlement import pack,unpack
        context=RewardContext((4,),(('bob',(4,)),),True,2)
        _,kwargs=unpack(pack(1,dict(reward_context=context)))
        self.assertEqual(kwargs['reward_context'],context)
        with closing(sqlite3.connect(self.path)) as db,db:
            city,audit=calculate(db,'alice','town',1,context,0,now=1)
            plain,_=calculate(db,'alice','town',1,replace(context,town_id=None),0,now=1)
            self.assertEqual(city,4*plain)
            self.assertEqual(json.loads(audit)['city_profit'],4)

    def test_hiring_all_combat_cities_but_miners_only_in_miners_town(self):
        from tio.hiring import HireStore
        from tio.city_catalogs import CityCatalogs
        root=Path(__file__).resolve().parents[1]
        raw=OwnedPetStore(self.path).list('alice')[0][1]
        store=HireStore(self.path,CityCatalogs(root/'config/city_catalogs.json'),raw)
        for town in (2,5,8):
            self.locate(0,town,4)
            candidates=store.available('alice')
            self.assertTrue(candidates)
            self.assertFalse(any(c.resource_type==6 for c in candidates))
        self.locate(0,9,4)
        self.assertTrue(all(c.resource_type==6 for c in store.available('alice')))

    def test_original_city_maps_connected_for_modes_and_seeds(self):
        for profile in ('denver','new_york','military_zone'):
            for mode in (0,1,4):
                for seed in range(4):
                    m=generate_map(profile,seed=seed,mode=mode,deployment_size=6)
                    self.assertTrue(connected(m.arena,reachable_cells(m.arena)))
                    self.assertGreaterEqual(len(m.arena.containers),3)
                    names=[o['file'] for o in m.layout['objects']]
                    if profile=='denver':self.assertTrue(any('forest_tree' in n for n in names))
                    if profile=='new_york':self.assertTrue(any(n.startswith('ny_') for n in names))
