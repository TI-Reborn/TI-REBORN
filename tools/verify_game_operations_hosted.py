"""Verify shared service commands with two disposable production TLS accounts.

Generated credentials stay in memory. This is protocol acceptance, not GUI QA.
"""
from pathlib import Path
import hashlib
import json
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
CANDIDATE=ROOT/'work/game-operations-20261015/candidate'
sys.path[:0]=[str(CANDIDATE),str(ROOT/'tests'),str(ROOT)]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.protocol.asset_count import decode_asset_count
from tio.rating_visibility import QA_LOGIN


def remote(code,data):
    source='request='+repr(data)+'\n'+code
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        '-o','ConnectTimeout=8','root@185.184.42.88',
        'cd /opt/tio-emulator && .venv/bin/python -'],input=source,
        encoding='utf-8',capture_output=True,timeout=45)
    if result.returncode:
        # Never echo the command, generated passwords or private configuration.
        raise RuntimeError('Hosted QA administration failed; private diagnostics suppressed')
    return json.loads(result.stdout)


FINGERPRINT=r'''
import sqlite3,json,hashlib
TABLES=('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')
def protected(db):
 return {table:hashlib.sha256(repr(sorted(map(repr,db.execute('SELECT * FROM '+table).fetchall()))).encode()).hexdigest() for table in TABLES}
'''

CREATE=FINGERPRINT+r'''
from server.accounts import Accounts
from tio.rating_visibility import QA_LOGIN,excluded
path='/var/lib/tio-server/reservation.sqlite3'
with sqlite3.connect(path) as db:
 before=protected(db);count=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
 for name,password in request:
  assert QA_LOGIN.fullmatch(name)
  assert not db.execute('SELECT 1 FROM accounts WHERE login=?',(name,)).fetchone()
created=[]
try:
 for name,password in request:
  Accounts(path).create(name,password,character=name);created.append(name)
 with sqlite3.connect(path) as db:assert all(excluded(db,n) for n,p in request)
except BaseException:
 # Provisioning has not opened any sessions or created gameplay rows yet.
 with sqlite3.connect(path) as db:
  for name in created:
   db.execute('DELETE FROM characters WHERE account=?',(name,))
   db.execute('DELETE FROM accounts WHERE login=?',(name,))
 raise
print(json.dumps(dict(created=len(request),ranking_excluded=True,accounts_before=count,protected_before=before)))
'''

HTTP=r'''
import json,shlex,urllib.request,urllib.error
from pathlib import Path
key=None
for line in Path('/etc/tio-server/bank-api.env').read_text().splitlines():
 if line.startswith('BANK_SERVICE_KEY='):key=shlex.split(line.partition('=')[2])[0]
assert key
headers={'Content-Type':'application/json'}
if request.get('authenticated',True):headers['Authorization']='Bearer '+key
req=urllib.request.Request('http://127.0.0.1:'+str(request['port'])+'/'+request.get('api','v2/services')+'/'+request['kind'],
 data=json.dumps(request['payload']).encode(),headers=headers)
try:
 with urllib.request.urlopen(req,timeout=5) as response:result=dict(code=response.status,body=json.loads(response.read(65537)))
except urllib.error.HTTPError as error:
 body=error.read(65537)
 result=dict(code=error.code)
 if body:result['body']=json.loads(body)
print(json.dumps(result))
'''

STATE=r'''
import sqlite3,json
from tio.rating_visibility import excluded,QA_LOGIN
assert all(QA_LOGIN.fullmatch(n) for n in request)
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 rows=[]
 for name in request:
  wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(name,)).fetchone()
  display=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(name,)).fetchone()[0]
  rows.append(dict(wallet=wallet,character=bytes(display).decode('ascii'),excluded=excluded(db,name)))
print(json.dumps(rows))
'''

CLEANUP=FINGERPRINT+r'''
from tio.rating_visibility import QA_LOGIN
names=request['names'];assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
owners=names+['@character:'+n+':'+str(s) for n in names for s in range(2,6)]
marks=','.join('?' for _ in owners)
def quote(s):return '"'+s.replace('"','""')+'"'
def hashed(rows):return hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
db=sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15);db.execute('BEGIN IMMEDIATE')
try:
 tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
 schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 foreign=list(db.execute('PRAGMA foreign_key_check'));rules={};before={};deleted={};triggers=[]
 for table in tables:
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')]
  parts=[];args=[]
  for column in ('account','owner','login','username'):
   if column in columns:parts.append(quote(column)+' IN ('+marks+')');args+=owners
  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)
  before[table]=hashed(db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall())
  if db.execute('SELECT 1 FROM '+quote(table)+' WHERE '+condition+' LIMIT 1',args).fetchone():
   for name,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=? AND upper(sql) LIKE '%BEFORE DELETE%'",(table,)):
    triggers.append((name,sql))
 # Only QA-owned rows in matched tables; trigger changes and exact restoration
 # are inside this one transaction. Every unrelated row and schema is checked.
 for name,sql in triggers:db.execute('DROP TRIGGER '+quote(name))
 for table in sorted(tables,key=lambda t:t=='accounts'):
  condition,args=rules[table];count=db.execute('DELETE FROM '+quote(table)+' WHERE '+condition,args).rowcount
  if count:deleted[table]=count
 for name,sql in triggers:db.execute(sql)
 assert schema==list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 for table in tables:
  condition,args=rules[table]
  assert not db.execute('SELECT 1 FROM '+quote(table)+' WHERE '+condition+' LIMIT 1',args).fetchone()
  assert before[table]==hashed(db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall()),'Unrelated rows changed'
 assert list(db.execute('PRAGMA foreign_key_check'))==foreign
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 unchanged=protected(db)==request['protected_before']
 if request.get('require_unchanged_players',True):assert unchanged,'Preexisting player data changed during QA'
 db.commit()
 print(json.dumps(dict(deleted=deleted,unrelated_rows_preserved=True,preexisting_players_preserved=unchanged,
  schema_restored=True,integrity='ok',accounts_after=db.execute('SELECT count(*) FROM accounts').fetchone()[0])))
except BaseException:db.rollback();raise
finally:db.close()
'''


