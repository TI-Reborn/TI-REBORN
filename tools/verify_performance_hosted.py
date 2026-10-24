"""Two disposable ranking-excluded native TLS peers; no real account changes."""
import ast
import argparse
import json
from pathlib import Path
import secrets
import socket
import ssl
import statistics
import struct
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.protocol.arena import ArenaCreateRequest,encode_create_request
from tio.protocol.wagers import encode_join,decode_room_list
from tio.protocol.battle_members import decode_battle_members

SSH=['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','-o','ConnectTimeout=10','root@185.184.42.88']

PARTY_STATE=r'''
import sqlite3,json,hashlib
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 names=request;marks=','.join('?' for _ in names)
 groups=db.execute('SELECT id,state,town_id FROM travel_party_groups WHERE leader IN ('+marks+')',names).fetchall()
 result=dict(groups=groups,members=[],invitations=[],inventory={})
 for identity,state,town in groups:
  result['members']+=db.execute('SELECT owner,ready,online FROM travel_party_members WHERE party_id=? ORDER BY owner',(identity,)).fetchall()
  result['invitations']+=db.execute('SELECT id,target_owner FROM travel_party_invitations WHERE party_id=?',(identity,)).fetchall()
 result['locations']=db.execute('SELECT account,town_id FROM character_locations WHERE account IN ('+marks+') ORDER BY account',names).fetchall()
 result['wallets']=db.execute('SELECT account,credits,gold FROM wallets WHERE account IN ('+marks+') ORDER BY account',names).fetchall()
 result['contracts']=[dict(id=i,state=s,zone=json.loads(t)['zone_id']) for i,s,t in db.execute('SELECT id,state,template_json FROM pve_contract_instances WHERE leader IN ('+marks+')',names)]
 result['locks']=db.execute('SELECT owner,instance_id FROM pve_contract_locks WHERE owner IN ('+marks+') ORDER BY owner',names).fetchall()
 for account,pet,inventory in db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets WHERE account IN ('+marks+') ORDER BY account,pet_id',names):
  result['inventory'][account+':'+str(pet)]=hashlib.sha256(inventory).hexdigest()
 print(json.dumps(result))
'''

PARTY_CLEANUP=r'''
import sqlite3,json
from tio.travel_party import PartyStore
from tio.rating_visibility import QA_LOGIN
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE');marks=','.join('?' for _ in names)
 groups=db.execute('SELECT id FROM travel_party_groups WHERE leader IN ('+marks+')',names).fetchall()
 for identity, in groups:
  members={r[0] for r in db.execute('SELECT owner FROM travel_party_members WHERE party_id=?',(identity,))}
  assert members<=set(names),'Refuse cleanup of a group containing another player'
  assert not db.execute('SELECT 1 FROM pve_contract_instances WHERE party_id=?',(str(identity),)).fetchone(),'Unexpected QA contract'
  db.execute('DELETE FROM travel_party_journeys WHERE party_id=?',(str(identity),))
  PartyStore._delete_room(db,identity)
 print(json.dumps(dict(disposable_groups_removed=len(groups))))
'''

CONTRACT_CLEANUP=r'''
import sqlite3,json,hashlib
from tio.rating_visibility import QA_LOGIN
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 db.execute('BEGIN IMMEDIATE');marks=','.join('?' for _ in names)
 rows=db.execute('SELECT id,state,match_id FROM pve_contract_instances WHERE leader IN ('+marks+')',names).fetchall()
 tables=('pve_contract_events','pve_contract_requests','pve_contract_locks','pve_contract_members','pve_contract_awards','pve_contract_instances')
 for identity,state,match in rows:
  assert state!='active' and match is None,'Refuse cleanup of a started battle'
  owners={r[0] for r in db.execute('SELECT owner FROM pve_contract_members WHERE instance_id=?',(identity,))}
  assert owners and owners<=set(names),'Refuse cleanup involving another player'
  assert not db.execute('SELECT 1 FROM pve_contract_awards WHERE instance_id=?',(identity,)).fetchone(),'Unexpected QA reward'
  for table in tables:
   key='id' if table=='pve_contract_instances' else 'instance_id'
   def unrelated():return sorted(repr(tuple(r)) for r in db.execute('SELECT * FROM '+table+' WHERE '+key+'!=?',(identity,)))
   before=unrelated();db.execute('DELETE FROM '+table+' WHERE '+key+'=?',(identity,));assert unrelated()==before
 print(json.dumps(dict(disposable_contracts_removed=len(rows),unrelated_rows_preserved=True)))
'''

