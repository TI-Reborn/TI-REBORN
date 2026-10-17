"""Validate public evidence readers and no-network gates, never touch hosting."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools import verify_hosted_clan_completion as clan
from tools import verify_hosted_world_completion as world
from tio.protocol.clan_ratings import ClanRating,encode_ratings
from tio.protocol.clans import encode_info
from tio.protocol.public_profile import encode_profile
from tio.protocol.shared_config import SharedConfigData,encode_shared_config_data
from tio.protocol.system_message import encode_shop_error
from tio.protocol.town_info import TownInfoBase,encode_town_info


class HostedEvidenceReadersTests(unittest.TestCase):
    def rejects(self,call,*args):
        with self.assertRaises((ValueError,AssertionError)):call(*args)

    def test_clan54_is_login_push_and_empty_affiliation_is_exact(self):
        value=clan.clan_info(encode_info())
        self.assertEqual((value['id'],value['name'],value['crest']),(0,'',0))
        self.rejects(clan.clan_info,encode_info()+b'\0')
        fake=bytearray(encode_info());fake[-2]=1
        self.rejects(clan.clan_info,bytes(fake))

    def test_real_crest_nonzero_and_clan_ties_are_preserved(self):
        rows=(ClanRating(3,b'A',b'Leader',1,7,1,20,crest_id=9),ClanRating(8,b'B',b'Owner',1,7,1,20,crest_id=11))
        self.assertEqual([r['crest'] for r in clan.clan_page(encode_ratings(0,0,rows),0,0)],[9,11])
        self.rejects(clan.clan_page,encode_ratings(0,0,rows[::-1]),0,0)

    def test_unconfirmed_trueskill_cannot_be_claimed_positive(self):
        self.assertEqual(clan.clan_page(encode_ratings(0,1,()),0,1),[])
        self.rejects(clan.clan_page,encode_ratings(0,1,(ClanRating(1,b'A',b'O',1,7,1,1),)),0,1)

    def test_profile_signed_rating_and_large_earned_merc_xp(self):
        packet=encode_profile(1,b'Alice',20,'',rating=-(1<<31),mercenaries=((b'Merc',20,0xffffffff,1),))
        row=clan.public_profile(packet)
        self.assertEqual(row['rating'],-(1<<31));self.assertEqual(row['mercenaries'][0]['xp'],0xffffffff)
        self.rejects(clan.public_profile,packet[:-1]);self.rejects(clan.public_profile,packet+b'\0')

    def test_error394_utf16_only_and_truncation_rejected(self):
        packet=encode_shop_error('Эмблема не найдена')
        self.assertEqual(clan.native_error(packet),'Эмблема не найдена')
        self.rejects(clan.native_error,packet[:-1]);self.rejects(clan.native_error,packet+b'\0')
        self.rejects(clan.native_error,b'\xf0'+struct.pack('<II',98,0))

    def test_clan_page_count_bound(self):
        self.rejects(clan.clan_page,b'\x83\0\0'+struct.pack('<I',101),0,0)

    def zone_packet(self,raw):
        return encode_shared_config_data(SharedConfigData(b'zones',len(raw),zlib.compress(raw)))

    def test_xml_checks_native_contiguous_order_and_exact_deflate(self):
        path=world.ROOT/'reports/gameplay-completion/stage8-world/runtime/evidence/zones_diagnostic.xml'
        raw=path.read_bytes();self.assertEqual(clan.zones(self.zone_packet(raw))['ids'],list(range(1,23)))
        swapped=raw.replace(b'id="18"',b'id="23"').replace(b'id="19"',b'id="18"').replace(b'id="23"',b'id="19"')
        self.rejects(clan.zones,self.zone_packet(swapped))
        packet=encode_shared_config_data(SharedConfigData(b'zones',len(raw),zlib.compress(raw)+b'extra'))
        self.rejects(clan.zones,packet)


class HostedWorldSafetyTests(unittest.TestCase):
    def setUp(self):
        self.rates={'4':[dict(town_id=4,epoch=1,influence='0',experience='3/4',profit='1')]}
        self.info=TownInfoBase(4,0,(4,20,0,0),(0,0,0),(0,0x3f400000,0x3f800000),(0,0,0),1)

    def test_mapping_matches_original_tooltips_and_rational_bits(self):
        actual=world.town_observation(encode_town_info(self.info),self.rates)
        self.assertEqual(actual['float_bits'],[0,0x3f400000,0x3f800000]);self.assertEqual(actual['booleans']['dragin'],0)
        bad=replace(self.info,unknown_float_bits=(0x3f400000,0,0x3f800000))
        with self.assertRaises(AssertionError):world.town_observation(encode_town_info(bad),self.rates)

    def test_nonfinite_coefficients_and_outpost_carry_gear_rejected(self):
        for info in (replace(self.info,unknown_float_bits=(0x7fc00000,0x3f400000,0x3f800000)),replace(self.info,unknown_bools=(0,1,0)),replace(self.info,unknown_bytes=(1,20,0,0))):
            with self.assertRaises(AssertionError):world.town_observation(encode_town_info(info),self.rates)

    def test_real_travel_bounds_no_float_or_boolean_coordinates(self):
        self.assertEqual(world.travel_request((-512,511)),struct.pack('<Bii',0x1b,-512,511))
        for point in ((512,0),(-513,0),(0.0,0),(True,0),(1,),None):
            with self.assertRaises(AssertionError):world.travel_request(point)

    def test_real_hour_boundary_allows_only_actual_adjacent_snapshots(self):
        rates=deepcopy(self.rates);rates['4'].append(dict(town_id=4,epoch=2,influence='1',experience='1',profit='4'))
        info=replace(self.info,unknown_float_bits=(0x3f800000,0x3f800000,0x40800000))
        self.assertEqual(world.town_observation(encode_town_info(info),rates)['real_utc_coefficients']['epoch'],2)
        with self.assertRaises(AssertionError):world.town_observation(encode_town_info(info),self.rates)

    def test_encounter_cannot_excuse_any_wallet_inventory_or_foreign_change(self):
        keys=('account','wallet','securities','items','tutorial','bank_receipts','marks','shop','sales','orders','messages','mail_items','mail_receipts','sc_receipts','private_receipts')
        state={k:[] for k in keys};state['account']='owned';state['wallet']=[3000,0];state['pets']=[dict(id=1,level=1,xp=0,profile_sha256='before')]
        before=dict(states=[state],foreign={},payments={},service='same');after=deepcopy(before)
        before['states'][0]['protected']={};after['states'][0]['protected']={}
        after['states'][0]['pets'][0]['profile_sha256']='real health after escape'
        proof=[dict(profile_changes_allowed=True,initial_protected={},protected={})]
        world.retained_assets(before,after,encounter=True,escapes=proof)
        for key in ('wallet','items'):
            bad=deepcopy(after);bad['states'][0][key]=['changed']
            with self.assertRaises(AssertionError):world.retained_assets(before,bad,encounter=True,escapes=proof)
        bad=deepcopy(after);bad['foreign']['foreign-owner']='changed'
        with self.assertRaises(AssertionError):world.retained_assets(before,bad,encounter=True,escapes=proof)
        with self.assertRaises(AssertionError):world.retained_assets(before,after,encounter=False)
        with self.assertRaises(AssertionError):world.retained_assets(before,after,encounter=True)

    def test_remote_observation_never_calls_schema_or_settlement(self):
        for source in (clan.CENSUS,world.WORLD_STATE):
            compile(source,'readonly_qa','exec')
            self.assertIn('?mode=ro',source);self.assertIn('PRAGMA query_only=ON',source)
            for forbidden in ('INSERT ','UPDATE ','DELETE ','CREATE TABLE','schema(db)','settle(','LocationStore('):self.assertNotIn(forbidden,source)

    def test_missing_deployment_refuses_before_credentials_or_network(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(world.Stage7Fixture,'load') as load,patch.object(world,'run') as run:
            code=world.main(['--deployments',tmp,'--phase7',str(Path(tmp)/'missing7.json'),'--phase8',str(Path(tmp)/'missing8.json'),'--fixture','private-unused.json','--output',str(Path(tmp)/'failure.json')])
            self.assertEqual(code,1);load.assert_not_called();run.assert_not_called()
            value=json.loads((Path(tmp)/'failure.json').read_text());self.assertFalse(value['passed']);self.assertEqual(value['error_type'],'FileNotFoundError')

    def test_world_release_requires_exact_deployed_native_model_chain(self):
        release=json.loads((world.ROOT/'reports/gameplay-completion/stage8-world/client/release.json').read_text())['world_client_release']
        hashes={'config/world_completion.json':release['policy_sha256'],'evidence/zones_diagnostic.xml':release['runtime_sha256']}
        with tempfile.TemporaryDirectory() as tmp:
            proof=Path(tmp)/'deployment.json';proof.write_text(json.dumps({'world_client_release':release}))
            self.assertEqual(world.pin_world_release(proof,hashes),release)
            proof.write_text(json.dumps({'world_client_release':{**release,'runtime_sha256':'0'*64}}))
            with self.assertRaises(AssertionError):world.pin_world_release(proof,hashes)
            proof.write_text(json.dumps({'world_client_release':release}))
            with self.assertRaises(AssertionError):world.pin_world_release(proof,{**hashes,'config/world_completion.json':'0'*64})

    def test_self_tests_need_no_credentials_or_network(self):
        with patch.object(world,'run') as wrun,patch.object(clan,'run') as crun:
            self.assertEqual(world.main(['--self-test']),0);self.assertEqual(clan.main(['--self-test']),0)
            wrun.assert_not_called();crun.assert_not_called()


if __name__=='__main__':unittest.main()
