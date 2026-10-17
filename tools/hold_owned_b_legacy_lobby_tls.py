"""One owned B TLS actor for real A/C GUI capacity checks; control-file commands only.

Allowed operations: status, join an observed ordinary A group, leave, cleanup.
Never creates a lobby, sends ready/start, hires, changes inventory or writes SQL.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_legacy_lobbies_hosted import LobbyTlsQA
from tools.verify_game_tls_hosted import require,tls_context,login_preface
from tools.verify_hosted_arena_surroundings import FreshSurroundingsQA,OWNERSHIP
from tio.protocol.arena import decode_room_list as decode_ba02
from tio.protocol.wagers import decode_room_list as decode_c82c,encode_join
from tio.protocol.battle_members import decode_battle_members

DEFAULT_RUN=ROOT/'reports/gameplay-completion/legacy-status-20261011/gui/b-headless-lobby'
INDEX=1

PREFLIGHT=OWNERSHIP+r'''
from tio.protocol.pet_info import decode_pet_info
import hashlib
owner=names[1];assert names==['qs3110ad96'+c for c in'abcd']
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(owner,)).fetchone()
 assert not db.execute('SELECT 1 FROM battle_settlement_jobs WHERE account=?',(owner,)).fetchone()
 assert db.execute('SELECT COUNT(*) FROM characters WHERE account=?',(owner,)).fetchone()[0]==1
 assert db.execute('SELECT town_id FROM character_locations WHERE account=?',(owner,)).fetchone()[0]==3
 pets=[]
 for identity,human,packet,inventory in db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id',(owner,)):
  f=decode_pet_info(packet,human_equipment=bool(human)).fields
  pets.append(dict(pet_id=identity,level=f['0x8c4aef'],xp=f['0x8c4b05'],selected=f['0x8c44a6'],inventory_sha256=hashlib.sha256(inventory).hexdigest()))
 assert any(1<=p['level']<=3 for p in pets)
 print(json.dumps(dict(account=owner,ownership_verified=True,read_only=True,pets=pets,own_checkpoint_members=0,own_settlements=0,accounts_count=db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0])))
'''

def utc():return datetime.now(timezone.utc).isoformat()

def json_atomic(path,value):
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)

class ActorNetwork(LobbyTlsQA):
    """Existing exact TLS flow; shared GUI peers are allowed to be online."""
    def begin(self,index):
        require(index==INDEX,'This helper may authenticate only owned fixture B')
        from test_server_deployment import Peer
        from tio.protocol.transport import (decode_initial_challenge,expected_reply_fields,InitialReply,
            encode_initial_reply,decode_initial_completion)
        from tio.protocol.login import BasicLoginRequest,encode_basic_login_request,transform_auth_value
        from tio.protocol.server_list import ServerListRequest,encode_server_list_request,decode_server_list
        from tio.protocol.server_login import ServerLoginRequest,encode_server_login_request
        conn=self.connect(self.login_port,label='login');conn.sendall(login_preface(self.local_session_port));peer=Peer(conn)
        fields=expected_reply_fields(decode_initial_challenge(peer.receive()))
        peer.send(encode_initial_reply(InitialReply(*fields,0,bytes(3))))
        token=decode_initial_completion(peer.receive()).unknown_u32_01
        conn.capture_next_write=True
        peer.send(encode_basic_login_request(BasicLoginRequest(self.fixture.names[index].encode(),self.fixture.passwords[index].encode(),transform_auth_value(token))))
        require(peer.receive()==b'\x04\0','Owned B TLS login failed')
        peer.send(encode_server_list_request(ServerListRequest(0,0,b'')))
        entries=decode_server_list(peer.receive()).entries
        require(len(entries)==1,'Expected one hosted backend')
        entry=entries[0]
        require(entry.address_octets==socket.inet_aton('127.0.0.1') and entry.unknown_u16_01==self.local_session_port,'TLS loopback route advertisement differs')
        self.advertised_online=entry.unknown_u16_02
        peer.send(encode_server_login_request(ServerLoginRequest(1,bytes(8))))
        require(peer.receive()==b'\x08\0','Owned B TLS handoff preparation failed')
        conn.close();return fields[1],token

class Actor:
    def __init__(self,network,run):
        self.network=network;self.run=run;self.joined=None;self.commands=[];self.rows=[];self.ba_rows=[]
        self.events=[];self.exit_requested=False;self.packet_counts=Counter()
        self.report=dict(kind='One owned headless B through verified native TLS; GUI operated independently',account=network.fixture.names[INDEX],
                         started_utc=utc(),pid=__import__('os').getpid(),authenticated=False,connected=False,
                         accounts_created=0,administrative_db_writes=0,lobbies_created=0,ready_packets_sent=0,start_packets_sent=0,
                         foreign_join_requested=False,password_logged=False,graphical_clients_started=0,joined_room=None)

    def event(self,name,**extra):
        self.events.append(dict(utc=utc(),event=name,**extra));self.events=self.events[-100:]

    def publish(self):
        self.report.update(connected=not self.exit_requested,observed_utc=utc(),joined_room=self.joined,rooms=self.rows,
                           ba02_rooms=self.ba_rows,commands=self.commands[-50:],events=self.events,tls_channels=[c.metadata() for c in self.network.connections],
                           received_packet_prefix_counts=dict(self.packet_counts))
        json_atomic(self.run/'status.json',self.report)

    def collect(self,replies):
        for packet in replies:self.packet_counts[packet[:2].hex()]+=1
        for packet in replies:
            if packet.startswith(b'\x35') or packet.startswith(b'\x41'):
                raise AssertionError('Unexpected battle scene; headless lobby actor must stop')
            if packet.startswith(b'\xf0\x18\0\0\0'):
                self.event('server_cleared_owned_membership',previous_room=self.joined);self.joined=None

    def command(self,packet):
        # Wire command boundary is intentionally closed: no raw CLI packet input.
        allowed=packet in (b'\xba\x01',b'\x2a\x01') or packet[:1]==b'\x29' and len(packet)==5
        require(allowed,'Packet is outside the bounded lobby helper command set')
        replies=self.network.command(INDEX,packet);self.collect(replies);return replies

    def listing(self):
        replies=self.command(b'\xba\x01')
        for prefix in (b'\xba\x02',b'\xc8\x2c'):
            if not any(p.startswith(prefix) for p in replies):replies.append(self.network.peers[INDEX].until(prefix,max_packets=4096))
        self.collect(replies)
        legacy=decode_ba02(next(p for p in reversed(replies) if p.startswith(b'\xba\x02')))
        typed=decode_c82c(next(p for p in reversed(replies) if p.startswith(b'\xc8\x2c')))
        names={n.encode() for n in self.network.fixture.names}
        self.ba_rows=[dict(identity=r.unknown_u32_00,mode=r.category,name=r.name.split(b' \xb7 ',1)[0].decode('cp1251'),label=r.name.decode('cp1251'),
                           members=r.unknown_u8_1d,capacity=r.unknown_u8_1c,status=r.unknown_u8_1e,
                           low=r.unknown_u8_1a,high=r.unknown_u8_1b,soldiers=r.unknown_u8_18) for r in legacy
                      if r.category in (1,4) and r.name.split(b' \xb7 ',1)[0] in names]
        self.rows=[]
        for r in typed:
            creator=r.creator_name.split(b' \xb7 ',1)[0]
            if r.mode not in (1,4) or creator not in names:continue
            self.rows.append(dict(identity=r.identity,mode=r.mode,creator=creator.decode('cp1251'),label=r.creator_name.decode('cp1251'),capacity=r.capacity,
                                 members=r.members,status=r.status,stake=r.stake,soldiers=r.soldiers,creator_level=r.creator_level,level_delta=r.level_delta))
        self.report['foreign_rooms_omitted']=len(typed)-len(self.rows)
        self.event('native_ba01_ba02_c82c_listing',owned_rows=len(self.rows),ba02_sha256=hashlib.sha256(next(p for p in reversed(replies) if p.startswith(b'\xba\x02'))).hexdigest(),
                   c82c_sha256=hashlib.sha256(next(p for p in reversed(replies) if p.startswith(b'\xc8\x2c'))).hexdigest())
        return self.rows

    def join(self,request):
        require(self.joined is None,'B must leave its prior group before another join')
        rows=self.listing();mode=request.get('mode',1);require(mode in (1,4),'Only ordinary Team/Wall may be joined')
        matches=[r for r in rows if r['creator']==self.network.fixture.names[0] and r['mode']==mode and r['stake']==0 and r['status']==0 and r['members']<r['capacity']]
        if 'room_id' in request:matches=[r for r in matches if r['identity']==request['room_id']]
        require(len(matches)==1,'Expected exactly one observed free ordinary A group')
        room=matches[0]
        require(room['capacity']==(2 if mode==1 else 4),'Observed group capacity differs')
        require(any(r['identity']==room['identity'] and r['name']==self.network.fixture.names[0] and r['mode']==mode and
                    r['capacity']==room['capacity'] and r['members']==room['members'] and r['status']==0 for r in self.ba_rows),
                'Observed A group differs between original BA02 and typed C82C listing')
        replies=self.command(encode_join(room['identity']))
        if not any(p.startswith(b'\x25') for p in replies):replies.append(self.network.peers[INDEX].until(b'\x25',max_packets=4096))
        _,_,members=decode_battle_members(next(p for p in reversed(replies) if p.startswith(b'\x25')))
        actual={m.name.decode('cp1251') for m in members};allowed=set(self.network.fixture.names)
        require(actual<=allowed and self.network.fixture.names[0] in actual and self.network.fixture.names[INDEX] in actual,'Joined member roster differs from owned A/B group')
        self.joined=room['identity'];self.report['joined_members']=[dict(account=m.name.decode('cp1251'),level=m.level,ready=m.ready) for m in members]
        self.event('original_29_joined_owned_a',room=room['identity'],mode=mode,members=len(members),capacity=room['capacity'])
        self.listing()
        occupied=next((r for r in self.rows if r['identity']==self.joined),None)
        require(occupied is not None and occupied['members']==len(members),'Authoritative list did not reflect owned B join')
        self.report['join_verified']=True

    def leave(self):
        if self.joined is None:self.event('leave_no_membership');return
        previous=self.joined;replies=self.command(b'\x2a\x01')
        if not any(p.startswith(b'\xf0\x18\0\0\0') for p in replies):
            replies.append(self.network.peers[INDEX].until(b'\xf0\x18\0\0\0',max_packets=4096))
        self.collect(replies);self.joined=None;self.event('original_2a_left_owned_group',room=previous);self.listing()

    def control(self,request):
        require(isinstance(request,dict) and set(request)<= {'id','action','room_id','mode'},'Unknown control fields')
        action=request.get('action');require(action in ('status','join-owned-a','leave','cleanup'),'Unknown control action')
        result=dict(id=request.get('id'),action=action,started_utc=utc(),passed=False)
        try:
            if action=='status':self.listing()
            elif action=='join-owned-a':self.join(request)
            elif action=='leave':self.leave()
            else:self.leave();self.exit_requested=True
            result['passed']=True
        except (AssertionError,OSError,EOFError,ValueError) as error:
            result.update(error_type=type(error).__name__,reason=str(error)[:180])
        result['completed_utc']=utc();self.commands.append(result);self.publish()

def run(args):
    fixture=FreshSurroundingsQA.load_private(args.fixture)
    require(fixture.host==args.host=='185.184.42.88' and fixture.prefix=='qs3110ad96','Only the proven owned hosted fixture is supported')
    require(not args.run_dir.exists(),'Use a fresh bounded run directory')
    args.run_dir.mkdir(parents=True)
    controls=args.run_dir/'controls.jsonl';controls.write_text('',encoding='utf-8')
    initial=fixture.remote(PREFLIGHT,fixture.ownership_payload());json_atomic(args.run_dir/'preflight.json',initial)
    network=ActorNetwork(fixture,args.host,args.server_name,args.login_port,args.session_port,tls_context(),local_session_port=args.loopback_session_port)
    actor=Actor(network,args.run_dir);actor.report['preflight']=initial
    started=time.monotonic();offset=0;last_poll=0
    try:
        network.enter(INDEX);actor.report.update(authenticated=True,advertised_online=network.advertised_online)
        actor.event('owned_b_authenticated_over_verified_tls');actor.listing();actor.publish()
        print(json.dumps(dict(ready=True,account=fixture.names[INDEX],pid=actor.report['pid'],status=str(args.run_dir/'status.json'),controls=str(controls))),flush=True)
        while not actor.exit_requested and time.monotonic()-started<args.max_seconds:
            with controls.open(encoding='utf-8-sig') as reader:
                reader.seek(offset)
                while True:
                    line=reader.readline()
                    if not line:break
                    if not line.endswith('\n'):break
                    offset=reader.tell()
                    if line.strip():actor.control(json.loads(line))
                    if actor.exit_requested:break
            if not actor.exit_requested and time.monotonic()-last_poll>=2:
                actor.listing();actor.publish();last_poll=time.monotonic()
                network.received[INDEX]=network.received[INDEX][-256:]
            time.sleep(.1)
        if not actor.exit_requested:actor.event('bounded_deadline_reached');actor.leave();actor.exit_requested=True
    except (AssertionError,OSError,EOFError,ValueError) as error:
        actor.report.update(error_type=type(error).__name__,reason=str(error)[:180]);actor.event('actor_failed')
    finally:
        if actor.joined is not None:
            try:actor.leave()
            except (AssertionError,OSError,EOFError,ValueError) as error:actor.report['cleanup_error_type']=type(error).__name__
        network.close();actor.exit_requested=True;actor.report.update(connected=False,terminated_utc=utc());actor.publish()
        json_atomic(args.run_dir/'final.json',actor.report)
    return 0 if actor.report.get('authenticated') and 'error_type' not in actor.report else 1

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=ROOT/'reports/arena-surroundings/private/qs3110ad96.json')
    parser.add_argument('--run-dir',type=Path,default=DEFAULT_RUN)
    parser.add_argument('--host',default='185.184.42.88');parser.add_argument('--server-name',default='ti-reborn.com')
    parser.add_argument('--login-port',type=int,default=29512);parser.add_argument('--session-port',type=int,default=29513)
    parser.add_argument('--loopback-session-port',type=int,default=28513)
    parser.add_argument('--max-seconds',type=int,default=1800)
    args=parser.parse_args();require(30<=args.max_seconds<=1800,'Use a bounded 30–1800 second run')
    return run(args)

if __name__=='__main__':raise SystemExit(main())
