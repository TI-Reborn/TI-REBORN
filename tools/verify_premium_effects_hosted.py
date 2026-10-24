"""Two excluded hosted TLS accounts: shared premium and authoritative battles.

This is protocol acceptance, not a graphical game-client test. Generated
credentials stay in a private local receipt and are removed with the fixtures.
"""
from pathlib import Path
import argparse
import hashlib
import socket
import ssl
import urllib.request
import json
import secrets
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools.verify_game_operations_hosted import remote,CREATE,CLEANUP
sys.path[:]=saved
from tools.verify_area_fire_hosted_20261018 import Network as LegacyNetwork,STATE as FIELD_STATE
sys.path[:]=saved
from tio.protocol.asset_count import decode_asset_count
from tio.protocol.city_catalogs import decode_item_shop
from tio.protocol.battle_attack import AttackRequest,encode_attack_request,decode_attack_result
from tio.protocol.battle_move import BattleMove,encode_move_request

class Network(LegacyNetwork):
    def __init__(self,data):
        super().__init__(data)
        raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=20).read()
        launcher=json.loads(urllib.request.urlopen('https://185.184.42.88/downloads/launcher-manifest.json',timeout=20).read())
        proof=hashlib.sha256(raw).digest()+struct.pack('!HHH',*map(int,launcher['version'].split('.')))
        context=ssl.create_default_context()
        def connect(kind,*,preface=None,**kwargs):
            raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
            channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');self.case.clients.append(channel)
            port=int.from_bytes(preface[6:8],'big') if preface else 38001
            flags=preface[5] if preface else 0
            channel.sendall(struct.pack('!4sBBH',b'TIOT',2,flags,port)+proof)
            return channel
        self.tls.connect=connect


OUT=ROOT/'reports/premium-effects-20261023'
PRIVATE=ROOT/'.secrets/premium-effects-20261023.json'

PREPARE=r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.characters import CharacterStore
from tio.protocol.character_create import CharacterCreateRequest
from tio.owned_pets import OwnedPetStore
from tio.squad import SquadStore
from tio.wallets import WalletStore
from tio.locations import LocationStore,center
from tio.weapon_proficiency import ProficiencyRules
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.level_progression import FLOORS
path='/var/lib/tio-server/reservation.sqlite3';names=request['names']
assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
if not request.get('refresh'):
 CharacterStore(path).create(names[0],CharacterCreateRequest((names[0]+'x').encode(),0,(0,0,0,0)))
