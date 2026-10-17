"""Local-only control/receipt/service guards for genuine hosted expiry QA."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import verify_hosted_mines_expiry as qa
from tests.test_shared_mines_qa import mine_fixture

def service():
    return dict(MainPID=123,NRestarts=0,ExecMainStartTimestampMonotonic='100',
                ActiveState='active',SubState='running')

def terminal(names,match='owned-match'):
    return dict(grace_seconds=180,checkpoint=None,
        durable={'battle_checkpoints':0,'battle_checkpoint_members':0,'battle_settlement_jobs':0},
        rewards=[dict(account=n,result=0,credits=0,gross=0,rental_tax=0) for n in names],
        mining_receipts=[dict(extractor=n,match_id=match,gross=0,tax=0,payouts={n:0}) for n in names],
        service=service(),failure_audit_rows=0)

def setup(names):
    return dict(states=[dict(wallet=[3050,0],receipts=[],pets=[dict(level=4,xp=7355,hp=115,max_hp=115,rank_points=0)]) for n in names]),dict(
        receipts=[],durable={'battle_checkpoints':0,'battle_checkpoint_members':0,'battle_settlement_jobs':0},
        clan=1,locations=[dict(account=n,town=13) for n in names],
        members=[dict(account=n) for n in (names[0],names[2])],amounts={**dict.fromkeys(names,0),'clan':0})

class ExpiryGuards(unittest.TestCase):
    def test_terminal_needs_real_grace_plus_ten_and_exact_three_receipts(self):
        names,_=mine_fixture();value=terminal(names)
        with self.assertRaisesRegex(AssertionError,'real grace'):qa.validate_terminal(value,names,'owned-match',180)
        self.assertEqual(qa.validate_terminal(value,names,'owned-match',190)['terminal_reward_receipts'],3)
        value['rewards'][2]['account']=names[1]
        with self.assertRaisesRegex(AssertionError,'three own'):qa.validate_terminal(value,names,'owned-match',190)

    def test_foreign_receipt_nonzero_reward_failure_audit_or_outbox_refused(self):
        names,_=mine_fixture()
        for mutate in (
            lambda r:r['mining_receipts'][0].update(extractor='other-player'),
            lambda r:r['mining_receipts'][0].update(match_id='other-match'),
            lambda r:r['rewards'][0].update(credits=1),
            lambda r:r.update(failure_audit_rows=1),
            lambda r:r['durable'].update(battle_settlement_jobs=1)):
            value=terminal(names);mutate(value)
            with self.assertRaises(AssertionError):qa.validate_terminal(value,names,'owned-match',190)

    def test_pid_restart_counter_and_start_timestamp_are_all_pinned(self):
        before=service()
        for key,value in [('MainPID',124),('NRestarts',1),('ExecMainStartTimestampMonotonic','101'),('ActiveState','failed')]:
            after={**before,key:value}
            with self.assertRaisesRegex(AssertionError,'restarted or stopped'):qa.validate_service(before,after)

    def test_old_played_trio_refused_without_network_or_mutation(self):
        names,_=mine_fixture();economy,status=setup(names)
        economy['states'][0]['pets'][0]['rank_points']=-20
        with self.assertRaisesRegex(AssertionError,'old played trio'):qa.validate_fresh(SimpleNamespace(names=names),economy,status)
        economy,status=setup(names);status['receipts']=[dict(gross=0)]
        with self.assertRaisesRegex(AssertionError,'prior missions'):qa.validate_fresh(SimpleNamespace(names=names),economy,status)

    def test_inspector_is_readonly_checks_cached_joined_owners_and_service(self):
        compile(qa.EXPIRY_READ,'local-expiry-inspection','exec')
        for statement in ('UPDATE ','INSERT ','DELETE ','systemctl restart','systemctl stop'):
            self.assertNotIn(statement,qa.EXPIRY_READ)
        for text in ('?mode=ro','Joined-owner durable cache incomplete','NRestarts','foreign==0','loads(payload,rebase=False)'):
            self.assertIn(text,qa.EXPIRY_READ)

    def test_no_login_or_game_command_after_all_sockets_drop_until_receipts_stable(self):
        names,state=mine_fixture();state['loading_complete']=True
        economy,status=setup(names);clock=[0.];events=[]
        fixture=SimpleNamespace(names=names,gate={'deadline_utc':(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()},
            guard_gate=lambda:events.append('gate'),guard_connections=lambda n:events.append(('connections',n)),
            status=lambda:deepcopy(status),snapshot_mine=lambda:deepcopy(state),preservation=lambda:{'integrity':'ok'})
        class Network:
            def __init__(self):self.peers={};self.closed=False;self.received={i:[b'\x41',b'\x35fake',b'\xb2\x0a\1'] for i in range(3)}
            def attach(self,i):
                self_outer.assertFalse(self.closed);events.append(('login',i));self.peers[i]=None
            def command(self,i,p):
                self_outer.assertFalse(self.closed);events.append(('command',i,p))
            def close(self):self.closed=True;events.append('close')
            def audit(self):return []
        self_outer=self;net=Network();net.fixture=fixture
        def read(f,match):
            events.append(('readonly',clock[0]));r=terminal(names)
            if match is None:return r
            if not net.closed or clock[0]<180:
                r['durable']={'battle_checkpoints':1,'battle_checkpoint_members':3,'battle_settlement_jobs':0}
                r['checkpoint']={'cache_accounts':names,'offline_remaining':dict.fromkeys(names,180)}
                r['rewards']=[];r['mining_receipts']=[]
            return r
        def sleep(seconds):clock[0]+=seconds
        report={}
        with patch.object(qa,'source_guard',return_value=economy),patch.object(qa,'make_network',return_value=net),\
             patch.object(qa,'sample',side_effect=read),patch.object(qa,'validate_wire_ground',return_value={'identical_clients':3}):
            qa.expiry_owned(fixture,SimpleNamespace(),report,clock=lambda:clock[0],sleep=sleep)
        self.assertTrue(report['passed']);self.assertGreaterEqual(clock[0],195)
        first_close=events.index('close')
        self.assertFalse(any(isinstance(e,tuple) and e[0] in ('login','command') for e in events[first_close:]))
        self.assertEqual([e for e in events if isinstance(e,tuple) and e[0]=='command'],
            [('command',0,b'\xb0\x14\1'),('command',2,b'\xb0\x14\3'),('command',1,b'\xb0\x14\2'),
             ('command',0,b'\x36'),('command',1,b'\x36'),('command',2,b'\x36')])
        self.assertEqual(report['service_before'],report['service_after'])

if __name__=='__main__':unittest.main()