def remote(code,data):
    result=subprocess.run(SSH+['cd /opt/tio-emulator && .venv/bin/python -'],input='request='+repr(data)+'\n'+code,
        capture_output=True,encoding='utf-8',timeout=40)
    if result.returncode:raise RuntimeError('Hosted QA administration failed; private diagnostics suppressed')
    return json.loads(result.stdout)

def constants():
    # Reuse the audited exact-owner provisioning/cleanup SQL without importing
    # that older tool's candidate sys.path or running any of its service actions.
    tree=ast.parse((ROOT/'tools/verify_game_operations_hosted.py').read_text(encoding='utf-8'))
    values={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('FINGERPRINT','CREATE','CLEANUP'):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<audited-QA-SQL>','exec'),values)
    return values

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('label',choices=('before','after'))
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/server-performance-20261017')
    parser.add_argument('--party',action='store_true',help='Also verify private QA party commands and shared city arrival')
    parser.add_argument('--contracts',action='store_true',help='Verify QA contract accept/private markers/cancel; requires --party')
    parser.add_argument('--auction-read',action='store_true',help='Read native SC catalogue with both peers without placing bids')
    args=parser.parse_args();label=args.label
    if args.contracts and not args.party:parser.error('--contracts requires --party')
    args.report_dir.mkdir(parents=True,exist_ok=True)
    out=args.report_dir/('hosted-'+label+'.json')
    names=['qp'+secrets.token_hex(4)+suffix for suffix in ('a','b')]
    passwords=[secrets.token_hex(16) for _ in names]
    sql=constants();case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();report=dict(passed=False,protocol_clients=2,graphical_clients=False)
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=20)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def ask(peer,packet,expected=None):
        start=time.perf_counter();peer.send(packet)
        if packet!=b'\x70':peer.send(b'\x70')
        packets=[];fenced=False
        for _ in range(1024):
            reply=peer.receive()
            if reply==b'\x9e':fenced=True
            if reply[:5]==b'\xf0\x8a\x01\0\0':raise AssertionError('Native request rejected: '+reply[13:-2].decode('utf-16-le'))
            packets.append(reply)
            if fenced and (expected is None or any(expected(p) if callable(expected) else p.startswith(expected) for p in packets)):
                return packets,(time.perf_counter()-start)*1000
        raise AssertionError('Ping fence missing')
    provision=None
    try:
        provision=remote(sql['CREATE'],list(zip(names,passwords)))
        report['ranking_excluded']=provision['ranking_excluded']
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,34001+i,password=password));case.enter(peer,name)
            ask(peer,struct.pack('<Bii',0x1b,-154,-318));peers.append(peer)
        times=[]
        for i in range(10):
            _,ms=ask(peers[i%2],b'\xba\x01',b'\xc8\x2c');times.append(ms)
        packets,create_ms=ask(peers[0],encode_create_request(ArenaCreateRequest(1,0,4,2,40,1,1,0,0)),b'\x6c')
        assert any(p[:1]==b'\x6c' for p in packets)
        packets,_=ask(peers[1],b'\xba\x01',b'\xc8\x2c')
        rooms=decode_room_list(next(p for p in packets if p[:2]==b'\xc8\x2c'))
        room=next(r for r in rooms if r.creator_name==names[0].encode())
        packets,join_ms=ask(peers[1],encode_join(room.identity),b'\x25')
        records=decode_battle_members(next(p for p in reversed(packets) if p[:1]==b'\x25'))[2]
        assert {r.name for r in records}=={n.encode() for n in names}
        assert next(r for r in records if r.name==names[1].encode()).character_id==1
        assert next(r for r in records if r.name==names[0].encode()).character_id!=1
        packets,_=ask(peers[0],b'\x70',b'\x25')
        updates=[p for p in packets if p[:1]==b'\x25']
        assert updates
        own=decode_battle_members(updates[-1])[2]
        assert next(r for r in own if r.name==names[0].encode()).character_id==1
        ask(peers[0],b'\x2a\1')
        party_checks=[]
        if args.auction_read:
            from tio.protocol.sc_auction_view import decode as decode_sc
            before=remote(PARTY_STATE,names)['wallets']
            for peer in peers:
                packets,_=ask(peer,b'\xbd\1\0\0\0',b'\xf8\1\1')
                op,rows=decode_sc(next(p for p in packets if p.startswith(b'\xf8\1\1')))
                assert op==1 and rows
                ask(peer,b'\xbd\x12',b'\xf8\1\1')
            assert remote(PARTY_STATE,names)['wallets']==before
            party_checks+=['two native SC catalogues and refreshes without bids','viewing SC leaves QA balances unchanged']
        if args.party:
            def command(index,text):return ask(peers[index],b'\x21\0'+text.encode('utf-16-le')+b'\0\0',b'\x22')
            initial=remote(PARTY_STATE,names)
            command(0,'!party create')
            command(0,'!party invite '+names[1])
            state=remote(PARTY_STATE,names)
            invitation=next(identity for identity,target in state['invitations'] if target==names[1])
            command(1,'!party accept '+str(invitation))
            for i in (0,1):command(i,'!party ready')
            state=remote(PARTY_STATE,names)
            assert {m[0] for m in state['members']}==set(names) and all(m[1] and m[2] for m in state['members'])
            ask(peers[0],struct.pack('<Bii',0x1b,-154,-318))
            for i in (0,1):command(i,'!party status')
            state=remote(PARTY_STATE,names)
            assert len(state['groups'])==1 and state['groups'][0][1:]==['city',3]
            assert state['locations']==[[n,3] for n in sorted(names)]
            assert state['inventory']==initial['inventory']
            if args.contracts:
                from tio.protocol.town_info import decode_town_info
                command(0,'!contracts take camp');accepted=remote(PARTY_STATE,names)
                assert len(accepted['contracts'])==1 and accepted['contracts'][0]['state']=='accepted'
                assert {owner for owner,_ in accepted['locks']}==set(names)
                zone=accepted['contracts'][0]['zone']
                def target(peer,enabled):
                    def matches(p):return p[:2]==b'\xc8\x2d' and int.from_bytes(p[2:4],'little')==zone and decode_town_info(p).final_bool==enabled
                    packets,_=ask(peer,bytes((0x79,zone)),matches)
                    assert any(matches(p) for p in packets)
                for peer in peers:
                    target(peer,1)
                command(0,'!contracts cancel');cancelled=remote(PARTY_STATE,names)
                assert cancelled['contracts'][0]['state']=='cancelled' and not cancelled['locks']
                assert cancelled['wallets']==initial['wallets'] and cancelled['inventory']==initial['inventory']
                for peer in peers:
                    target(peer,0)
                party_checks+=['private contract accepted through TLS','both owners see enabled private target','cancel releases both locks and hides target','contract accept/cancel leaves balances and inventories unchanged']
            command(0,'!party disband')
            assert not remote(PARTY_STATE,names)['groups']
            party_checks+=['private party create/invite/accept through TLS','two accounts ready','shared same-city arrival and status','inventories unchanged','native party disband']
        report.update(passed=True,checks=['two TLS logins','list rooms','create shared lobby','join second real account',
            'private self IDs and shared peer IDs','creator receives joined roster','disband lobby']+party_checks,
            list_roundtrip_median_ms=statistics.median(times),list_roundtrip_max_ms=max(times),
            create_roundtrip_ms=create_ms,join_roundtrip_ms=join_ms)
    except BaseException:
        report['error']=traceback.format_exc()
        raise
    finally:
        for channel in case.clients:
            try:channel.close()
            except OSError:pass
        if provision is not None:
            time.sleep(1)
            if args.contracts:report['contract_cleanup']=remote(CONTRACT_CLEANUP,names)
            if args.party:report['party_cleanup']=remote(PARTY_CLEANUP,names)
            report['cleanup']=remote(sql['CLEANUP'],dict(names=names,protected_before=provision['protected_before'],require_unchanged_players=False))
        out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