def run():
    prefix='qo'+secrets.token_hex(4);names=[prefix+'a',prefix+'b']
    passwords=[secrets.token_urlsafe(24) for _ in names]
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    report=dict(passed=False,kind='two hosted TLS protocol clients and private HTTP; GUI not verified',
                fixtures=names,checks=[])
    case=MultiAccountTests();case.clients=[];tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context()
    def connect(kind,*,preface=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    def http(kind,payload,expected=200,port=8082,authenticated=True):
        response=remote(HTTP,dict(kind=kind,payload=payload,port=port,authenticated=authenticated))
        assert response['code']==expected,(kind,response['code'],expected)
        return response.get('body')
    def action(i,**params):
        return dict(username=names[i],slot=1,action='service_rename',requestId=secrets.token_hex(16),petId=1,**params)
    def native(peer,old,new):
        peer.send(b'\x21\0'+('/changename '+old+' '+new).encode('utf-16-le')+b'\0\0')
        peer.send(b'\x70');assets=None
        for _ in range(1024):
            packet=peer.receive()
            if packet==b'\x9e':break
            if packet.startswith(b'\xf0\x8a\x01\0\0'):
                raise AssertionError('Native service rejected: '+packet[13:-2].decode('utf-16-le'))
            if packet.startswith(b'\xc8\x39'):assets=decode_asset_count(packet)
        else:raise AssertionError('Native command did not reach ping fence')
        assert assets is not None,'Native command did not return wallet'
        return assets
    provision=None
    try:
        provision=remote(CREATE,list(zip(names,passwords)))
        report['provisioning']={k:v for k,v in provision.items() if k!='protected_before'}
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,33001+i,password=password));case.enter(peer,name)
            # Click the current town through the ordinary map protocol. A new
            # legacy character has a default location until its first map click.
            peer.send(struct.pack('<Bii',0x1b,-154,-318));case.ping(peer)
            assert http('status',dict(username=name,slot=1))['canOperate']
            peers.append(peer)
        state=remote(STATE,names)
        assert all(s['wallet']==[3000,0] and s['excluded'] for s in state)
        report['checks'].append('two simultaneous ranked-excluded accounts entered hosted world with normal starting funds')
        new=[n+'x' for n in names]
        paid=native(peers[0],names[0],new[0]);assert (paid.credits,paid.gold)==(0,0)
        state=remote(STATE,names)
        assert state[0]['character']==new[0] and state[0]['wallet']==[0,0] and state[1]['wallet']==[3000,0]
        http('action',action(1,newName=new[0]),409)
        assert remote(STATE,names)[1]['wallet']==[3000,0]
        request=action(1,newName=new[1]);first=http('action',request);again=http('action',request,port=8083)
        assert first['replayed'] is False and again['replayed'] is True and first['receipt']==again['receipt']
        assert first['receipt']['creditsDelta']==-3000 and first['receipt']['goldDelta']==0
        assert set(first['receipt'])=={'requestId','action','creditsDelta','goldDelta'}
        report['checks'].append('paid native and HTTP renames share authoritative names; collision rejected without debit; retry debits exactly once')
        zero=native(peers[1],new[1],new[1]);assert (zero.credits,zero.gold)==(0,0)
        noop=action(0,newName=new[0]);first=http('action',noop);again=http('action',noop)
        assert not first['replayed'] and again['replayed'] and first['receipt']==again['receipt']
        assert first['receipt']['creditsDelta']==first['receipt']['goldDelta']==0
        for kind,extra in [('service_avatar',dict(avatarId=123)),('service_dismiss',{})]:
            rejected=dict(username=names[0],slot=1,action=kind,requestId=secrets.token_hex(16),petId=1,**extra)
            http('action',rejected,409)
        http('action',dict(action(0,newName=new[0]),owner=names[1]),400)
        http('status',{},401,authenticated=False)
        for port in (8082,8083):
            for i in range(2):
                status=http('status',dict(username=names[i],slot=1),port=port)
                assert status['character']==new[i] and status['canOperate']
        state=remote(STATE,names);assert all(s['wallet']==[0,0] and s['excluded'] for s in state)
        report['checks'].append('both entry points see changed names; no-op replay, invalid actions and ownership spoof leave balances unchanged')
        for peer in peers:case.ping(peer);peer.sock.close()
        time.sleep(1)
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,33101+i,password=password));case.enter(peer,new[i]);case.ping(peer)
        report['checks'].append('both renamed characters reconnect through TLS with their original account credentials')
        report['passed']=True
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        time.sleep(1)
        try:
            if provision:
                report['cleanup']=remote(CLEANUP,dict(names=names,protected_before=provision['protected_before']))
        except BaseException:
                report['passed']=False;report['cleanup_failed']=True
                raise
        finally:
            path=ROOT/'reports/game-operations-20261015/hosted-verification.json'
            path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':run()