owners=[names[0], '@character:'+names[0]+':2',names[1]]
pet=decode_pet_info(bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']),human_equipment=True)
locations=LocationStore(path);pets=OwnedPetStore(path)
for owner in owners:
 WalletStore(path).ensure(owner)
 with sqlite3.connect(path) as db:
  assert excluded(db,owner)
  assert not db.execute('SELECT 1 FROM battle_checkpoint_members WHERE account=?',(owner,)).fetchone()
  display=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()[0]
 raw=ProficiencyRules().normalize(encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4489':display,'0x8c4aef':10,'0x8c4b05':FLOORS[9],'0x8c4a07':1000,'0x8c4ab1':1000,'0x8c4b57':65000})),True)
 def item(i,t,n,e,s):return ItemRecord(i,t,bytes(2),n,e,s,(300,300,300),bytes(4),None,bytes(3))
 inv=encode_item_list(1,(item(91001,314,1,1,16),item(91002,14,600,0,0)))
 pets.ensure(owner,raw,inv,human=True)
 with sqlite3.connect(path) as db:
  db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(raw,inv,owner))
  db.execute('UPDATE wallets SET credits=100000 WHERE account=?',(owner,))
  LocationStore._save(db,owner,2,*center(2))
  if not request.get('refresh'):
   db.execute('CREATE TABLE IF NOT EXISTS rating_exclusions(account TEXT PRIMARY KEY)')
   db.execute('INSERT OR IGNORE INTO rating_exclusions VALUES (?)',(owner,))
 SquadStore(path).assign(owner,1,1)
print(json.dumps(dict(owners=owners,ranking_excluded=True)))
'''

QUERY=r'''
import json,sqlite3
from tio.rating_visibility import QA_LOGIN,excluded
from tio.premium import state
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
owners=[names[0], '@character:'+names[0]+':2',names[1]]
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 result={'states':[state(db,o) for o in owners],'excluded':all(excluded(db,o) for o in owners)}
 match=request.get('match')
 if match:
  result['rewards']=[dict(owner=owners.index(a),result=r,gross=g,audit=json.loads(c)) for a,r,g,c in db.execute('SELECT account,result,gross,calculation FROM battle_rewards WHERE match_id=?',(match,)) if a in owners]
  result['xp']=[dict(owner=owners.index(a),gain=g) for a,g in db.execute('SELECT account,gain FROM experience_battle_audit WHERE match_id=?',(match,)) if a in owners]
  result['rank']=[dict(owner=owners.index(a),earned=e) for a,e in db.execute('SELECT account,earned FROM rank_battle_audit WHERE match_id=?',(match,)) if a in owners]
  result['influence']=[dict(owner=owners.index(a),**json.loads(body)) for a,body in db.execute("SELECT account,receipt FROM clan_benefit_receipts WHERE operation='xp' AND identity=?",(match,)) if a in owners]
 print(json.dumps(result))
'''

# Read the accepted authoritative snapshot; planning never writes the battle.
STATE=FIELD_STATE.replace("names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)",
 "logins=request['names'];assert len(logins)==2 and all(QA_LOGIN.fullmatch(n) for n in logins)\nnames=['@character:'+logins[0]+':2',logins[1]]")
STATE=STATE.replace("  if request.get('plan')", "  result['skills']={str(a.actor_id):c.proficiency_rules.value(c.proficiencies[a.actor_id],True,'Heavy') for a in f._actors.values()}\n  if request.get('plan')")


def state(data,plan=False):return remote(STATE,dict(names=data['names'],plan=plan))
def saved_fighter(data,index):
    return remote(SAVED,dict(names=data['names'],index=index))


SAVED=r'''
import sqlite3,json
from tio.rating_visibility import QA_LOGIN
from tio.protocol.item_list import decode_item_list
from tio.weapon_proficiency import ProficiencyRules
names=request['names'];assert all(QA_LOGIN.fullmatch(n) for n in names)
owner=('@character:'+names[0]+':2') if request['index']==0 else names[1]
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 p,inv=db.execute('SELECT pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(owner,)).fetchone()
 print(json.dumps(dict(skill=ProficiencyRules().value(p,True,'Heavy'),wear=next(i.unknown_words[0] for i in decode_item_list(inv)[1] if i.template_id==314))))
'''


def save(data):PRIVATE.write_text(json.dumps(data))


def enter_second(net):
    p=net.tls.handoff(net.tls.begin(net.data['names'][0],38001,password=net.data['passwords'][0]))
    net.case.character_screen(p);p.send(b'\x17'+struct.pack('<I',2));p.until(b'\x18');p.send(b'\x19')
    p.until(b'\x1a');assets=decode_asset_count(p.until(b'\xc8\x39'));net.case.ping(p)
    receive=p.receive
    def record():
        row=receive();net.received[0].append(row);return row
    p.receive=record;net.peers[0]=p
    return assets


def run():
    resume=PRIVATE.exists()
    if resume:
        data=json.loads(PRIVATE.read_text());report=json.loads((OUT/'hosted-two-account.json').read_text())
        assert not state(data) and len(report['phases'])==1 and report['phases'][0]['offer']==1
    else:
        prefix='qv'+secrets.token_hex(4)
        data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)],matches=[])
        data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));save(data)
        remote(PREPARE,data);report=dict(passed=False,kind=__doc__,phases=[])
    net=Network(data)
    try:
        enter_second(net);net.connect(1)
        # Native clan creation/invitation, owned and excluded before it exists.
        if not resume:
            rows=net.command(0,b'\x52'+(prefix+'Clan').encode()+b'\0')
            data['clan']=struct.unpack_from('<I',next(r for r in rows if r[:1]==b'\x5e'),1)[0];save(data)
            net.command(0,b'\x5b'+data['names'][1].encode()+b'\0');net.command(1,b'\x5d\x01')
        for offer in ((3,) if resume else (1,3)):
            if offer==3:
                net.close();time.sleep(1)
                remote(PREPARE,{**data,'refresh':True});net=Network(data);enter_second(net);net.connect(1)
            rows=net.command(0,b'\xc8\x3a'+struct.pack('<II',offer,1500))
            until=time.monotonic()+10
            while True:
                assets=[decode_asset_count(r) for r in rows if r[:2]==b'\xc8\x39']
                if any(a.optional_raw and a.optional_raw[1]==offer for a in assets):break
                assert time.monotonic()<until,'No updated premium status'
                rows+=net.command(0)

            snapshot=remote(QUERY,data);assert snapshot['excluded'] and snapshot['states'][0][0]==offer and snapshot['states'][1][0]==offer and snapshot['states'][2][0]==0
            quotes=[]
            for i in (0,1):
                rows=net.command(i,b'\x73\0')
                catalog=decode_item_shop(next(r for r in rows if r[:1]==b'\x74'))[1]
                quotes.append(next(o.unknown_u32_03 for o in catalog if o.unknown_u32_01==81))
            assert quotes[0]==(quotes[1]*4+4)//5
            for i in (0,1):net.command(i,b'\xba\3\0\1')
            for i in (0,1):
                if not any(p[:1]==b'\x41' for p in net.received[i]):net.peers[i].until(b'\x41',max_packets=4096)
            frame=state(data);assert frame and not frame['finished'];match=frame['match'];data['matches'].append(match);save(data)
            for i in (0,1):net.command(i,b'\x36')
            owners=['@character:'+data['names'][0]+':2',data['names'][1]]
            shots=[];spent={0:0,1:0};deadline=time.monotonic()+360
            while time.monotonic()<deadline:
                frame=state(data,True)
                if not frame or frame['finished']:break
                actor=next(a for a in frame['actors'] if a['owner']==frame['turn']);i=owners.index(actor['account'])
                if actor['ap']<9 or i==1 and any(s['account']==1 for s in shots):
                    time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
                if frame.get('route'):
                    net.command(i,encode_move_request(BattleMove(actor['id'],tuple(map(tuple,frame['route'])))),expected=b'\x3d');continue
                if not frame.get('aim'):
                    time.sleep(1.05);net.command(i,b'\x3a'+bytes(4));continue
                persisted_before=saved_fighter(data,i)
                rows=net.command(i,encode_attack_request(AttackRequest(actor['id'],*frame['aim'])),expected=b'\x4b')
                # A previous ping may still be queued from scene loading.
                # Observe the committed own inventory instead of assuming that
                # the first received ping or snapshot is the latest operation.
                until=time.monotonic()+10
                while True:
                    persisted_after=saved_fighter(data,i)
                    if persisted_after['wear']!=persisted_before['wear']:break
                    if time.monotonic()>until:raise AssertionError(dict(before=persisted_before,after=persisted_after,index=i,offer=offer))
                    time.sleep(.2)
                spent[i]+=9
                expected=(spent[i]+1)//2 if i==0 and offer==3 else spent[i]
                assert 300-persisted_after['wear']==expected,dict(actual=persisted_after,expected_total_wear=expected,index=i,offer=offer)
                gain=persisted_after['skill']-persisted_before['skill'];assert gain>0
                wear=persisted_before['wear']-persisted_after['wear']
                shots.append(dict(account=i,wear=wear,skill_gain=gain))
                after=state(data)
                print(json.dumps(dict(offer=offer,accepted_shots=len(shots),battle_running=bool(after and not after['finished']))),flush=True)
            else:raise TimeoutError('Owned battle did not finish')
            result=remote(QUERY,{**data,'match':match})
            own=next(r for r in result['rewards'] if r['owner']==1)
            assert own['result']==1 and own['gross']>0 and own['audit']['premium_kind']==offer
            assert own['audit']['experience_factor']==('3/2' if offer==1 else '0')
            assert own['audit']['rank_positive_factor']==('3' if offer==1 else '2')
            assert next(r for r in result['xp'] if r['owner']==1)['gain']>0 if offer==1 else next(r for r in result['xp'] if r['owner']==1)['gain']==0
            assert next(r for r in result['influence'] if r['owner']==1)['amount']>0
            phase=dict(offer=offer,match=match,shop_quotes=quotes,shots=shots,result=result)
            report['phases'].append(phase);(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
            for i in (0,1):net.command(i,b'\x2a\1')
        report['passed']=True
    finally:
        for i in tuple(net.peers):
            try:net.command(i,b'\x2a\1')
            except (OSError,EOFError,AssertionError):pass
        net.close();(OUT/'hosted-two-account.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=True,phases=2,shared_hosted_battles=True,graphical_clients=False)))


def cleanup():
    data=json.loads(PRIVATE.read_text());assert state(data) is None,'Own retained battle must finish normally'
    code=CLEANUP
    marker=" tables=[r[0]"
    guard=" cid=request.get('clan')\n if cid:\n  assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==('@character:'+names[0]+':2',)\n  assert {r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(cid,))}<=set(owners)\n"
    code=code.replace(marker,guard+marker)
    old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
    new="\n  if request.get('clan') and 'clan_id' in columns:parts.append(quote('clan_id')+'=?');args.append(request['clan'])\n  if request.get('clan') and table=='clans':parts.append('id=?');args.append(request['clan'])\n  if 'match_id' in columns and request.get('matches'):parts.append(quote('match_id')+' IN ('+','.join('?' for _ in request['matches'])+')');args+=request['matches']\n  "+old
    assert old in code;code=code.replace(old,new)
    value=remote(code,dict(names=data['names'],clan=data.get('clan'),matches=data['matches'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(value,indent=2));PRIVATE.unlink();print(json.dumps(value))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('run','cleanup'));a=p.parse_args();globals()[a.mode]()
