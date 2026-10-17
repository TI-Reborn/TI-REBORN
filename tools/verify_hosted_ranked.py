"""Two fresh real accounts over encrypted TCP; no bots or graphical-client claim."""
from verify_hosted_character_onboarding import *
from collections import deque
from contextlib import closing
import socket,subprocess,shlex,struct
from tio.protocol.battle_move import BattleMove,encode_move_request,decode_battle_move
from tio.protocol.battle_turn import encode_end_turn


def run(host):
    prefix='qt'+secrets.token_hex(4);names=[prefix+x for x in 'ab']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    report=dict(accounts=names,passed=False,checks=[],fixture='Only fresh QA accounts: level4, HP1000, Denver; artificial test fixture, not progression')
    output=ROOT/f'reports/ranked/hosted-{prefix}.json'
    def remote(code,payload=names):
        p=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),
            capture_output=True,text=True,encoding='utf-8')
        if p.returncode:raise RuntimeError(p.stderr)
        return p.stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        s=socket.create_connection((host,port),timeout=12);case.clients.append(s);return s
    case.connect=connect
    peers={};received={0:[],1:[]};turn=[False,False];scores=[0,0];outcomes={};positions={};ap={};ids={}
    def enter(i):
        peer=case.handoff(case.begin(names[i],passwords[i]));received[i]=[];original=peer.receive
        def receive():
            p=original();received[i].append(p)
            if p[:1]==b'\x38':turn[i]=True
            if p[:1]==b'\x39':turn[i]=False
            if p[:1]==b'\x4c':outcomes[i]=p[3]
            if p[:2]==b'\xc6\x16':
                values=struct.unpack('<7I',p[2:]);scores[:]=[values[2],values[5]]
            if p[:1]==b'\x3d':
                m=decode_battle_move(p)
                if m.actor_id==ids.get(i):positions[i]=m.path[-1]
            if p[:1]==b'\x4e' and int.from_bytes(p[1:5],'little')==ids.get(i) and int.from_bytes(p[9:13],'little')==10:ap[i]=int.from_bytes(p[13:17],'little')
            if p[:1]==b'\x3b' and int.from_bytes(p[5:9],'little')==1:
                from tio.protocol.battle_soldier import decode_battle_soldier
                a=decode_battle_soldier(p,human_equipment=True);ids[i]=a.soldier_id;positions[i]=a.position;ap[i]=a.fields['0x8c571d']
            return p
        peer.receive=receive;peers[i]=peer;case.enter(peer,names[i]);return peer
    def close_all():
        for s in case.clients:s.close()
        case.clients=[]
    def state():
        return json.loads(remote('''
import json,sys,sqlite3
from tio.battle_snapshot import loads
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m ON c.match_id=m.match_id WHERE m.account=?',(names[0],)).fetchone()
 assert row
 b=loads(row[0])[0]['battle'];f=b['field'];p=b['points']
 print(json.dumps(dict(match_id=b['match_id'],positions=p.positions,owners=p.owners,scores=p.scores,
  width=f.width,height=f.height,blocked=list(f.blocked),pending=b.get('point_turn_pending'),
  actors=[dict(id=a.actor_id,owner=a.owner_id,side=f.teams[a.owner_id],x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in f._actors.values()])))
'''))
    def ranks():
        return json.loads(remote('''
import json,sys,sqlite3
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 print(json.dumps(db.execute('SELECT account,skill,league,streak,wins,losses,draws FROM ranked_players WHERE account IN (?,?) ORDER BY account',names).fetchall()))
'''))
    def profile(i):
        peers[i].send(b'\x68\0'+names[i].encode()+b'\0')
        p=peers[i].until(b'\xa7\0');return struct.unpack('<IIQQ',p[-25:-1])
    def start():
        outcomes.clear();turn[:]=[False,False];scores[:]=[0,0]
        for i in (0,1):
            received[i]=[];peers[i].send(b'\xc6\x21'+bytes(2)+struct.pack('<III',1,1,0)+b'\0')
            if i==0:case.ping(peers[i])
        for i in (0,1):
            peers[i].until(b'\x41',max_packets=512);peers[i].send(b'\x36');case.ping(peers[i])
        time.sleep(.15)
        for p in peers.values():case.ping(p)
        return state()
    def finish():
        for i in (0,1):
            if i not in outcomes:peers[i].until(b'\x4c',max_packets=2048)
            case.ping(peers[i])
        rows=ranks();profiles=[profile(i) for i in (0,1)]
        for row,p in zip(rows,profiles):assert (row[1],row[2],row[3])==(p[0],p[1],p[3]) and p[2]>0,(rows,profiles)
        report.setdefault('matches',[]).append(dict(outcomes=dict(outcomes),scores=list(scores),ratings=rows,profiles=profiles))
        for p in peers.values():p.send(b'\x2a\1');case.ping(p)
        return rows
    def surrender(i):
        peers[i].send(b'\x2a\1');case.ping(peers[i])
        # Native exit returns directly to town; escaping has no 4C window.
        # The final independent SQLite receipt below verifies the loss.
        outcomes[i]=0
    try:
        remote('''
import json,sys
from server.accounts import Accounts
a=Accounts('/var/lib/tio-server/reservation.sqlite3')
for n,p in json.load(sys.stdin):
 assert n.startswith('qt') and len(n)==11
 a.create(n,p,character=n)
''',list(zip(names,passwords)))
        for i in (0,1):enter(i)
        close_all();time.sleep(1)
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.locations import LocationStore,center
names=json.load(sys.stdin)
assert len(names)==2 and all(n.startswith('qt') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n in names:
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c4aef':4}))
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(raw,n))
  LocationStore._save(db,n,2,*center(2))
