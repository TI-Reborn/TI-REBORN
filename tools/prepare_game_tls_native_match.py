"""Retain one owned two-human match for subsequent real native TLS validation.

Uses the original protocol through verified TLS for both channels. Existing
owned QA accounts only; no provisioning, direct sockets, purchases, equipment
changes or database writes. Only normal BA03 admission and battle-loaded36 are
sent. Successful completion disconnects without Leave so the server retains
its normal 180-second reconnect checkpoint for the real graphical clients.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.verify_game_tls_hosted import PREFLIGHT,TlsNetworkQA,require,tls_context
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP

SAFE_PREFLIGHT=PREFLIGHT.replace(" print(json.dumps(rows))", """
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account NOT IN (?,?)',names).fetchone(),'An unrelated active checkpoint exists'
 print(json.dumps(rows))""")
INVENTORY_DIGESTS=r'''
import hashlib,json,sqlite3,sys
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 print(json.dumps([hashlib.sha256(db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]).hexdigest() for n in names]))
'''


def prepare(args, fixture=None):
    from tio.protocol.battle_soldier import decode_battle_soldier
    fixture=fixture or FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host==args.host,'Fixture belongs to a different hosted endpoint')
    names=fixture.names[:2]
    require(len(names)==2,'Two independently owned accounts are required')
    fixture.remote(OWNERSHIP+'\nprint(json.dumps(dict(owned=True)))',fixture.ownership_payload())
    initial=fixture.remote(SAFE_PREFLIGHT,names)
    before=fixture.remote(INVENTORY_DIGESTS,names)
    network=TlsNetworkQA(fixture,args.host,args.server_name,args.login_port,args.session_port,
        tls_context(cafile=args.ca_file),local_session_port=args.loopback_session_port)
    report=dict(passed=False,kind='protocol-created retained match for subsequent real native TLS clients',
        ownership_checked=True,accounts_created=0,remote_database_writes_by_tool=0,
        purchases_requested=0,equipment_changes_requested=0,ui_actions_verified=False,
        initial=initial,checks=[])
    created=False
    try:
        keys=[network.begin(0),network.begin(1)]
        require(keys[0]!=keys[1],'Two same-origin accounts received the same handoff token')
        for index in (1,0):network.record_peer(index,network.handoff(keys[index]))
        for index in (0,1):network.command(index,b'\xba\x03\0\1')
        created=True
        grounds=[]
        own_ids=[]
        for index in (0,1):
            if b'\x41' not in network.received[index]:network.peers[index].until(b'\x41',max_packets=4096)
            packets=network.received[index]
            grounds.append(next(p for p in reversed(packets) if p.startswith(b'\x35')))
            own=[decode_battle_soldier(p,human_equipment=True) for p in packets
                if p.startswith(b'\x3b') and int.from_bytes(p[5:9],'little')==1]
            require(len(own)==1,'One native soldier must belong to each owned account')
            own_ids.append(own[0].soldier_id)
            network.command(index,b'\x36')
        require(grounds[0]==grounds[1] and own_ids[0]!=own_ids[1], 'Native scenes or identities differ')
        snapshot=fixture.snapshot(names)
        require(snapshot['bots']==0 and len(snapshot['actors'])==2 and
            {a['account'] for a in snapshot['actors']}==set(names), 'Match contains unrelated accounts or bots')
        require(snapshot['ground_sha256']==hashlib.sha256(grounds[0]).hexdigest(),'TLS scene differs from authoritative checkpoint')
        after=fixture.remote(INVENTORY_DIGESTS,names)
        require(after==before,'Normal admission changed saved inventories')
        report.update(snapshot=snapshot,inventory_sha256=after,humans=2,bots=0,
            native_actor_ids=own_ids,checks=['two real accounts authenticate over both verified TLS channels',
            'normal BA03 survival admission creates one authoritative two-human scene',
            'wire scene equals shared hosted checkpoint; saved inventories unchanged'])
        network.close()
        disconnected=datetime.now(timezone.utc)
        # Wait only for own socket closure to reach the backend; no Leave and
        # no checkpoint cleanup, DB mutation or relogin are requested.
        time.sleep(.6)
        retained=fixture.snapshot(names)
        require(retained['match']==snapshot['match'] and retained['ground_sha256']==snapshot['ground_sha256'] and
            retained['actors']==snapshot['actors'], 'Disconnect did not retain the identical authoritative match')
        report.update(passed=True,retained=retained,native_leave_requested=False,
            disconnected_utc=disconnected.isoformat(),reconnect_retention_seconds=180,
            reconnect_deadline_utc=datetime.fromtimestamp(disconnected.timestamp()+180,timezone.utc).isoformat(),
            limitations=['battle was created by protocol clients; real native UI creation is not proven',
                'queue readiness is transient server memory; database preflight checks active checkpoints',
                'native load, movement, chat and reconnect require separate actual client evidence'])
    except Exception as error:
        report['error_type']=type(error).__name__
        if created:
            for index in tuple(network.peers):
                try:network.command(index,b'\x2a\1')
                except Exception:pass
    finally:
        network.close()
        report['tls_channels']=[connection.metadata() for connection in network.connections]
        report['secrets_persisted']=False
        report['same_origin_local_ip']=len({c.channel.get('local_ip') for c in network.connections})==1
        if not all(not direction['plaintext_secret_found'] and direction['valid_tls_record_stream']
            for channel in report['tls_channels'] for direction in channel['wire'].values()):
            report['passed']=False
            report['wire_audit_failed']=True
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--host',default='185.184.42.88')
    parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512)
    parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513)
    parser.add_argument('--ca-file',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/game-tls/native-retained-match.json')
    args=parser.parse_args()
    for port in (args.login_port,args.session_port,args.loopback_session_port):require(1024<=port<=65535,'Invalid endpoint port')
    report=dict(passed=False,secrets_persisted=False)
    try:report=prepare(args)
    except Exception as error:report['error_type']=type(error).__name__
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],report=str(args.output),credentials_printed=False,
        disconnected_utc=report.get('disconnected_utc'),reconnect_deadline_utc=report.get('reconnect_deadline_utc'))))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
