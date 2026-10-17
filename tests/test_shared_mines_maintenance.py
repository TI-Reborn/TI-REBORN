"""Local operational guard checks: real SQLite, source hashes and snapshot codec.

Every file is under TemporaryDirectory. nft/systemctl/ss are simulated; on
Windows flock/root ownership are shims, so these are not Linux permission or
firewall integration claims. The actual nft --check evidence is separate.
"""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tio.battle_checkpoints import schema as checkpoint_schema,save
from tio.battle_settlement import schema as outbox_schema
from tio.battle_snapshot import dumps,loads
from tio.clans import schema as clan_schema
from tio.mine_claims import schema as claim_schema
from server.accounts import Accounts
from tools.shared_mines_maintenance import Maintenance,PORTS,TTL,gate_shape,gate_expr,sha,canonical


class Host:
    def __init__(self,case):
        self.case=case;self.events=[];self.tables={};self.peers=[];self.active='active'
        self.foreign={'table':{'family':'ip','name':'filter','handle':1}}
        self.failure=None;self.callback=None;self.stop_callback=None

    def run(self,*args,input=None):
        self.events.append(args)
        if self.callback:self.callback(args)
        if self.failure and self.failure(args):
            self.failure=None;raise RuntimeError('Injected host operation failure')
        if args==('nft','-j','list','ruleset'):
            return canonical({'nftables':[copy.deepcopy(self.foreign)]+[v for data in self.tables.values() for v in data['nftables']]})
        if args[:4]==('nft','-j','list','table'):
            return canonical(self.tables[args[-1]])
        if args==('nft','-j','-f','-'):
            program=json.loads(input)['nftables'];table=program[0]['add']['table']['name']
            self.tables[table]={'nftables':[{kind:dict(value,handle=101+i)} for i,entry in enumerate(program) for kind,value in entry['add'].items()]}
            return ''
        if args[:3]==('nft','delete','table'):
            self.case.assertEqual(args[3],'inet');del self.tables[args[4]];return ''
        if args[0]=='ss':return '\n'.join(self.peers)
        if args[0]=='systemd-run':
            # A fired watchdog must always be able to read its immutable proof.
            folder=Path(args[-1]).parent
            self.case.assertTrue((folder/'proof.json').is_file());self.case.assertTrue((folder/'state.json').is_file())
            self.case.assertEqual(json.loads((folder/'state.json').read_text())['status'],'preparing')
            self.case.assertIn('--on-active='+str(TTL)+'s',args);return ''
        if args==('systemctl','stop','tio-server'):
            self.active='inactive';self.peers=[]
            if self.stop_callback:self.stop_callback()
            return ''
        if args==('systemctl','start','tio-server'):
            # Starting occurs while the exact gate is present and claim cleared.
            self.case.assertTrue(self.tables)
            with closing(sqlite3.connect(self.case.db)) as db:
                self.case.assertIsNone(self.case.m.claim_now(db)['owner_clan'])
            self.active='active';return ''
        if args==('systemctl','show','tio-server','-p','ActiveState','--value'):return self.active
        if args[0]=='systemctl' and (args[1]=='daemon-reload' or args[1]=='stop' and args[2].endswith('.timer')):return ''
        raise AssertionError('Unmocked host operation: '+repr(args))


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.root=Path(folder.name).resolve();self.db=self.root/'hosted.sqlite3'
        self.private=self.root/'private';self.dropins=self.root/'dropins'
        self.now=1000.;self.names=['qa_minea','qa_mineb','qa_minec']
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,{'fcntl':SimpleNamespace(LOCK_EX=1,LOCK_UN=2,flock=lambda *a:None)}).start()
        patch('server.accounts.ITERATIONS',1000).start()
        self.host=Host(self)
        self.m=Maintenance(database=self.db,private=self.private,dropins=self.dropins,
            runner=self.host.run,clock=lambda:self.now,strict_private=False)
        self.accounts=Accounts(self.db)
        self.accounts.create('realplayer','LocalFixtureAccountOnly')
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('CREATE TABLE wallets(account TEXT PRIMARY KEY,credits INTEGER,gold INTEGER)')
            db.execute("INSERT INTO wallets VALUES ('realplayer',123456,77)")
            clan_schema(db);claim_schema(db);checkpoint_schema(db);outbox_schema(db)
            db.execute('CREATE TABLE battle_rewards(match_id TEXT,account TEXT,PRIMARY KEY(match_id,account))')

    def activate(self):
        self.proof=self.m.activate(self.names,42001,42002);self.folder=Path(self.proof['lease_path']).parent
        self.lease=json.loads((self.folder/'lease.json').read_text());return self.proof

    def claim(self):
        for name in self.names:self.accounts.create(name,'LocalFixtureAccountOnly')
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('INSERT INTO clans(id,name,name_key,leader) VALUES (7,?,?,?)',(b'QA','qa',self.names[0]))
            db.executemany('INSERT INTO clan_members(account,clan_id,permissions) VALUES (?,7,0)',[(self.names[0],),(self.names[2],)])
            db.executemany('INSERT INTO wallets VALUES (?,3000,0)',[(n,) for n in self.names])
        self.assigned=self.m.claim(self.proof,7);return self.assigned

    def checkpoint(self,*,foreign=False,finished=False,paid=False,badclaim=False,quarantined=False):
        names=['realplayer'] if foreign else self.names
        sessions={i+1:{'account':n} for i,n in enumerate(names)}
        data=dict(kind='shared',battle=dict(kind='mine',city_id=13,match_id='qa-battle',finished=finished,
            mine_claim=dict(self.assigned,revision=999) if badclaim else self.assigned),
            sessions=sessions,retained={o:'completed' if finished else 'active' for o in sessions})
        with closing(sqlite3.connect(self.db)) as db,db:
            save(db,'qa-battle',dumps(data),{v['account']:o for o,v in sessions.items()},status='quarantined' if quarantined else 'finished' if finished else 'active')
            if paid:db.executemany('INSERT OR IGNORE INTO battle_rewards VALUES (?,?)',[('qa-battle',n) for n in names])

    def unowned(self):
        with closing(sqlite3.connect(self.db)) as db:return self.m.claim_now(db)['owner_clan']is None

    def preserved(self):
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT credits,gold FROM wallets WHERE account='realplayer'").fetchone(),(123456,77))
            self.assertEqual(db.execute("SELECT login FROM accounts WHERE login='realplayer'").fetchone(),('realplayer',))
            self.assertEqual([r[1] for r in db.execute('PRAGMA table_info(accounts)')],['login','salt','digest','iterations'])
        self.assertEqual(self.host.foreign,{'table':{'family':'ip','name':'filter','handle':1}})
        for file in self.private.rglob('*'):
            self.assertTrue(file.resolve().is_relative_to(self.root))
        for file in self.dropins.rglob('*'):
            self.assertTrue(file.resolve().is_relative_to(self.root))

    def test_exact_activation_proof_and_normal_release_preserve_players(self):
        self.activate();self.claim()
        self.assertEqual(self.proof['helper_path'],str(self.folder/'maintenance.py'))
        self.assertEqual(sha((self.folder/'maintenance.py').read_bytes()),self.proof['helper_sha256'])
        self.assertEqual(self.m.load(self.proof)[2]['status'],'isolated')
        result=self.m.finish(self.proof)
        self.assertEqual(result['status'],'released');self.assertFalse(result['database_restored'])
        self.assertTrue(self.unowned());self.assertFalse(self.host.tables);self.assertFalse(list(self.dropins.glob('*.conf')))
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events)
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT revision,owner_clan,tax_percent FROM mine_claim_history ORDER BY revision').fetchall(),[(1,7,10),(2,None,0)])
        self.preserved()

    def test_activation_failures_rollback_only_owned_artifacts(self):
        for stage in ('daemon-reload','systemd-run','nft-add','shape'):
            with self.subTest(stage=stage):
                self.host.failure=lambda a,s=stage: a==('systemctl','daemon-reload') if s=='daemon-reload' else a[0]=='systemd-run' if s=='systemd-run' else a==('nft','-j','-f','-') if s=='nft-add' else a[:4]==('nft','-j','list','table')
                with self.assertRaises((RuntimeError,KeyError)):self.m.activate(self.names,42001,42002)
                self.assertFalse(self.host.tables);self.assertFalse(list(self.dropins.glob('*.conf')))
                states=[json.loads(p.read_text())['status'] for p in self.private.glob('*/state.json')]
                self.assertTrue(all(s=='activation-aborted' for s in states));self.assertTrue(self.unowned())
        self.preserved()

    def test_raced_connection_activation_rolls_back_before_any_claim(self):
        count=0
        def race(args):
            nonlocal count
            if args[0]=='ss':
                count+=1
                if count==2:self.host.peers=['0 0 185.184.42.88:29513 192.0.2.1:30000']
        self.host.callback=race
        with self.assertRaisesRegex(ValueError,'Foreign game'):self.m.activate(self.names,42001,42002)
        self.assertFalse(self.host.tables);self.assertFalse(list(self.dropins.glob('*.conf')));self.preserved()

    def test_battle_racing_after_gate_is_preserved_and_activation_aborted(self):
        def race(args):
            if args==('nft','-j','-f','-'):
                with closing(sqlite3.connect(self.db)) as db,db:
                    save(db,'foreign-accepted-before-gate',dumps(dict(kind='private')),{'realplayer':123})
        self.host.callback=race
        with self.assertRaisesRegex(ValueError,'Unfinished battle'):self.m.activate(self.names,42001,42002)
        self.assertFalse(self.host.tables);self.assertFalse(list(self.dropins.glob('*.conf')))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT match_id FROM battle_checkpoints').fetchone(),('foreign-accepted-before-gate',))
        self.preserved()

    def test_claim_racing_activation_keeps_gate_and_guard_for_attention(self):
        def race(args):
            if args==('nft','-j','-f','-'):
                from tio.mine_claims import MineClaimsStore
                MineClaimsStore(self.db).admin_set_claim(13,None,tax_percent=0,expected_revision=0,
                    actor='other-operator',reason='Explicit concurrent operation in local fixture')
        self.host.callback=race
        with self.assertRaisesRegex(ValueError,'Checkpoint raced'):self.m.activate(self.names,42001,42002)
        self.assertTrue(self.host.tables);self.assertTrue(list(self.dropins.glob('*.conf')))
        self.assertEqual(json.loads(next(self.private.glob('*/state.json')).read_text())['status'],'attention')
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(self.m.claim_now(db)['revision'],1)
        self.preserved()

    def test_verification_rejects_tampered_proof_expiry_and_gate(self):
        self.activate()
        for field,value in [('lease_sha256','0'*64),('helper_sha256','0'*64),('helper_path',str(self.root/'other.py'))]:
            with self.subTest(field=field),self.assertRaises(ValueError):self.m.load(dict(self.proof,**{field:value}))
        self.now+=TTL
        with self.assertRaisesRegex(ValueError,'expired'):self.m.load(self.proof)
        self.now-=TTL
        original=copy.deepcopy(self.host.tables)
        entry=self.host.tables[self.proof['gate_table']]['nftables']
        entry.append(copy.deepcopy(entry[-1]))
        with self.assertRaisesRegex(ValueError,'exactly one'):self.m.load(self.proof)
        self.host.tables=copy.deepcopy(original);self.host.tables[self.proof['gate_table']]['nftables'][0]['table']['flags']=['dormant']
        with self.assertRaisesRegex(ValueError,'flags'):self.m.load(self.proof)
        self.host.tables=copy.deepcopy(original);self.host.tables[self.proof['gate_table']]['nftables'][-1]['rule']['handle']+=1
        with self.assertRaisesRegex(ValueError,'handles'):self.m.load(self.proof)
        self.host.tables=copy.deepcopy(original);self.host.foreign['table']['handle']+=1
        with self.assertRaisesRegex(ValueError,'Foreign firewall'):self.m.load(self.proof)
        self.host.foreign['table']['handle']-=1;self.host.tables={}
        with self.assertRaisesRegex(ValueError,'gate missing'):self.m.load(self.proof)

    def test_watchdog_finishes_only_paid_owned_result_then_clears_and_reopens(self):
        self.activate();self.claim();self.checkpoint()
        self.host.peers=['0 0 127.0.0.1:29513 127.0.0.1:50000']*3
        self.host.stop_callback=lambda:self.checkpoint(finished=True,paid=True)
        self.now+=TTL+1  # Only cleanup may use an expired lease.
        result=self.m.finish(self.proof,watchdog=True)
        self.assertEqual(result['status'],'released');self.assertTrue(self.unowned());self.assertFalse(self.host.tables)
        self.assertLess(self.host.events.index(('systemctl','stop','tio-server')),self.host.events.index(('systemctl','start','tio-server')))
        self.assertLess(self.host.events.index(('systemctl','start','tio-server')),self.host.events.index(('nft','delete','table','inet',self.proof['gate_table'])))
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_rewards').fetchone()[0],3)
        self.preserved()

    def test_foreign_or_changed_claim_rejects_watchdog_before_stop(self):
        self.activate();self.claim()
        for bad in ('foreign','badclaim','quarantined'):
            with self.subTest(bad=bad):
                self.checkpoint(**{bad:True})
                with self.assertRaises(ValueError):self.m.finish(self.proof,watchdog=True)
                self.assertNotIn(('systemctl','stop','tio-server'),self.host.events);self.assertTrue(self.host.tables)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('DELETE FROM battle_checkpoints');db.execute('DELETE FROM battle_checkpoint_members')
            db.execute('UPDATE mine_claims SET revision=123 WHERE location=13')
        with self.assertRaisesRegex(ValueError,'ownership raced'):self.m.finish(self.proof,watchdog=True)
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events);self.assertTrue(self.host.tables);self.preserved()

    def test_watchdog_never_deletes_unfinished_or_unpaid_checkpoint(self):
        self.activate();self.claim();self.checkpoint(finished=True,paid=False)
        with self.assertRaisesRegex(ValueError,'committed receipt'):self.m.finish(self.proof,watchdog=True)
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events)
        self.checkpoint(finished=False,paid=False)
        self.host.stop_callback=lambda:self.checkpoint(finished=True,paid=False)
        with self.assertRaisesRegex(ValueError,'committed receipt'):self.m.finish(self.proof,watchdog=True)
        self.assertTrue(self.host.tables);self.assertFalse(self.unowned());self.assertEqual(self.host.active,'inactive')
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],1)
        self.preserved()

    def test_orphan_members_or_foreign_outbox_blocks_release(self):
        self.activate();self.claim()
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("INSERT INTO battle_checkpoint_members VALUES ('realplayer','orphan',123)")
        with self.assertRaises(ValueError):self.m.finish(self.proof,watchdog=True)
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events)
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('DELETE FROM battle_checkpoint_members')
            db.execute('INSERT INTO battle_settlement_jobs(match_id,account,payload) VALUES (?,?,?)',('other','realplayer',canonical(dict(kwargs={}))))
        with self.assertRaisesRegex(ValueError,'Foreign settlement'):self.m.finish(self.proof,watchdog=True)
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events);self.assertTrue(self.host.tables);self.preserved()

    def test_foreign_socket_and_foreign_clan_member_block_before_stop(self):
        self.activate();self.claim()
        self.host.peers=['0 0 185.184.42.88:29513 203.0.113.3:50123']
        with self.assertRaisesRegex(ValueError,'Foreign game'):self.m.finish(self.proof,watchdog=True)
        self.host.peers=[]
        with closing(sqlite3.connect(self.db)) as db,db:db.execute("INSERT INTO clan_members(account,clan_id,permissions) VALUES ('realplayer',7,0)")
        with self.assertRaisesRegex(ValueError,'foreign ownership'):self.m.finish(self.proof,watchdog=True)
        self.assertNotIn(('systemctl','stop','tio-server'),self.host.events);self.assertTrue(self.host.tables);self.preserved()

    def test_failed_gate_delete_retry_never_reassigns_owner(self):
        self.activate();self.claim()
        self.host.failure=lambda a:a[:3]==('nft','delete','table')
        with self.assertRaises(RuntimeError):self.m.finish(self.proof)
        self.assertTrue(self.unowned());self.assertTrue(self.host.tables);self.assertFalse(list(self.dropins.glob('*.conf')))
        self.assertEqual(json.loads((self.folder/'state.json').read_text())['status'],'attention')
        self.assertEqual(self.m.finish(self.proof)['status'],'released')
        with closing(sqlite3.connect(self.db)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM mine_claim_history').fetchone()[0],2)
        self.preserved()

    def test_real_shared_journal_finished_result_is_eligible_for_owned_cleanup(self):
        # Native 2A01 on a real journaled mine produces status='finished', not
        # active. This regression detects an operational guard rejecting the
        # authoritative result format before its safe metadata-only cleanup.
        with patch.object(sys,'path',[str(Path(__file__).parent),*sys.path]):
            from tests.test_shared_mine_arena import SharedMineArenaTests
            case=SharedMineArenaTests();case.setUp();self.addCleanup(case.doCleanups)
            battle=case.enter(indices=(0,));case.move_to_exit(battle,0);case.send(0,b'\x2a\x01')
        names=[s.account for s in case.case.sessions[:3]]
        with closing(sqlite3.connect(case.path)) as db,db:
            self.assertEqual(db.execute('SELECT status FROM battle_checkpoints').fetchone(),('finished',))
            reward_rows=db.execute('SELECT * FROM battle_rewards').fetchall()
            self.assertTrue(reward_rows)
            self.m.pending(db,names,claim=case.claim)
            self.m.remove_finished_qa_checkpoints(db,names)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_checkpoints').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM battle_checkpoint_members').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT * FROM battle_rewards').fetchall(),reward_rows)


if __name__=='__main__':unittest.main()