''')
        for i in (0,1):enter(i)
        initial=start();match_ids=[initial['match_id']]
        assert len(initial['actors'])==2 and {a['side'] for a in initial['actors']}=={0,1}
        report['checks'].append('Two separate authenticated accounts matched in Denver, one fighter each, no bots; native C6 battle scene/flags/score received')
        blocked=set(map(tuple,initial['blocked']));target=tuple(initial['positions'][2]);width=initial['width'];height=initial['height']
        def route():
            start=positions[0]
            if sum(abs(a-b) for a,b in zip(start,target))<=2:return ()
            queue=deque([start]);previous={start:None}
            occupied={positions[1]}
            while queue:
                x,y=queue.popleft()
                for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if cell in previous or cell in blocked|occupied or not(0<=cell[0]<width and 0<=cell[1]<height):continue
                    previous[cell]=(x,y)
                    if sum(abs(a-b) for a,b in zip(cell,target))<=2:
                        result=[]
                        while cell!=start:result.append(cell);cell=previous[cell]
                        return tuple(reversed(result))
                    queue.append(cell)
            raise AssertionError('No path to center flag')
        resumed=False;captured=False
        for cycle in range(250):
            for i,p in list(peers.items()):case.ping(p)
            if outcomes:break
            current=next((i for i in (0,1) if turn[i]),None)
            if current is None:time.sleep(.12);continue
            p=peers[current]
            if current==0 and not captured:
                for attempt in range(20):
                    path=route()
                    if not path:captured=True;break
                    n=min(4,len(path),ap[0])
                    if not n:break
                    previous=positions[0];p.send(encode_move_request(BattleMove(ids[0],path[:n])));case.ping(p)
                    assert positions[0]!=previous,[(x.hex()) for x in received[0][-8:]]
                if captured and not resumed:
                    before=state();p.sock.close();time.sleep(1);p=enter(0)
                    assert any(x[:2]==b'\xc6\x16' for x in received[0])
                    after=state();assert before['scores']==after['scores'] and before['actors']==after['actors'] and before['owners']==after['owners']
                    p.send(b'\x36');case.ping(p);resumed=True
                    report['checks'].append('Center flag captured through TCP movement; reconnect retained exact flag ownership, scores, HP, AP and actor IDs')
            p.send(encode_end_turn());case.ping(p);time.sleep(.12)
        assert captured and resumed and outcomes,(captured,resumed,scores)
        terminal=state();assert all(a['hp']>0 for a in terminal['actors']),terminal
        assert outcomes.get(0)==1 and scores[0]==1000,(outcomes,scores)
        finish();report['checks'].append('Authoritative 1000-point victory while both fighters remained alive; public profile agrees with stored TrueSkill/league/place/streak')
        for attempt in (2,3):
            b=start();match_ids.append(b['match_id']);surrender(1);rows=finish()
        assert rows[0][2:6]==[2,3,3,0],rows
        report['checks'].append('Three consecutive wins promote bronze to silver and display a streak of 3')
        b=start();match_ids.append(b['match_id']);surrender(0);rows=finish()
        assert rows[0][3]==0 and rows[0][4:6]==[3,1] and rows[1][3]==1,rows
        report['checks'].append('Loss resets winning streak; surrender awards opponent; four matches update both accounts exactly once')
        report['receipts']=json.loads(remote('''
import json,sys,sqlite3
names,matches=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT account,match_id,result FROM battle_rewards WHERE account IN (?,?) ORDER BY match_id,account',names).fetchall()
 assert len(rows)==8 and len({r[1] for r in rows})==4
 assert db.execute('SELECT count(*) FROM ranked_matches WHERE match_id IN (?,?,?,?)',matches).fetchone()[0]==4
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',names).fetchone()
 assert not db.execute('SELECT 1 FROM battle_settlement_jobs WHERE account IN (?,?)',names).fetchone()
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 print(json.dumps(rows))
''',[names,match_ids]))
        close_all();time.sleep(1)
        remote('''
import json,sys,sqlite3
names,matches=json.load(sys.stdin)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for m in matches:
  row=db.execute('SELECT report FROM ranked_matches WHERE match_id=?',(m,)).fetchone()
  assert set(p[0] for t in json.loads(row[0])['teams'] for p in t)==set(names)
  db.execute('DELETE FROM ranked_matches WHERE match_id=?',(m,))
 for n in names:db.execute('DELETE FROM ranked_players WHERE account=?',(n,))
''',[names,match_ids])
        report['checks'].append('Only fresh QA rating entries removed afterward so test wins do not occupy the live leaderboard; original player rows untouched')
        report['passed']=True
    finally:
        close_all();output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':run(sys.argv[1])
