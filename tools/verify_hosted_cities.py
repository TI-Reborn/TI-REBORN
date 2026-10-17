"""Fresh authenticated accounts over public TCP; graphical clients not exercised."""
from verify_hosted_character_onboarding import *
from collections import deque
import shlex,socket,struct,subprocess
from tio.protocol.city_catalogs import decode_pet_shop,decode_item_shop
from tio.protocol.shop_purchase import ShopPurchase,encode_shop_purchase
from tio.protocol.hire import encode_hire_request
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_turn import encode_end_turn
from tio.protocol.battle_attack import AttackRequest,encode_attack_request


def run(host):
    prefix='qy'+secrets.token_hex(4);names=[prefix+c for c in 'ab']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    folder=ROOT/'reports/cities';folder.mkdir(parents=True,exist_ok=True)
    report=dict(accounts=names,passed=False,checks=[],matches=[],fixture='Only fresh QA accounts: level4, HP1000; native shops/hire/movement/combat, no seeded opponent or result')
    def remote(code,payload=names):
        r=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@'+host,
            'cd /opt/tio-emulator && .venv/bin/python -c '+shlex.quote(code)],input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8')
        if r.returncode:raise RuntimeError(r.stderr)
        return r.stdout
    case=MultiAccountTests();case.config=SimpleNamespace(game_port=28512,session_port=28513);case.clients=[]
    def connect(port):
        s=socket.create_connection((host,port),timeout=15);case.clients.append(s);return s
    case.connect=connect;peers={};received={0:[],1:[]}
    def enter(i):
        peer=case.handoff(case.begin(names[i],passwords[i]));original=peer.receive;received[i]=[]
        def receive():
            p=original();received[i].append(p);return p
        peer.receive=receive;peers[i]=peer;case.enter(peer,names[i]);return peer
    def close():
        for s in case.clients:s.close()
        case.clients=[]
    def command(i,p):
        received[i]=[];peers[i].send(p);case.ping(peers[i]);return received[i]
    def last(i,head):
        return next(p for p in reversed(received[i]) if p.startswith(head))
    def state():
        return json.loads(remote('''
import json,sys,sqlite3
from tio.battle_snapshot import loads
names=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 raw=db.execute('SELECT c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m USING(match_id) WHERE m.account=?',(names[0],)).fetchone()[0]
 b=loads(raw)[0]['battle'];f=b['field'];turn=b['arena']._turns.get(b['room'].room_id)
 print(json.dumps(dict(match=b['match_id'],city=b['city_id'],metadata=f.scene_metadata,bots=len(b['bots']),
  blocked=list(f.blocked),width=f.width,height=f.height,turn=turn[0] if turn else None,
  actors=[dict(id=a.actor_id,owner=a.owner_id,account=b['reward_roster'][a.owner_id][0],side=f.teams[a.owner_id],x=a.x,y=a.y,hp=a.health,ap=a.action_points) for a in f._actors.values()])))
'''))
    def fixture(towns):
        remote('''
import json,sys,sqlite3
from dataclasses import replace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.locations import LocationStore,center
data=json.load(sys.stdin);names=data['names'];towns=data['towns']
assert len(names)==2 and all(n.startswith('qy') and len(n)==11 for n in names)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 for n,t in zip(names,towns):
  raw=db.execute('SELECT pet_packet FROM owned_pets WHERE account=? AND pet_id=1',(n,)).fetchone()[0]
  pet=decode_pet_info(raw,human_equipment=True)
  fields={**pet.fields,'0x8c4aef':4,'0x8c4a07':1000,'0x8c4ab1':1000}
  db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(encode_pet_info(replace(pet,fields=fields)),n))
  LocationStore._save(db,n,t,*center(t))
''',dict(names=names,towns=towns))
    backup=None
    try:
        backup=remote('''
import json,sys,sqlite3,tempfile,pathlib
from server.accounts import Accounts
pairs=json.load(sys.stdin)
assert len(pairs)==2 and all(n.startswith('qy') and len(n)==11 for n,p in pairs)
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-cities-qa-',dir='/root'))
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as src,sqlite3.connect(folder/'reservation.sqlite3') as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
for n,p in pairs:Accounts('/var/lib/tio-server/reservation.sqlite3').create(n,p,character=n)
print(folder)
''',list(zip(names,passwords))).strip();report['backup']=backup
        for i in (0,1):enter(i)
        close();time.sleep(1)
        for attempt,towns in enumerate(((2,5),(8,5),(5,2))):
            fixture(towns)
            for i in (0,1):enter(i)
            # Ordinary city market mutations through the original packet builders.
            command(0,b'\x61');candidates=decode_pet_shop(last(0,b'\x62'))
            assert candidates and not any(c.resource_type==6 for c in candidates)
            if attempt==0:
                command(0,encode_hire_request(candidates[0].candidate_id))
                assert any(p[:1]==b'\x66' and int.from_bytes(p[1:5],'little')==2 for p in received[0])
            command(0,b'\x73\0');offers=decode_item_shop(last(0,b'\x74'))[1]
            offer=next(o for o in offers if o.item_id==301)
            command(0,encode_shop_purchase(ShopPurchase(1,0,offer.unknown_u32_01,1)))
            assert any(p[:1]==b'\x30' for p in received[0])
            command(0,b'\xba\3\0\1')
            time.sleep(.2);command(1,b'\xba\3\0\1')
            for i in (0,1):
                if not any(p==b'\x41' for p in received[i]):peers[i].until(b'\x41',max_packets=512)
                peers[i].send(b'\x36');case.ping(peers[i])
            time.sleep(.2)
            initial=state();assert initial['city']==towns[0] and initial['bots']==0
            assert len(initial['actors'])==2 and initial['metadata']['profile']==('denver','military_zone','new_york')[attempt]
            if attempt==0:
                peers[0].sock.close();time.sleep(.5);enter(0)
                if not any(p==b'\x41' for p in received[0]):peers[0].until(b'\x41',max_packets=512)
                peers[0].send(b'\x36');case.ping(peers[0]);restored=state()
                assert restored['match']==initial['match'] and restored['city']==initial['city'] and restored['actors']==initial['actors']
                report['checks'].append('Reconnect retained city, exact actors/HP/AP and one shared match')
            # Walk the generated geometry and obtain a real damage event before settling.
            damage=False
            for step in range(24):
                b=state();actors=sorted(b['actors'],key=lambda a:a['account'])
                i=next(i for i,a in enumerate(actors) if a['owner']==b['turn'])
                a,e=actors[i],actors[1-i];start=(a['x'],a['y']);target=(e['x'],e['y'])
                if abs(start[0]-target[0])+abs(start[1]-target[1])>1:
                    blocked=set(map(tuple,b['blocked']))|{target};q=deque([start]);prev={start:None};end=None
                    while q:
                        x,y=q.popleft()
                        if abs(x-target[0])+abs(y-target[1])==1:end=(x,y);break
                        for cell in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                            if cell not in prev and cell not in blocked and 0<=cell[0]<b['width'] and 0<=cell[1]<b['height']:
                                prev[cell]=(x,y);q.append(cell)
                    assert end is not None
                    route=[]
                    while end!=start:route.append(end);end=prev[end]
                    path=tuple(reversed(route))[:min(10,a['ap'])]
                    command(i,encode_move_request(BattleMove(a['id'],path)))
                else:
                    command(i,encode_attack_request(AttackRequest(a['id'],e['x'],e['y'])))
                    after=state()
                    damage=any(a['hp']<1000 for a in after['actors'])
                    if damage:break
                command(i,encode_end_turn());time.sleep(.12)
            assert damage,'No real damage in native combat'
            winner=i;loser=1-i
            command(loser,b'\x2a\1')
            peers[winner].until(b'\x4c',max_packets=2048)
            command(winner,b'\x2a\1')
            receipts=json.loads(remote('''
import json,sys,sqlite3
data=json.load(sys.stdin)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT account,result,gross,calculation FROM battle_rewards WHERE match_id=? ORDER BY account',(data['match'],)).fetchall()
 assert len(rows)==2 and [r[1] for r in rows]==[int(i==data['winner']) for i in (0,1)]
 for n,r,g,c in rows:
  audit=json.loads(c);assert audit['town_id']==data['town'] and audit['city_profit']==4
 assert rows[data['winner']][2]>0
 assert [db.execute('SELECT town_id FROM character_locations WHERE account=?',(n,)).fetchone()[0] for n in data['names']]==data['towns']
 assert not db.execute('SELECT 1 FROM ranked_matches WHERE match_id=?',(data['match'],)).fetchone()
 print(json.dumps([dict(account=n,result=r,gross=g,calculation=json.loads(c)) for n,r,g,c in rows]))
''',dict(names=names,match=initial['match'],town=towns[0],towns=towns,winner=winner)))
            report['matches'].append(dict(match=initial['match'],towns=towns,map=initial['metadata'],receipts=receipts))
            report['checks'].append('Native city hiring/shop, two real accounts, geometry/movement/damage, profit4, own-town return, ordinary battle leaves TrueSkill unchanged')
            close();time.sleep(1)
        report['preservation']=json.loads(remote('''
import json,sys,sqlite3,pathlib
data=json.load(sys.stdin);backup=pathlib.Path(data['backup'])
assert backup.parent==pathlib.Path('/root') and backup.name.startswith('tio-before-cities-')
with sqlite3.connect(backup/'reservation.sqlite3') as old,sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 count=0;tables=old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'").fetchall()
 for name, in tables:
  quoted='"'+name.replace('"','""')+'"';before=set(map(repr,old.execute('SELECT * FROM '+quoted)));after=set(map(repr,db.execute('SELECT * FROM '+quoted)))
  assert before<=after,'Existing records changed: '+name
  count+=len(before)
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account IN (?,?)',data['names']).fetchone()
 assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
 print(json.dumps(dict(integrity='ok',old_tables=len(tables),old_rows_preserved=count)))
''',dict(names=names,backup=json.loads((folder/'deployment.json').read_text())['backup'])))
        report['passed']=True
    except BaseException as exc:
        report['error']=repr(exc)
        for i,p in peers.items():
            try:
                p.send(b'\x2a\1');case.ping(p)
            except (OSError,ValueError):pass
        raise
    finally:
        close();output=folder/f'hosted-{prefix}.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(report=str(output),passed=report['passed'])))


if __name__=='__main__':run(sys.argv[1] if len(sys.argv)>1 else '185.184.42.88')
