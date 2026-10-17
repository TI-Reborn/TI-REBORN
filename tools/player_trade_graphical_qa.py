"""Owned native GUI barter QA via the exact published launcher and real TLS."""
from pathlib import Path
import hashlib,json,subprocess,sys,time,secrets
import pefile,frida
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.verify_english_localization_hosted import remote,CREATE,CLEANUP
from tools.hosted_graphical_qa_bridge import SPANS,HostedGraphicalQaBridge
from tools.hosted_tls_graphical_qa import native_source
from tools.window_compat import install
REPORT=ROOT/'reports/direct-trade-20261014'

COMPLETED = r'''
import json,sqlite3
with sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True) as db:
 completed=[]
 for raw,result in db.execute('SELECT parties,result FROM player_trade_receipts ORDER BY occurred'):
  parties=json.loads(raw)
  if len(parties)==2 and {a for a,p in parties}==set(request):completed.append(json.loads(result))
 current_matches=bool(completed)
 if completed:
  for account,expected in completed[-1].items():
   wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
   bag=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,expected['pet'])).fetchone()
   current_matches &= wallet==(expected['credits'],expected['gold']) and bag is not None and bag[0].hex()==expected['inventory']
 print(json.dumps(dict(committed_receipts=len(completed),current_state_matches_receipt=current_matches)))
'''

def guards(root):
    for n,h in {'ti.exe':'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
                'orange.dll':'5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589',
                'silver.dll':'d533d7ec2eaa5b6134c072be4a55ba3e04f8006a5279fabd645d03c5216c4748'}.items():
        assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h
    assert (root/'.tio-owned-qa').is_file()
    assert not (root/'login.ini').exists() and not (root/'base/login.ini').exists()
    p=pefile.PE(str(root/'silver.dll'));result=[]
    for n,a,s,h in SPANS:
        data=p.get_data(a-0x400000,s);assert hashlib.sha256(data).hexdigest()==h
        reloc=[e.rva-(a-0x400000) for b in p.DIRECTORY_ENTRY_BASERELOC for e in b.entries if e.type==3 and a-0x400000<=e.rva<a-0x400000+12]
        result.append(dict(name=n,va=a,entry12=data[:12].hex(),entry_relocations=reloc))
    return result

class Bridge(HostedGraphicalQaBridge):
    def __init__(self,root,login,password,ready):
        self.root=root;self.pid=ready['Pid'];self.bridge_pid=ready['BridgePid']
        self.events=[];self._runtime_errors=[];self._on_event=None;self.window_script=None;self.closed=False
        self.device=frida.get_local_device();self.session=self.device.attach(self.pid)
        source=native_source(ready['LoginPort'],ready['SessionPort'])
        # Launcher 0.1.4+ pins CMP AL,0, matching ORANGE's byte mode. Keep
        # every route byte checked, using the current published thunk layout.
        assert source.count('0x18,0x83,0xf8,0,0xb8')==1
        source=source.replace('0x18,0x83,0xf8,0,0xb8','0x18,0x80,0xf8,0,0xb8')
        self.script=self.session.create_script(source)
        def receive(message,data):
            if message.get('type')=='send':self.events.append(message.get('payload',{}))
            else:self._runtime_errors.append(message.get('type','unknown'))
        self.script.on('message',receive);self.script.load()
        self.script.exports_sync.initialize(dict(executable=str(root/'ti.exe'),silver_path=str(root/'silver.dll'),entry_guards=guards(root),
            login=login,password=password,auto_select=True,loopback_login_port=ready['LoginPort'],loopback_session_port=ready['SessionPort'],
            verified_tls_route=True,session_host='127.0.0.1',session_port=ready['SessionPort']))
        self.window_script=install(self.session,receive)
        self.trade=None

