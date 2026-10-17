"""Safety/negative checks for the optional production economy acceptance tool."""
import ast
import copy
from contextlib import redirect_stdout
import io
import json
import hashlib
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

from tools.verify_hosted_economy_tls import PROVISION_ECONOMY, ECONOMY_SNAPSHOT, PAIR_READY, OWNERSHIP, PINNED_SOURCES, ROOT, path_to_adjacent, summary, run_economy
from tio.protocol.battle_over import SoldierExperience, encode_battle_over


class HostedEconomyVerifierTests(unittest.TestCase):
    def test_provisioning_only_creates_accounts_and_consistent_backup(self):
        tree=ast.parse(PROVISION_ECONOMY)
        creates=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='create']
        self.assertEqual(len(creates),1)
        self.assertFalse(creates[0].keywords, 'Native onboarding must create the character, not administration')
        self.assertIn('src.backup(dst)',PROVISION_ECONOMY)
        self.assertLess(PROVISION_ECONOMY.index('src.backup(dst)'),PROVISION_ECONOMY.index('.create(name,password)'))
        self.assertLess(PROVISION_ECONOMY.index("data['source_hashes']"),PROVISION_ECONOMY.index('tempfile.mkdtemp'))
        self.assertNotIn('UPDATE ',PROVISION_ECONOMY)
        self.assertNotIn('DELETE ',PROVISION_ECONOMY)

    def test_readonly_ownership_snapshots_and_idle_guards(self):
        ast.parse(ECONOMY_SNAPSHOT)
        ast.parse(PAIR_READY)
        for port in (28512,28513,29512,29513):
            self.assertIn(':'+str(port),PROVISION_ECONOMY)
            self.assertIn(':'+str(port),PAIR_READY)
        for code in (ECONOMY_SNAPSHOT,PAIR_READY):
            tree=ast.parse(code)
            connects=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='connect']
            self.assertTrue(connects)
            for call in connects:
                self.assertIn('mode=ro',ast.unparse(call.args[0]))
                self.assertIn('uri=True',ast.unparse(call))
            self.assertNotIn('INSERT ',code)
            self.assertNotIn('UPDATE ',code)
            self.assertNotIn('DELETE ',code)
        self.assertIn('Only the two owned TLS sessions',PAIR_READY)
        self.assertIn('Retained battle present',PAIR_READY)

    def test_native_result_without_xp_cannot_be_accepted(self):
        with self.assertRaises(AssertionError):summary(encode_battle_over(1,credits=100))
        record=SoldierExperience(2,123,tuple([0]*7),tuple([0]*16))
        packet=encode_battle_over(1,credits=100,soldiers=(record,))
        decoded=summary(packet)
        self.assertEqual((decoded['xp_actor'],decoded['xp_gain'],decoded['credits']),(2,123,100))
        for invalid in (packet[:-1],packet+b'\0'):
            with self.assertRaises(AssertionError):summary(invalid)

    def test_native_positive_dropped_recipient_cannot_hide_in_count(self):
        records=tuple(SoldierExperience(i,10,tuple([0]*7),tuple([0]*16)) for i in (1,2))
        with self.assertRaises(AssertionError):summary(encode_battle_over(1,soldiers=records))

    def test_match_path_respects_blockers_and_opponent(self):
        blockers={(1,0),(1,1)}
        route=path_to_adjacent((0,0),(3,0),blockers,4,4)
        self.assertFalse(set(route)&(blockers|{(3,0)}))
        self.assertEqual(sum(abs(a-b) for a,b in zip(route[-1],(3,0))),1)
        with self.assertRaises(AssertionError):path_to_adjacent((0,0),(3,0),{(1,y) for y in range(4)},4,4)

    def test_linux_ss_headerless_state_and_ipv6_formats_are_counted(self):
        variants=('ESTAB 0 0 185.184.42.88:29513 192.0.2.1:4000\n',
                  '0 0 185.184.42.88:29513 192.0.2.1:4000\n',
                  '0 0 [::ffff:185.184.42.88]:29513 [::ffff:192.0.2.1]:4000\n')
        source=PAIR_READY[len(OWNERSHIP):]
        for line in variants:
            with self.subTest(line=line):
                fake=MagicMock();fake.connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=(0,)
                output=io.StringIO()
                with patch('subprocess.check_output',side_effect=[line*2,line*2]),redirect_stdout(output):
                    exec(compile(source,'<Linux ss count fixture>','exec'),dict(json=json,sqlite3=fake))
                self.assertEqual(json.loads(output.getvalue())['other_established_game_connections'],0)
        fake=MagicMock()
        with patch('subprocess.check_output',side_effect=[variants[0]*3,variants[0]*2]):
            with self.assertRaises(AssertionError):exec(compile(source,'<extra-player negative fixture>','exec'),dict(json=json,sqlite3=fake))

    def test_resume_rejects_progressed_or_modified_pair_before_network(self):
        state=dict(characters=1,receipts=[],xp_audit=[],rank_audit=[],repairs=[],checkpoints=0,wallet=[3050,0],
            achievement_credits=100,awards=[dict(id=38)],pets=[dict(id=1,level=1,xp=0,rank_points=0,hp=100,max_hp=100,
            items=[dict(id=1001,template=301,count=1,equipped=1,slot=16,durability=[300]*3),
                   dict(id=1002,template=3,count=50,equipped=0,slot=0,durability=[1]*3)])])
        hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in PINNED_SOURCES}
        folder=ROOT/'reports/stage4-economy';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=folder,suffix='.json',delete=False) as handle:path=Path(handle.name)
        try:
            path.write_text(json.dumps(dict(accounts=['qaexamplea','qaexampleb'],source_hashes=hashes,passed=False,battles=[],
                onboarding=[dict(wallet=[3000,0])]*2,first_purchase=[dict(wallet=[3050,0])]*2)),encoding='utf-8')
            args=SimpleNamespace(resume_onboarding_report=path,host='unused',server_name='unused',login_port=29512,
                                 session_port=29513,ca_file=None,loopback_session_port=28513)
            def check(states):
                fixture=SimpleNamespace(names=['qaexamplea','qaexampleb'],snapshot_economy=lambda **kw:
                    dict(states=states,source_hashes=hashes,integrity='ok'))
                with patch('tools.verify_hosted_economy_tls.EconomyNetwork',side_effect=RuntimeError('no network invoked')) as network:
                    if states==[state,state]:
                        with self.assertRaisesRegex(RuntimeError,'no network invoked'):run_economy(fixture,args,{})
                        self.assertEqual(network.call_count,1)
                    else:
                        with self.assertRaises(AssertionError):run_economy(fixture,args,{})
                        self.assertFalse(network.called)
            check([state,state])
            for field,value in (('wallet',[3000,0]),('receipts',[dict(match_id='already-played')]),('checkpoints',1)):
                changed=copy.deepcopy(state);changed[field]=value;check([changed,state])
            for field,value in (('xp',1),('rank_points',-5),('hp',99)):
                changed=copy.deepcopy(state);changed['pets'][0][field]=value;check([changed,state])
            changed=copy.deepcopy(state);changed['pets'][0]['items'][1]['count']=49;check([changed,state])
        finally:path.unlink()


if __name__=='__main__':unittest.main()
