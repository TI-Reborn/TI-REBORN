"""Owned, excluded QA accounts exercise credit receipts through hosted TLS."""
import ast
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/bot-credit-rewards-20261016'
CANDIDATE=ROOT/'work/bot-credit-rewards-20261016/candidate'
sys.path[:0]=[str(CANDIDATE),str(CANDIDATE/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
saved_path=list(sys.path)
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
sys.path[:]=saved_path
from tio.rating_visibility import QA_LOGIN

# Reuse the audited, read-only battle-state collector, without importing its
# previous release's path setup or executing that release's scenarios.
source=ast.parse((ROOT/'tools/verify_bot_finishing_hosted.py').read_text())
STATE=next(ast.literal_eval(n.value) for n in source.body if isinstance(n,ast.Assign)
           and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='STATE')

PREPARE=r'''
import json,sqlite3
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
name=request['name'];assert QA_LOGIN.fullmatch(name)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert excluded(db,name)
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
 rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(name,)).fetchall()
 assert len(rows)==1 and rows[0][1]
 identity,human,raw=rows[0];pet=decode_pet_info(raw,human_equipment=True)
 packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':200,'0x8c4a07':200}))
 db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,name,identity))
 if request['armed']:
  def item(i,t,n,e,s):return ItemRecord(i,t,b'\0\0',n,e,s,(300,300,300),b'\0'*4,None,b'\0'*3)
  bag=encode_item_list(identity,(item(91001,304,1,1,16),item(91002,7,100,0,0),item(91003,256,1,1,4)))
  db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(bag,name,identity))
 print(json.dumps(dict(owned_fixture_only=True,health=200,armed=request['armed'])))
'''

PLAN=r'''
import json,sqlite3
from tio.battle_snapshot import loads
from tio.rating_visibility import QA_LOGIN
from tio.training_bot import approach_path
from tio.tactical_bot import can_fire,weapon_for
from tio.visibility import visible_actors
from tio.protocol.battle_attack import AttackRequest,encode_attack_request
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_door import DoorRequest,encode_door_request
from tio.protocol.battle_turn import encode_end_turn
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 row=db.execute('SELECT c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m ON m.match_id=c.match_id WHERE m.account=?',(names[0],)).fetchone()
 if not row:print(json.dumps(dict(finished=True)))
 else:
  b=loads(row[0])[0]['battle'];f=b['field']
  assert {r[0] for r in b['reward_roster'].values()}<=set(names)
  owner=next(o for o,r in b['reward_roster'].items() if r[0]==names[0])
  turn=b['arena']._turns.get(b['room'].room_id)
  result=dict(finished=b['finished'],turn=turn[0] if turn else None,owner=owner,
   active=owner in b['reward_damage'],packet=None,skip=False)
  if not b['finished'] and turn and turn[0]==owner and f.living_actor_ids(owner):
   identity=f.living_actor_ids(owner)[0];a=f.actor(identity)
   targets=sorted((t for t in f._actors.values() if t.health and not f.allied(t.owner_id,owner)),key=lambda t:t.health)
   known=visible_actors(f,owner);weapon=weapon_for(f,identity)
   target=next((t for t in targets if t.actor_id in known and weapon and a.action_points>=weapon.attack_ap and can_fire(f,(a.x,a.y),t,weapon)),None)
   if target:packet=encode_attack_request(AttackRequest(identity,target.x,target.y))
   else:
    path=approach_path(f,identity,targets,frozenset(f._actors)) if targets else ()
    closed={p for p,opened in f.doors.states.items() if not opened}
    if path and a.action_points>1:
     if path[0] in closed:packet=encode_door_request(DoorRequest(identity,True,*path[0]))
     else:
      steps=[]
      for cell in path[:max(1,(a.action_points-(weapon.attack_ap if weapon else 4))//f.step_cost)]:
       if cell in closed:break
       steps.append(cell)
      packet=encode_move_request(BattleMove(identity,tuple(steps)))
    else:packet=encode_end_turn();result['skip']=True
   result['packet']=packet.hex()
  print(json.dumps(result))
'''

RECEIPTS=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN
names=request['names'];assert all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 result={}
 for name in names:
  wallet=db.execute('SELECT credits FROM wallets WHERE account=?',(name,)).fetchone()
  rows=db.execute('SELECT match_id,result,credits,gross,rental_tax,calculation FROM battle_rewards WHERE account=?',(name,)).fetchall()
  result[name]=dict(wallet=wallet[0] if wallet else None,receipts=[dict(match=r[0],result=r[1],credits=r[2],gross=r[3],tax=r[4],audit=json.loads(r[5])) for r in rows])
 print(json.dumps(result))
'''


def scenario(mode):
    names=['qb'+secrets.token_hex(4)]
    names=[names[0]+'a',names[0]+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();peers=[];provision=None
    report=dict(mode=mode,passed=False,fixtures=names,graphical_clients=False)
    def connect(kind,*,preface=None,**kwargs):
        channel=context.wrap_socket(socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15),server_hostname='ti-reborn.com')
        case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def command(i,packet=None):
        if packet is not None:peers[i].send(packet)
        peers[i].send(b'\x70');result=[]
        for _ in range(4096):
            p=peers[i].receive()
            if p==b'\x9e':return result
            result.append(p)
            if p.startswith(b'\xf0\x8a\x01\0\0'):raise AssertionError('Gameplay rejected: '+p[13:-2].decode('utf-16-le'))
        raise AssertionError('No ping fence')
    def state():return remote(STATE,dict(names=names))
    try:
        provision=remote(CREATE,list(zip(names,passwords)));report['ranking_excluded']=provision['ranking_excluded']
        for i in range(1 if mode=='solo' else 2):
            p=tls.handoff(tls.begin(names[i],35001+i,password=passwords[i]));case.enter(p,names[i]);peers.append(p)
            command(i,struct.pack('<Bii',0x1b,-154,-318))
            remote(PREPARE,dict(name=names[i],armed=i==0))
        before=remote(RECEIPTS,dict(names=names));start=time.monotonic()
        if mode in ('humans','solo'):
            command(0,b'\xba\3\0\1')
            if mode=='humans':command(1,b'\xba\3\0\1')
        else:
            for i in (0,1):command(i,bytes((0xba,3,1 if mode=='team' else 4,1)));command(i,b'\x2e')
        while not state():
            if time.monotonic()-start>70:raise AssertionError('No hosted scene')
            command(0);time.sleep(3)
        battle=state()[0];report['snapshot']=battle
        assert battle['bots']==dict(humans=0,solo=1,team=2,wall=6)[mode]
        assert len(battle['humans'])==len(peers)
        for i in range(len(peers)):command(i,b'\x36')
        for _ in range(240):
            frame=remote(PLAN,dict(names=names))
            for i in range(len(peers)):command(i)
            if frame['finished']:break
            if mode in ('team','wall') and frame['active']:
                # The receipt still freezes and audits the mixed composition
                # on an ordinary forfeit, which must never pay escape money.
                command(0,b'\x2a\1');break
            if frame['packet']:
                if frame['skip']:time.sleep(1.05)
                command(0,bytes.fromhex(frame['packet']))
            else:
                other=next((i for o,n in battle['humans'].items() for i in (names.index(n),) if int(o)==frame['turn']),None)
                if other is not None:time.sleep(1.05);command(other,b'\x3a\0\0\0\0')
                else:time.sleep(.2)
        else:raise AssertionError('Controlled match did not finish')
        after=remote(RECEIPTS,dict(names=names));rows=after[names[0]]['receipts'];assert len(rows)==1
        row=rows[0];assert row['match']==battle['match']
        report.update(receipt=row,wallet_before=before[names[0]]['wallet'],wallet_after=after[names[0]]['wallet'])
        expected=dict(humans='1',solo='1/2',team='3/4',wall='5/8')[mode]
        assert row['audit'].get('bot_credit_factor','1')==expected
        assert row['audit']['participation']==1
        if mode in ('solo','humans'):
            assert row['result']==1
            assert row['gross']==(50 if mode=='solo' else 100)
            assert after[names[0]]['wallet']-before[names[0]]['wallet']==row['credits']
            wallet=after[names[0]]['wallet']
            command(0,b'\x36');command(0,b'\x36')
            assert remote(RECEIPTS,dict(names=names))[names[0]]['wallet']==wallet
        else:assert row['credits']==0 and row['audit']['outcome']=='0'
        report.update(passed=True,receipt=row,wallet_before=before[names[0]]['wallet'],wallet_after=after[names[0]]['wallet'],rate=expected,
                      real_tls_gameplay=True,active_damage_verified=True)
    finally:
        for i in range(len(peers)):
            try:command(i,b'\x2a\1')
            except (AssertionError,OSError,EOFError):pass
        for c in case.clients:
            try:c.close()
            except OSError:pass
        time.sleep(1)
        output=FOLDER/('hosted-'+mode+'.json');output.write_text(json.dumps(report,indent=2))
        if provision:
            if state():raise RuntimeError('Owned QA scene remains; retained for safe cleanup')
            report['cleanup']=remote(CLEANUP,dict(names=names,protected_before=provision['protected_before'],require_unchanged_players=False))
        output.write_text(json.dumps(report,indent=2))
    return report


def main():
    reports=[]
    for mode in ('humans','solo','team','wall'):
        previous=FOLDER/('hosted-'+mode+'.json')
        saved=json.loads(previous.read_text()) if previous.exists() else None
        value=saved if saved and saved.get('passed') and saved.get('cleanup',{}).get('unrelated_rows_preserved') else scenario(mode)
        reports.append(value);print(json.dumps({k:v for k,v in value.items() if k!='snapshot'}),flush=True)
    from tools.cleanup_bot_credit_rewards_qa import main as cleanup
    cleanup()
    (FOLDER/'hosted-verification.json').write_text(json.dumps(dict(passed=True,scenarios=reports,graphical_clients=False),indent=2))


if __name__=='__main__':main()
