from contextlib import closing,redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import verify_hosted_clan_warfare as qa
from tio.protocol.clan_ratings import ClanRating,encode_ratings
from tio.protocol.alliances import AllianceInfo,AllianceClan,encode_ratings as alliance_ratings
from tio.protocol.public_profile import encode_profile


class HostedWarfareToolTests(unittest.TestCase):
    def test_native_parser_checks_page_selector_and_bounds(self):
        row=ClanRating(17,b'Clan',b'Leader',1,15,1,901)
        self.assertEqual(qa.clan_page(encode_ratings(0,0,[row]),0,0),dict(kind=0,selector=0,count=1))
        with self.assertRaises(AssertionError):qa.clan_page(encode_ratings(0,0,[row]),1,0)
        with self.assertRaises(AssertionError):qa.clan_page(encode_ratings(0,1,[row]),0,1)
        with self.assertRaises(AssertionError):qa.clan_page(encode_ratings(0,0,[replace(row,influence=1),row]),0,0)
        with self.assertRaises(AssertionError):qa.clan_page(encode_ratings(0,0,[replace(row,crest_id=1)]),0,0)

    def test_native_alliance_count_and_profile_crest_semantics(self):
        row=AllianceInfo(123,b'Alliance',1,17,901,0,(AllianceClan(17,b'Clan',1,901,b'Leader'),))
        self.assertEqual(qa.alliance_page(alliance_ratings([row])),dict(count=1))
        packet=encode_profile(17,b'Alice',1,'')
        self.assertEqual(qa.own_profile(packet,b'Alice')['alliance_crest'],0)
        with self.assertRaises(AssertionError):qa.own_profile(encode_profile(17,b'Alice',1,'',alliance_name=b'Invented',alliance_crest_id=123),b'Alice')

    def test_provision_only_normal_two_accounts_with_prewrite_guards(self):
        compile(qa.PROVISION,'provision','exec');compile(qa.SNAPSHOT,'snapshot','exec')
        self.assertIn("assert len(names)==2",qa.PROVISION)
        self.assertIn('create(name,password)',qa.PROVISION)
        self.assertNotIn('create(name,password,character=',qa.PROVISION)
        for port in (28512,28513,29512,29513):self.assertIn(str(port),qa.PROVISION)
        self.assertLess(qa.PROVISION.index('battle_settlement_jobs'),qa.PROVISION.index('folder=pathlib.Path(tempfile.mkdtemp'))
        for table in ('warfare_match_receipts','warfare_event_receipts','territory_claim_history'):self.assertIn(table,qa.SNAPSHOT)
        for mutation in ('INSERT ','UPDATE ','DELETE ','CREATE '):self.assertNotIn(mutation,qa.SNAPSHOT)

    def test_prepare_and_private_reload_are_local_preserve_secrets_and_use16char_passwords(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(qa,'PRIVATE',Path(temp)/'private'),patch.object(qa.WarfareFixture,'private_directory'),patch.object(qa.FreshSurroundingsQA,'remote',side_effect=AssertionError('Unexpected SSH')):
            qa.PRIVATE.mkdir();(qa.PRIVATE/'.gitignore').write_text('*\n')
            fixture=qa.WarfareFixture.prepare('127.0.0.1','local-key')
            self.assertEqual(len(fixture.names),2);self.assertTrue(all(len(p)==16 for p in fixture.passwords))
            loaded=qa.WarfareFixture.load(fixture.credential_path)
            self.assertEqual(loaded.passwords,fixture.passwords);self.assertFalse(loaded.backup)
            with self.assertRaises(AssertionError):fixture.save(pending=True)

    def test_real_local_tls_normal_onboarding_readonly_pages_profiles_and_room_denial(self):
        # Only path/ownership/ss observations are adapted. Both TLS channels,
        # command framing, actual server handlers and SQLite stores are real.
        from test_multi_account import MultiAccountTests
        from test_game_tls import free_ports,FIXTURES
        from server.config import TLSConfig
        case=MultiAccountTests();case.setUp();self.addCleanup(case.doCleanups)
        ports=free_ports(2)
        case.config=replace(case.config,tls=TLSConfig(True,*ports,FIXTURES/'valid-chain.pem',FIXTURES/'valid-key.pem'))
        backup=case.config.data_directory/'before-ordinary-qa';backup.mkdir()
        with closing(sqlite3.connect(case.config.database)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:src.backup(dst)
        names=['qs01234567a','qs01234567b'];passwords=['LocalPassword123','OtherPassword123']
        for name,password in zip(names,passwords):case.accounts.create(name,password)
        fixture=qa.WarfareFixture('127.0.0.1','qs01234567',names,passwords,str(backup),'local-key')
        def remote(code,payload):
            self.assertTrue(code.startswith(qa.OWNERSHIP))
            source=code[len(qa.OWNERSHIP):]
            self.assertNotIn('UPDATE ',source);self.assertNotIn('DELETE ',source)
            source=source.replace('/var/lib/tio-server/reservation.sqlite3',case.config.database.as_posix())
            source='import json,pathlib,sqlite3,sys\ndata=json.load(sys.stdin);names=data["names"];folder=pathlib.Path(data["backup"])\n'+source
            out=io.StringIO()
            with patch.object(sys,'stdin',io.StringIO(json.dumps(payload))),redirect_stdout(out),patch('subprocess.check_output',side_effect=lambda *a,**k:'owned-session\n'*len(case.server.multi.active_accounts)):
                exec(compile(source,'<local readonly warfare proof>','exec'),{})
            return json.loads(out.getvalue())
        fixture.remote=remote
        args=SimpleNamespace(host='127.0.0.1',server_name='localhost',login_port=ports[0],session_port=ports[1],ca_file=FIXTURES/'ca.pem',loopback_session_port=31003)
        hashes={name:hashlib.sha256((qa.ROOT/name).read_bytes()).hexdigest() for name in ('tio/alliances.py','tio/protocol/clan_ratings.py')}
        case.start();report=dict(passed=False)
        qa.run(fixture,args,report,hashes)
        self.assertTrue(report['passed']);self.assertEqual(len(report['pages']),12)
        self.assertEqual(report['starter_wallets'],[[3000,0],[3000,0]])
        self.assertEqual(len(report['profiles']),2);self.assertEqual(len(report['room_query_rejections']),2)
        self.assertTrue(report['global_claims_groups_matches_unchanged'])
        self.assertTrue(all(c['verified_chain_and_name'] for c in report['tls_channels']))
        self.assertTrue(all(not direction['plaintext_secret_found'] for c in report['tls_channels'] for direction in c['wire'].values()))


if __name__=='__main__':unittest.main()
