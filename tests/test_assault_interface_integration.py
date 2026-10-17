"""Authoritative owned-slot HTTP and original clan badge projection."""
from contextlib import closing
import importlib.util
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_assault_public as fixtures
import test_clan_crest_gateway as gateway_fixtures
from server.alliance_service import classic_ratings
from server.economy_runtime import private_command
from tio.protocol.binary import Reader
from tio.protocol.clan_ratings import encode_request


def encode_send(channel,text):
    return bytes((0x21,channel))+text.encode('utf-16le')+b'\0\0'+(b'Alice\0' if channel==1 else b'')


class AssaultBadgeIntegrationTests(unittest.TestCase):
    def test_original_83_projects_actual_places_then_expires_without_changing_saves(self):
        f=fixtures.AssaultPublicTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        f.event('accepted');f.close();before=f.fingerprint()
        def rows():
            r=Reader(classic_ratings(SimpleNamespace(database=f.path),encode_request(0,0)))
            self.assertEqual(r.read(3),b'\x83\0\0');result={}
            for _ in range(r.u32()):
                identity=r.u32()
                for _ in range(2):
                    while r.u8():pass
                r.u16();r.u16();r.u8();result[identity]=tuple(r.u32() for _ in range(6))
            r.finish();return result
        with patch('server.assault_public.time.time',return_value=f.now):
            value=rows();self.assertEqual((value[2][4],value[1][4],value[3][4]),(1,2,0))
            self.assertTrue(all(row[5]==0 for row in value.values()))
        with patch('server.assault_public.time.time',return_value=f.week+2*fixtures.b.WEEK):
            self.assertTrue(all(row[4]==0 for row in rows().values()))
        self.assertEqual(before,f.fingerprint())

    def test_assault_command_is_private_in_every_native_chat_channel(self):
        for channel in (0,1,3,4):self.assertTrue(private_command(encode_send(channel,'!Assault me')))
        self.assertFalse(private_command(encode_send(0,'Давай !assault me')))


@unittest.skipUnless(importlib.util.find_spec('flask'),'Existing portal Flask runtime')
class AssaultGatewayIntegrationTests(unittest.TestCase):
    def setUp(self):
        f=gateway_fixtures.ClanCrestGatewayTests(methodName='runTest');f.setUp();self.addCleanup(f.doCleanups)
        self.f=f

    def post(self,data,*,auth=True,remote='127.0.0.1'):
        return self.f.client.post('/v1/clan/assault',json=data,
            headers={'Authorization':'Bearer '+self.f.key} if auth else {},
            environ_overrides={'REMOTE_ADDR':remote})

    def test_owned_alias_slot_read_only_view_excludes_private_owner_and_credentials(self):
        before=self.f.path.read_bytes();response=self.post(dict(username='alice',slot=2,page=1))
        self.assertEqual(response.status_code,200);value=response.json
        self.assertEqual((value['character'],value['assault']['character_name']),('AliceTwo','AliceTwo'))
        self.assertEqual(value['assault']['player']['clan']['name'],'Alpha')
        self.assertEqual(value['assault']['player']['medals']['entries'],[])
        self.assertNotIn(self.f.owner,response.text);self.assertNotIn(self.f.key,response.text)
        self.assertEqual(self.f.path.read_bytes(),before)

    def test_auth_slot_and_page_are_authoritative_on_new_route(self):
        valid=dict(username='alice',slot=2,page=1)
        self.assertEqual(self.post(valid,auth=False).status_code,401)
        self.assertEqual(self.post(valid,remote='203.0.113.8').status_code,403)
        self.assertEqual(self.post(dict(valid,slot=3)).status_code,409)
        self.assertEqual(self.post(dict(valid,username=self.f.owner)).status_code,400)
        self.assertEqual(self.post(dict(valid,owner='bob')).status_code,400)
        for page in (0,10001,True,'1',None):
            self.assertEqual(self.post(dict(valid,page=page)).status_code,400)


if __name__=='__main__':unittest.main()
