"""Screenshot regressions and multiplayer bot gameplay over hosted TLS.

Checks real-player priority, the actual one-minute timeout, shared bot turns,
crate equipment and capacity. This is protocol QA, not graphical-client QA.
"""
import json
from pathlib import Path
import secrets
import socket
import ssl
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/bot-finishing-20261016/candidate'
sys.path[:0]=[str(CANDIDATE),str(CANDIDATE/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
# Reuse the previously audited exact-owner provisioning/cleanup transaction.
saved_path=list(sys.path)
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
sys.path[:]=saved_path
from tio.protocol.battle_turn import encode_end_turn
from tio.rating_visibility import QA_LOGIN
from tio.protocol.battle_attack import decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request
from tio.protocol.battle_door import DoorRequest,encode_door_request

# Controlled health belongs only to this fresh, excluded disposable account.
# Set it before queueing; never edit a live battle or an ordinary player.
PREPARE_DUEL=r'''
import json,sqlite3
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
name=request['name'];assert QA_LOGIN.fullmatch(name)
with sqlite3.connect('/var/lib/tio-server/reservation.sqlite3') as db:
 assert excluded(db,name)
 assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(name,)).fetchone()
 rows=db.execute('SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(name,)).fetchall()
 assert len(rows)==1 and rows[0][1]
 identity,human,raw=rows[0];pet=decode_pet_info(raw,human_equipment=True)
 packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4ab1':200,'0x8c4a07':200}))
 db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,name,identity))
 print(json.dumps(dict(owned_fixture_only=True,health=200)))
'''

ENGAGEMENT=r'''
import json,sqlite3
from tio.battle_snapshot import loads
from tio.rating_visibility import QA_LOGIN
from tio.training_bot import approach_path
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=db.execute('SELECT c.payload FROM battle_checkpoints c JOIN battle_checkpoint_members m ON m.match_id=c.match_id WHERE m.account=?',(names[0],)).fetchall()
 if not rows:print(json.dumps(dict(finished=True)))
 else:
  assert len(rows)==1
  b=loads(rows[0][0])[0]['battle'];f=b['field']
  assert len(b['humans'])==1 and len(b['bots'])==1
  owner=next(iter(b['humans']));assert b['reward_roster'][owner][0]==names[0]
  identity=f.actor_ids(owner)[0];human=f.actor(identity)
  bot=next(a for a in f._actors.values() if a.owner_id in b['bots'])
  # The QA driver may inspect its own controlled scene to arrange contact.
  # The production bot still receives only its ordinary visibility set.
  path=approach_path(f,identity,(bot,),frozenset(f._actors)) if human.health and bot.health else ()
  turn=b['arena']._turns.get(b['room'].room_id)
  print(json.dumps(dict(finished=b['finished'],owner=owner,turn=turn[0] if turn else None,
   identity=identity,hp=human.health,ap=human.action_points,path=path,
   closed=[p for p,opened in f.doors.states.items() if not opened],bot=bot.actor_id)))
'''

STATE=r'''
import sqlite3,json
from tio.rating_visibility import QA_LOGIN,excluded
from tio.battle_snapshot import loads
from tio.protocol.item_list import decode_item_list
from tio.weight import inventory_weight,overload_penalty
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 assert all(excluded(db,n) for n in names)
 marks=','.join('?' for n in names)
 rows=db.execute('SELECT DISTINCT c.match_id,c.payload,c.status FROM battle_checkpoints c JOIN battle_checkpoint_members m ON m.match_id=c.match_id WHERE m.account IN ('+marks+')',names).fetchall()
 result=[]
 for match,payload,status in rows:
  battle=loads(payload)[0]['battle'];field=battle['field'];combat=field.combat;room=battle['room']
  assert {r[0] for r in battle['reward_roster'].values()}<=set(names),'Foreign player entered owned QA scene'
  turn=battle['arena']._turns.get(room.room_id)
  actors=[]
  for actor in field._actors.values():
   bag=decode_item_list(combat.inventories[actor.actor_id])[1]
   capacity=combat.weight_capacity(actor.actor_id) if actor.actor_id in combat.weight_capacities else None
   weight=inventory_weight(combat.inventories[actor.actor_id])
   actors.append(dict(id=actor.actor_id,owner=actor.owner_id,bot=actor.owner_id in battle['bots'],
    hp=actor.health,ap=actor.action_points,round=field._ability_turns.get(actor.actor_id,0),position=[actor.x,actor.y],
    items=[dict(template=i.template_id,count=i.count,equipped=i.equipped) for i in bag],
    weight=weight,capacity=capacity,penalty=overload_penalty(weight,capacity) if capacity else None,
    crates=len(getattr(field,'bot_crates',{}).get(actor.actor_id,()))))
  result.append(dict(match=match,status=status,mode=room.request.mode,bots=len(battle['bots']),
    humans={str(o):r[0] for o,r in battle['reward_roster'].items()},finished=battle['finished'],
    turn=turn[0] if turn else None,loading=len(battle['arena']._loading[room.room_id]),actors=actors))
 print(json.dumps(result))
'''


def scenario(mode):
    prefix='qb'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    passwords=[secrets.token_urlsafe(24) for _ in names]
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context();peers=[];provision=None
    report=dict(mode=mode,passed=False,kind='hosted native TLS protocol; no graphical clients')
    report['fixtures']=names
    engagement=dict(enabled=False,phase=0,groups={})
    def capture(packet):
        if not engagement['enabled']:return
        if packet[0]==0x38:engagement['phase']+=1
        if packet[0]!=0x4b:return
        attack=decode_attack_result(packet)
        for hit in attack.hits:
            if hit.actor_id!=engagement['target']:continue
            key=engagement['phase'],attack.actor_id
            engagement['groups'].setdefault(key,[]).append(dict(weapon=attack.weapon_id,damage=hit.damage,left_hp=hit.left_hp))
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def command(index,packet=None):
        peer=peers[index]
        if packet is not None:peer.send(packet)
        peer.send(b'\x70');received=[]
        for _ in range(4096):
            reply=peer.receive()
            if reply==b'\x9e':return received
            received.append(reply)
            capture(reply)
            if reply.startswith(b'\xf0\x8a\x01\0\0'):
                raise AssertionError('Gameplay request rejected: '+reply[13:-2].decode('utf-16-le'))
        raise AssertionError('Missing gameplay ping fence')
    def state():return remote(STATE,dict(names=names))
    def wait(predicate,seconds=12):
        deadline=time.monotonic()+seconds
        while True:
            value=state()
            if predicate(value):return value
            if time.monotonic()>=deadline:raise AssertionError('Hosted gameplay state timeout')
            time.sleep(.4)
    try:
        provision=remote(CREATE,list(zip(names,passwords)))
        report['ranking_excluded']=provision['ranking_excluded']
        for index in range(1 if mode=='solo' else 2):
            peer=tls.handoff(tls.begin(names[index],34001+index,password=passwords[index]));case.enter(peer,names[index])
            peers.append(peer);command(index,struct.pack('<Bii',0x1b,-154,-318))
        if mode=='solo':report['duel_fixture']=remote(PREPARE_DUEL,dict(name=names[0]))
        start=time.monotonic()
        if mode in ('solo','humans'):
            command(0,b'\xba\x03\0\1')
            if mode=='humans':command(1,b'\xba\x03\0\1')
            else:
                # Actual hosted elapsed time, without changing server clocks.
                while time.monotonic()-start<58:
                    assert not state(),'Solo scene started before the minute'
                    command(0);time.sleep(min(5,max(.01,58-(time.monotonic()-start))))
                assert not state(),'Solo scene started before the minute'
        else:
            category=1 if mode=='team' else 4
            for index in (0,1):
                command(index,bytes((0xba,3,category,1)));command(index,b'\x2e')
        battle=wait(lambda s:len(s)==1)[0]
        elapsed=time.monotonic()-start
        report['elapsed_to_scene_seconds']=round(elapsed,3)
        assert battle['bots']==(1 if mode=='solo' else 0 if mode=='humans' else 2 if mode=='team' else 6)
        assert len(battle['humans'])==len(peers)
        assert all(not a['items'] for a in battle['actors'] if a['bot']),'Bots copied player inventory'
        for index in range(len(peers)):command(index,b'\x36')
        battle=wait(lambda s:s and s[0]['turn'] is not None)[0]
        owners={int(o):names.index(n) for o,n in battle['humans'].items()}
        bot_states=[]
        if mode=='solo':
            human=next(iter(owners))
            assert all(0<a['owner']<0x80000000 for a in battle['actors'] if a['bot'])
            before_rounds={a['id']:a['round'] for a in battle['actors'] if not a['bot']}
            peers[0].send(encode_end_turn());peers[0].send(encode_end_turn())
            replies=command(0)
            assert replies.count(b'\x39')==1,'Duplicate EndTurn ended two turns'
            battle=wait(lambda s:s and s[0]['turn']==human)[0]
            after_rounds={a['id']:a['round'] for a in battle['actors'] if not a['bot']}
            assert after_rounds=={i:n+1 for i,n in before_rounds.items()},'Human turn skipped after fast bot'
            assert all(a['ap']>0 for a in battle['actors'] if not a['bot'])
            report['duplicate_end_turn_preserved_next_turn']=True
            report['native_safe_bot_owner']=True
            bot_states.extend(a for a in battle['actors'] if a['bot'])
        for _ in range(12 if mode!='humans' else 2):
            if battle['finished']:break
            owner=battle['turn']
            if owner in owners:
                time.sleep(1.05) # A separate intentional skip, outside the repeat window.
                command(owners[owner],encode_end_turn())
            previous=battle
            battle=wait(lambda s:s and (s[0]['finished'] or s[0]['turn']!=owner or s[0]['turn']==owner and
                s[0]['actors']!=previous['actors']),seconds=25)[0]
            for index in range(len(peers)):command(index)
            bot_states.extend(a for a in battle['actors'] if a['bot'])
            if mode!='humans' and any(a['items'] and any(i['equipped'] for i in a['items']) for a in bot_states):break
        if mode!='humans':
            assert any(a['crates'] for a in bot_states),'No authoritative bot crate opening recorded'
            assert any(any(i['equipped'] for i in a['items']) for a in bot_states),'No bot equipped crate gear'
            assert all(a['penalty']==0 for a in bot_states if a['capacity']),'Bot collected overload'
        if mode=='solo':
            frame=remote(ENGAGEMENT,dict(names=names));assert not frame['finished']
            engagement.update(enabled=True,target=frame['identity'])
            for _ in range(100):
                groups=list(engagement['groups'].values())
                if any(len(g)>=2 and sum(h['damage']>0 for h in g)>=2 and g[-1]['left_hp']==0 for g in groups):break
                frame=remote(ENGAGEMENT,dict(names=names))
                if frame['finished']:command(0);break
                if frame['turn']!=frame['owner']:
                    command(0);time.sleep(.15);continue
                path=frame['path'];closed=set(map(tuple,frame['closed']))
                if path and frame['ap']>1:
                    if tuple(path[0]) in closed:
                        command(0,encode_door_request(DoorRequest(frame['identity'],True,*path[0])))
                    else:
                        steps=[]
                        for cell in path[:frame['ap']-1]:
                            if tuple(cell) in closed:break
                            steps.append(tuple(cell))
                        command(0,encode_move_request(BattleMove(frame['identity'],tuple(steps))))
                else:
                    time.sleep(1.05);command(0,encode_end_turn())
            command(0)
            groups=[dict(phase=k[0],bot=k[1],attacks=v) for k,v in engagement['groups'].items()]
            report['duel_attack_groups']=groups
            report['hosted_multiple_hits_finished_target']=any(
                len(g['attacks'])>=2 and sum(h['damage']>0 for h in g['attacks'])>=2
                and g['attacks'][-1]['left_hp']==0 for g in groups)
            assert report['hosted_multiple_hits_finished_target'],'No same-turn multi-hit finishing kill observed'
        report.update(passed=True,bots=battle['bots'],human_accounts=len(peers),
            bot_crates_opened=max((a['crates'] for a in bot_states),default=0),
            bot_equipment_observed=any(any(i['equipped'] for i in a['items']) for a in bot_states),
            no_overload=all(a['penalty']==0 for a in bot_states if a['capacity']),snapshot=battle)
    finally:
        # Leave only our own searches/scenes through native commands before the
        # exact-owner database cleanup. Never delete another player's battle.
        for index in range(len(peers)):
            try:
                command(index,b'\xba\x07\0' if not state() else b'\x2a\1')
            except (AssertionError,OSError,EOFError):
                try:command(index,b'\x2a\1')
                except (AssertionError,OSError,EOFError):pass
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        time.sleep(1)
        folder=ROOT/'reports/bot-finishing-20261016'
        # Preserve exact ownership and gameplay evidence even when cleanup
        # encounters concurrent ordinary gameplay or fails its own guards.
        (folder/('hosted-'+mode+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        if provision:
            remaining=state()
            if remaining:raise RuntimeError('Owned QA battle remains; fixtures retained for safe cleanup')
            # Unrelated rows are fingerprinted and checked within the cleanup
            # transaction. Ordinary players may change their saves during QA;
            # never require those saves to equal a minutes-old fingerprint.
            report['cleanup']=remote(CLEANUP,dict(names=names,protected_before=provision['protected_before'],
                                                require_unchanged_players=False))
        (folder/('hosted-'+mode+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    reports=[]
    for mode in ('humans','solo','team','wall'):
        previous=ROOT/'reports/bot-finishing-20261016'/('hosted-'+mode+'.json')
        saved=json.loads(previous.read_text()) if previous.exists() else None
        value=saved if saved and saved.get('passed') and saved.get('cleanup',{}).get('unrelated_rows_preserved') else scenario(mode)
        reports.append({k:v for k,v in value.items() if k!='snapshot'})
        print(json.dumps(reports[-1]),flush=True)
    from tools.cleanup_bot_finishing_qa import main as cleanup_receipts
    cleanup_receipts()
    (ROOT/'reports/bot-finishing-20261016/hosted-verification.json').write_text(json.dumps(
        dict(passed=all(r['passed'] for r in reports),scenarios=reports,graphical_clients=False),indent=2))


if __name__=='__main__':main()