def main():
    prefix='qt'+secrets.token_hex(4);names=[prefix+'a',prefix+'b'];passwords=[secrets.token_urlsafe(24) for _ in names]
    bridges=[];pids=[];created=False;report=dict(graphical_clients_used=True,passed=False,actions=[])
    launcher=ROOT/'reports/english-startup-fix-20261014/launcher/TIO Launcher.exe'
    assert hashlib.sha256(launcher.read_bytes()).hexdigest()=='9714367635045e0ec7011b153f13ef3403803fad974ffa61e04f569cdc4a24f2'
    try:
        report['provisioning']=remote(CREATE,list(zip(names,passwords)));created=True
        for i in range(2):
            root=REPORT/'client-qa'/('game-'+('a' if i==0 else 'b'));guards(root)
            receipt=REPORT/f'gui-ready-{prefix}-{i}.json'
            if receipt.exists():raise FileExistsError(receipt)
            r=subprocess.run([str(launcher),'--tls-qa-start',str(root),str(receipt)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=75)
            assert r.returncode==0
            ready=json.loads(receipt.read_text());assert ready['EndpointCertificatesValidated']
            time.sleep(4)  # Wait for native menu/config initialization before auth.
            pids.append(ready['Pid']);bridge=Bridge(root,names[i],passwords[i],ready);bridges.append(bridge);bridge.start_connect()
        for bridge in bridges:
            deadline=time.monotonic()+40
            while not bridge.status()['worldStartSent'] and time.monotonic()<deadline:time.sleep(.25)
            assert bridge.status()['worldStartSent'], 'Owned native login did not reach the world'
            bridge.trade=bridge.session.create_script((ROOT/'tools/player_trade_graphical_qa.js').read_text());bridge.trade.load()
        print(json.dumps(dict(event='owned_native_clients_ready',pids=pids)),flush=True)
        for line in sys.stdin:
            command=json.loads(line);action=command.get('action')
            if action=='status':
                print(json.dumps(dict(event='status',clients=[dict(pid=b.pid,login=b.status(),trade=b.trade.exports_sync.status()) for b in bridges])),flush=True)
            elif action=='reload':
                for b in bridges:
                    b.trade.unload();b.trade=b.session.create_script((ROOT/'tools/player_trade_graphical_qa.js').read_text());b.trade.load()
                print(json.dumps(dict(event='trade_observer_reloaded')),flush=True)
            elif action=='cleanup':break
            elif action in ('invite','answer','offer','confirm'):
                args=command.get('args',{})
                if action=='invite':args['name']=names[1]
                result=bridges[command.get('client',0)].trade.exports_sync.action(action,args)
                report['actions'].append(dict(action=action,client=command.get('client',0)))
                print(json.dumps(dict(event='action_queued',action=action,result=result)),flush=True)
            else:print(json.dumps(dict(event='unknown_action')),flush=True)
        report['native_status']=[dict(pid=b.pid,login=b.status(),trade=b.trade.exports_sync.status()) for b in bridges]
        report['committed_state']=remote(COMPLETED,names)
        report['passed']=all(s['trade']['starts'] and s['trade']['done'] and not s['trade']['fault']
                             for s in report['native_status']) and report['committed_state']['current_state_matches_receipt']
    finally:
        for bridge in bridges:
            try:
                if bridge.trade is not None:bridge.trade.unload()
                bridge.release(cleanup=True)
            except Exception:pass
        for pid in pids:
            # PID came only from this exact launcher's owned readiness receipt.
            subprocess.run(['powershell.exe','-NoProfile','-Command',f'Stop-Process -Id {pid} -ErrorAction SilentlyContinue'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if created:
            time.sleep(1)
            from tools.player_trade_qa_cleanup import RECEIPT_CLEANUP
            report['receipt_cleanup']=remote(RECEIPT_CLEANUP,names)
            report['cleanup']=remote(CLEANUP,names)
        (REPORT/'graphical-qa.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(event='finished',passed=report['passed'])),flush=True)
if __name__=='__main__':
    try:main()
    except Exception as error:
        # Frida RPC diagnostics contain authored assertion text, not credentials.
        reason=str(error).splitlines()[0][:200]
        print(json.dumps(dict(event='graphical_qa_failed',error_type=type(error).__name__,reason=reason)),flush=True)
        raise SystemExit(1)
