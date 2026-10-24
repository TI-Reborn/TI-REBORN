"""Two reserved, excluded QA accounts; native clan protocol on live hosting."""
import argparse,hashlib,json,secrets,socket,ssl,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.verify_game_operations_hosted import CREATE,CLEANUP,remote
from tools.verify_training_base_20261018_hosted import PREPARE
from test_multi_account import MultiAccountTests
from test_game_tls import GameTLSTests
from tio.protocol.clan_crests import encode_request,decode_content
def encode_upload(raw):
 raw=raw or b'';assert len(raw)<=824
 return b'\x58'+struct.pack('<H',len(raw))+raw
OUT=ROOT/'reports/clan-icons-20261018';PRIVATE=ROOT/'.secrets/clan-icons-20261018.json'

STATE=r'''
import sqlite3,json,hashlib
from tio.rating_visibility import QA_LOGIN,excluded
from tio.clan_benefits import crest_id,crest_content
assert all(QA_LOGIN.fullmatch(n) for n in request['names'])
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 cid=request['clan'];assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==(request['names'][0],)
 identity=crest_id(db,cid)
 print(json.dumps(dict(clan=cid,crest=identity,sha256=hashlib.sha256(crest_content(db,identity)).hexdigest() if identity else None,wallets=[db.execute('SELECT credits FROM wallets WHERE account=?',(n,)).fetchone()[0] for n in request['names']],excluded=all(excluded(db,n) for n in request['names']))))
'''

class Clients:
 def __init__(self,data):
  self.data=data;self.case=MultiAccountTests();self.case.clients=[];self.tls=GameTLSTests();self.tls.case=self.case
  context=ssl.create_default_context()
  def connect(kind,*,preface=None,**kwargs):
   raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
   channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');self.case.clients.append(channel)
   if preface is not None:channel.sendall(preface)
   return channel
  self.tls.connect=connect;self.peers={}
 def connect(self,i):
  peer=self.tls.handoff(self.tls.begin(self.data['names'][i],37001+i,password=self.data['passwords'][i]));self.case.enter(peer,self.data['names'][i]);self.peers[i]=peer
  return peer
 def command(self,i,packet=b'\x70',allow_error=False):
  peer=self.peers[i]
  if packet!=b'\x70':peer.send(packet)
  peer.send(b'\x70');rows=[];fenced=False
  for _ in range(2048):
   row=peer.receive();rows.append(row)
   if row[:5]==b'\xf0\x8a\x01\0\0' and not allow_error:raise AssertionError('QA native request rejected: '+row[13:-2].decode('utf-16le',errors='replace'))
   if row==b'\x9e':fenced=True
   expected=b'\x5a' if packet[:1]==b'\x59' else b'\xf0' if allow_error else None
   if fenced and (expected is None or any(p.startswith(expected) for p in rows)):return rows
  raise AssertionError('Missing ping fence')
 def close(self):
  for channel in self.case.clients:
   try:channel.close()
   except OSError:pass

def state(data):return remote(STATE,dict(names=data['names'],clan=data['clan']))

def provision():
 if PRIVATE.exists():
  data=json.loads(PRIVATE.read_text());assert not data.get('clan');prefix=data['names'][0][:-1]
 else:
  prefix='qt'+secrets.token_hex(4);data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
  data['provision']=remote(CREATE,list(zip(data['names'],data['passwords'])));PRIVATE.write_text(json.dumps(data))
 preparation=PREPARE.replace('19,*center(19)','3,*center(3)').replace('town=19','town=3')
 preparation=preparation.replace("assert not db.execute('SELECT 1 FROM owned_pets WHERE account=?',(name,)).fetchone()", "db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(raw,name))")
 remote(preparation,data['names']);clients=Clients(data)
 try:
  for i in range(2):clients.connect(i)
  rows=clients.command(0,b'\x52'+('Crest '+prefix[2:]).encode()+b'\0')
  joined=next(r for r in rows if r[:1]==b'\x5e');data['clan']=struct.unpack_from('<I',joined,1)[0];PRIVATE.write_text(json.dumps(data))
  clients.command(0,b'\x5b'+data['names'][1].encode()+b'\0');clients.command(1,b'\x5d\x01')
  result=state(data);assert result['excluded'] and result['wallets']==[3000,3000]
  (OUT/'fixture-provisioning.json').write_text(json.dumps(dict(**result,accounts_before=data['provision']['accounts_before'],native_clan_creation=True,two_members=True),indent=2));print(json.dumps(result))
 finally:clients.close()

def cleanup():
 data=json.loads(PRIVATE.read_text());assert data.get('clan')
 code=CLEANUP.replace("tables=[r[0]", "cid=request['clan'];assert db.execute('SELECT leader FROM clans WHERE id=?',(cid,)).fetchone()==(names[0],)\n assert {r[0] for r in db.execute('SELECT account FROM clan_members WHERE clan_id=?',(cid,))}<=set(names)\n tables=[r[0]")
 old="condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
 new="\n  if 'clan_id' in columns:parts.append(quote('clan_id')+'=?');args.append(cid)\n  if table=='clans':parts.append('id=?');args.append(cid)\n  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)"
 assert old in code;code=code.replace(old,new)
 result=remote(code,dict(names=data['names'],clan=data['clan'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
 (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

def watch():
 data=json.loads(PRIVATE.read_text());clients=Clients(data);clients.connect(1)
 print(json.dumps(dict(second_account_connected=True,state=state(data))),flush=True)
 try:
  for line in sys.stdin:
   command=line.strip()
   if command=='stop':break
   current=state(data)
   if command=='verify':
    assert current['crest'] and current['sha256']==hashlib.sha256((OUT/'clan-normalized.bmp').read_bytes()).hexdigest()
    rows=clients.command(1,encode_request(current['crest']));content=decode_content(next(r for r in rows if r[:1]==b'\x5a'))
    assert content.bmp==(OUT/'clan-normalized.bmp').read_bytes()
    current['second_account_verified']=True;(OUT/'second-account-verification.json').write_text(json.dumps(current,indent=2))
   elif command=='forbidden':
    rows=clients.command(1,encode_upload((OUT/'clan-normalized.bmp').read_bytes()),allow_error=True)
    assert any(r[:1]==b'\xf0' for r in rows) and current==state(data);current['member_upload_denied']=True
   else:clients.command(1)
   print(json.dumps(current),flush=True)
 finally:clients.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','watch','cleanup','state'));a=p.parse_args()
 if a.mode=='provision':provision()
 elif a.mode=='cleanup':cleanup()
 elif a.mode=='watch':watch()
 else:print(json.dumps(state(json.loads(PRIVATE.read_text()))))
