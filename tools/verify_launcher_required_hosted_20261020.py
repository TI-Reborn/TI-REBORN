"""Current public manifests admit two excluded QA accounts; old routes fail."""
import hashlib,json,secrets,socket,ssl,struct,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
saved=list(sys.path)
from tools import verify_warehouse_counters_hosted_20261018 as v
sys.path[:]=saved
OUT=ROOT/'reports/launcher-required-20261020';PRIVATE=ROOT/'.secrets/launcher-required-20261020.json'

def identity():
    origin='https://185.184.42.88/'
    raw=urllib.request.urlopen(origin+'updates/manifest.json',timeout=20).read()
    launcher=json.loads(urllib.request.urlopen(origin+'downloads/launcher-manifest.json',timeout=20).read())
    return hashlib.sha256(raw).digest()+struct.pack('!HHH',*map(int,launcher['version'].split('.')))

class Network(v.Network):
    def __init__(self,data):
        super().__init__(data);proof=identity();context=ssl.create_default_context()
        def connect(kind,*,preface=None,**kwargs):
            raw=socket.create_connection(('185.184.42.88',29512 if kind=='login' else 29513),timeout=15)
            channel=context.wrap_socket(raw,server_hostname='ti-reborn.com');self.case.clients.append(channel)
            port=int.from_bytes(preface[6:8],'big') if preface else 37001
            flags=preface[5] if preface else 0
            channel.sendall(struct.pack('!4sBBH',b'TIOT',2,flags,port)+proof)
            return channel
        self.tls.connect=connect

def provision():
    assert not PRIVATE.exists()
    prefix='qt'+secrets.token_hex(4);data=dict(names=[prefix+'a',prefix+'b'],passwords=[secrets.token_urlsafe(24) for _ in range(2)])
    data['provision']=v.remote(v.CREATE,list(zip(data['names'],data['passwords'])))
    PRIVATE.write_text(json.dumps(data),encoding='utf-8');result=v.remote(v.PREPARE,data['names'])
    (OUT/'fixture-provisioning.json').write_text(json.dumps(result,indent=2))

def run():
    data=json.loads(PRIVATE.read_text());report=dict(passed=False,public_tls=True,graphical_accounts=False,checks={})
    for port in (28512,28513):
        try:
            c=socket.create_connection(('185.184.42.88',port),timeout=3)
        except OSError:pass
        else:c.close();raise AssertionError('Public direct route remains open')
    report['checks']['public_legacy_login_and_session_ports_unreachable']=True
    proof=identity();context=ssl.create_default_context()
    cases=[('old_login',29512,b'TIOT\x01\0'+struct.pack('!H',37001)),('old_session',29513,b'old-game-mode1'),
           ('old_client',29512,struct.pack('!4sBBH',b'TIOT',2,0,37001)+bytes(32)+proof[32:]),
           ('old_launcher',29512,struct.pack('!4sBBH',b'TIOT',2,0,37001)+proof[:32]+struct.pack('!HHH',0,1,22)),
           ('old_game_release',29513,struct.pack('!4sBBH',b'TIOT',2,0,37001)+bytes(32)+proof[32:])]
    for name,port,packet in cases:
        with socket.create_connection(('185.184.42.88',port),timeout=10) as raw:
            with context.wrap_socket(raw,server_hostname='ti-reborn.com') as c:
                c.sendall(packet)
                try:assert c.recv(1)==b'',name
                except (ConnectionResetError,ConnectionAbortedError):pass
        report['checks'][name+'_rejected_before_native_credentials']=True
    net=Network(data)
    try:
        for i in (0,1):net.connect(i)
        initial=[v.values(v.assets(net,i)) for i in (0,1)]
        assert initial==[[3,4540,73,72,71,2,1],[7,1200,74,73,72,3,1]],initial
        for i in (0,1):net.command(i)
        report['checks']['two_current_release_accounts_enter_and_ping_independently']=True
    finally:net.close()
    net=Network(data)
    try:
        for i in (0,1):net.connect(i)
        assert [v.values(v.assets(net,i)) for i in (0,1)]==initial
        report['checks']['authenticated_reconnect_preserves_accounts']=True;report['passed']=True
    finally:net.close()
    (OUT/'hosted-admission.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

def cleanup():
    data=json.loads(PRIVATE.read_text());result=v.remote(v.CLEANUP,dict(names=data['names'],protected_before=data['provision']['protected_before'],require_unchanged_players=False))
    (OUT/'fixture-cleanup.json').write_text(json.dumps(result,indent=2));PRIVATE.unlink();print(json.dumps(result))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','run','cleanup'));a=p.parse_args();globals()[a.mode]()
