"""Retire only the expected owned QA match through ordinary verified TLS Leave.

Close both real native clients first. This authenticates only existing proven
owned QA accounts, reloads their expected two-human retained battle, then sends
normal Leave2A01 for both. No direct sockets, provisioning or database writes.
Normal battle settlement can change these QA accounts' results/rewards.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_game_tls_hosted import TlsNetworkQA,require,tls_context
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP

AFTER=r'''
import json,sqlite3,sys
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT count(*) FROM battle_checkpoint_members WHERE account IN (?,?)',names).fetchone()[0]
 print(json.dumps(dict(own_checkpoint_members_remaining=rows)))
'''


def retire(args, fixture=None):
    fixture=fixture or FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host==args.host,'Fixture belongs to another hosted endpoint')
    names=fixture.names[:2]
    fixture.remote(OWNERSHIP+'\nprint(json.dumps(dict(owned=True)))',fixture.ownership_payload())
    before=fixture.snapshot(names)
    require(before['match']==args.expected_match and before['bots']==0 and len(before['actors'])==2 and
        {a['account'] for a in before['actors']}==set(names),'Only the exact owned two-human match may be retired')
    report=dict(passed=False,expected_match=args.expected_match,ownership_checked=True,
        ui_actions_verified=False,accounts_created=0,remote_database_writes_by_tool=0,
        kind='normal protocol cleanup of expected owned QA match over verified TLS')
    network=TlsNetworkQA(fixture,args.host,args.server_name,args.login_port,args.session_port,
        tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    try:
        for index in (0,1):
            network.enter(index)
            if b'\x41' not in network.received[index]:network.peers[index].until(b'\x41',max_packets=4096)
            network.command(index,b'\x36')
        current=fixture.snapshot(names)
        require(current['match']==args.expected_match and current['bots']==0 and
            {a['account'] for a in current['actors']}==set(names),'Owned retained match changed before Leave')
        for index in (0,1):network.command(index,b'\x2a\1')
        after=fixture.remote(AFTER,names)
        require(after['own_checkpoint_members_remaining']==0,'Normal Leave did not retire both owned checkpoints')
        report.update(passed=True,after=after,native_leave_packets_sent=2,
            normal_qa_battle_settlement_requested=True,completed_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:report['error_type']=type(error).__name__
    finally:
        network.close()
        report['tls_channels']=[connection.metadata() for connection in network.connections]
        report['secrets_persisted']=False
        if not all(not d['plaintext_secret_found'] and d['valid_tls_record_stream']
            for c in report['tls_channels'] for d in c['wire'].values()):
            report.update(passed=False,wire_audit_failed=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--expected-match',required=True)
    parser.add_argument('--host',default='185.184.42.88')
    parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512)
    parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513)
    parser.add_argument('--ca-file',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/game-tls/native-match-cleanup.json')
    args=parser.parse_args()
    for port in (args.login_port,args.session_port,args.loopback_session_port):require(1024<=port<=65535,'Invalid endpoint port')
    report=dict(passed=False,secrets_persisted=False)
    try:report=retire(args)
    except Exception as error:report['error_type']=type(error).__name__
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False)))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
