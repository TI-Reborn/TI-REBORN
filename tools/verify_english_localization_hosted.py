"""Two disposable, ranking-excluded accounts verify RU/EN on production TLS.

Uses protocol clients, not graphical world/battle acceptance. Private generated
credentials stay in memory; all disposable account/save rows are removed in a
guarded cleanup transaction that fingerprints every unrelated table row.
"""
from pathlib import Path
import hashlib,json,secrets,socket,ssl,subprocess,sys,time
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_game_tls import GameTLSTests
from test_multi_account import MultiAccountTests
from tio.localization import english
from tio.rating_visibility import QA_LOGIN
REPORT=ROOT/'reports/english-localization'

def remote(code,data):
    source='request='+repr(data)+'\n'+code
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88','cd /opt/tio-emulator && .venv/bin/python -'],input=source,encoding='utf-8',capture_output=True,timeout=60)
    if result.returncode:raise RuntimeError('Owned QA administration failed; private diagnostics suppressed')
    return json.loads(result.stdout)

CREATE=r'''
from server.accounts import Accounts
from tio.rating_visibility import QA_LOGIN,excluded
import sqlite3,json
path='/var/lib/tio-server/reservation.sqlite3'
with sqlite3.connect(path) as db:
 before=db.execute('SELECT count(*) FROM accounts').fetchone()[0]
 for name,password in request:
  assert QA_LOGIN.fullmatch(name) and not db.execute('SELECT 1 FROM accounts WHERE login=?',(name,)).fetchone()
for name,password in request:Accounts(path).create(name,password,character=name)
with sqlite3.connect(path) as db:
 assert all(excluded(db,name) for name,password in request)
print(json.dumps(dict(created=len(request),ranking_excluded=True,accounts_before=before)))
'''
CLEANUP=r'''
from tio.rating_visibility import QA_LOGIN
import sqlite3,json,hashlib
names=request;assert len(names)==2 and all(QA_LOGIN.fullmatch(n) for n in names)
owners=names+['@character:'+n+':'+str(s) for n in names for s in range(2,6)]
marks=','.join('?' for _ in owners)
def quote(s):return '"'+s.replace('"','""')+'"'
db=sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15);db.execute('BEGIN IMMEDIATE')
try:
 tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
 immutable={r[0] for r in db.execute("SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND upper(sql) LIKE '%BEFORE DELETE%'")}
 rules={};before={}
 for table in tables:
  columns=[r[1] for r in db.execute('PRAGMA table_info('+quote(table)+')')]
  parts=[];args=[]
  for column in ('account','owner','login'):
   if column in columns:parts.append(quote(column)+' IN ('+marks+')');args+=owners
  condition=' OR '.join(parts) if parts else '0';rules[table]=(condition,args)
  rows=db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall()
  before[table]=hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest()
 foreign=db.execute('PRAGMA foreign_key_check').fetchall();deleted={}
 for table in sorted(tables,key=lambda t:t=='accounts'):
  if table in immutable:continue
  condition,args=rules[table]
  count=db.execute('DELETE FROM '+quote(table)+' WHERE '+condition,args).rowcount
  if count:deleted[table]=count
 for table in tables:
  condition,args=rules[table];rows=db.execute('SELECT * FROM '+quote(table)+' WHERE NOT COALESCE(('+condition+'),0)',args).fetchall()
  assert before[table]==hashlib.sha256(repr(sorted(map(repr,rows))).encode()).hexdigest(),'Unrelated rows changed'
 assert db.execute('PRAGMA foreign_key_check').fetchall()==foreign
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 assert not db.execute('SELECT 1 FROM accounts WHERE login IN (?,?)',names).fetchone()
 assert not db.execute('SELECT 1 FROM characters WHERE account IN (?,?)',names).fetchone()
 db.commit()
 print(json.dumps(dict(deleted=deleted,unrelated_rows_preserved=True,integrity='ok',accounts_after=db.execute('SELECT count(*) FROM accounts').fetchone()[0])))
except Exception:db.rollback();raise
finally:db.close()
'''

def run():
    prefix='ql'+secrets.token_hex(4);names=[prefix+'a',prefix+'b'];passwords=[secrets.token_urlsafe(24) for _ in names]
    assert all(QA_LOGIN.fullmatch(n) for n in names)
    report=dict(kind='two production TLS protocol clients; not graphical world acceptance',passed=False)
    case=MultiAccountTests();case.clients=[]
    tls=GameTLSTests();tls.case=case
    context=ssl.create_default_context()
    def connect(kind,*,preface=None,context_override=None,**kwargs):
        raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
        channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');case.clients.append(channel)
        if preface is not None:channel.sendall(preface)
        return channel
    tls.connect=connect
    created=False
    try:
        report['provisioning']=remote(CREATE,list(zip(names,passwords)));created=True
        peers=[]
        for i,(name,password) in enumerate(zip(names,passwords)):
            peer=tls.handoff(tls.begin(name,31001+i,password=password,language='english' if i else 'russian'));case.enter(peer,name);peers.append(peer)
        for peer in peers:peer.send(b'\x21\0'+'!bank unknown'.encode('utf-16-le')+b'\0\0')
        packets=[peer.until(b'\x22',max_packets=512) for peer in peers]
        texts=[p[p.index(b'\0',6)+1:-2].decode('utf-16-le') for p in packets]
        assert texts[1]==english(texts[0]) and texts[0]!=texts[1]
        chat='Боец не принадлежит вашему аккаунту'
        peers[0].send(b'\x21\0'+chat.encode('utf-16-le')+b'\0\0')
        assert chat.encode('utf-16-le') in peers[1].until(b'\x22',max_packets=512)
        for peer in peers:case.ping(peer)
        report.update(passed=True,checks=['two shared-IP TLS logins and world entries','per-recipient Russian/English private bank rejection','Russian player chat preserved in English recipient','both connections remain live'],system_texts=texts)
    finally:
        for connection in case.clients:
            try:connection.close()
            except OSError:pass
        if created:
            time.sleep(1)
            report['cleanup']=remote(CLEANUP,names)
        (REPORT/'hosted-language-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':run()
