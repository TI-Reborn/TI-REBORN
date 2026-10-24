"""Verify the actual menu callback reads the new URL in an owned native client.

No authentication or hosted QA accounts. The original callback opens its own
confirmation panel; its URL argument is observed before any browser launch.
"""
from pathlib import Path
import hashlib,json,subprocess,threading,time
import frida,pefile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/menu-website-20261020'
CLIENT=ROOT/'work/personal-gui-all-20261020/gui/game-a'
LAUNCHER=ROOT/'work/menu-website-20261020/launcher/TIO Launcher.exe'
assert (CLIENT/'.tio-owned-qa').is_file()
assert hashlib.sha256((CLIENT/'silver.dll').read_bytes()).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
receipt=OUT/('native-start-'+str(time.time_ns())+'.json')
assert not receipt.exists()
child=subprocess.Popen([str(LAUNCHER),'--tls-qa-start',str(CLIENT),str(receipt)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
child.wait(timeout=75);assert child.returncode==0 and receipt.is_file()
info=json.loads(receipt.read_text());assert info['EndpointCertificatesValidated']
device=frida.get_local_device();session=device.attach(info['Pid']);event=threading.Event();results=[]
probe=session.create_script("rpc.exports={ready(){return {path:Process.mainModule.path,silver:Process.findModuleByName('silver.dll')!==null};}};")
probe.load()
try:
    deadline=time.monotonic()+30
    while True:
        state=probe.exports_sync.ready();assert Path(state['path']).resolve()==CLIENT/'ti.exe'
        if state['silver']:break
        assert time.monotonic()<deadline;time.sleep(.1)
    probe.unload()
    with pefile.PE(str(CLIENT/'silver.dll')) as pe:
        guards={str(va):pe.get_data(va-0x400000,8).hex() for va in (0x888fdc,0x68a0b8)}
    script=session.create_script(r'''
const config=CONFIG;
if(Process.mainModule.path.toLowerCase()!==config.path.toLowerCase())throw Error('Owned client only');
const silver=Process.getModuleByName('silver.dll').base,at=va=>silver.add(va-0x400000);
function hex(p,n){return Array.from(new Uint8Array(p.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join('');}
for(const [va,bytes] of Object.entries(config.guards))if(hex(at(Number(va)),8)!==bytes)throw Error('Native callback changed');
let observed=null,called=false;
Interceptor.attach(at(0x68a0b8),{onEnter(){observed=this.context.eax.readUtf16String();}});
const callback=new NativeFunction(at(0x888fdc),'void',[],{traps:'all'});
const timer=setInterval(()=>{
 const ref=ptr(0x76de0c).readPointer();if(ref.isNull())return;
 const renderer=ref.readPointer();if(renderer.isNull())return;
 const device=renderer.add(0x44).readPointer();if(device.isNull())return;
 clearInterval(timer);
 Interceptor.attach(device.readPointer().add(17*4).readPointer(),{onEnter(args){
  if(called||!args[0].equals(device))return;called=true;callback();
  send({passed:observed==='https://ti-reborn.com/',url:observed,original_menu_callback:'888fdc',
        original_url_opener:'68a0b8',browser_confirmation_accepted:false,accounts_created:0});
 }});
},100);
'''.replace('CONFIG',json.dumps({'path':str(CLIENT/'ti.exe'),'guards':guards})))
    def receive(message,data):
        if message['type']=='send':results.append(message['payload']);event.set()
        elif message['type']=='error':results.append({'passed':False,'error':message.get('description')});event.set()
    script.on('message',receive);script.load()
    assert event.wait(25) and results[0]['passed'],results
    (OUT/'native-menu-link.json').write_text(json.dumps(results[0],indent=2)+'\n',encoding='utf-8')
    print(json.dumps(results[0]))
finally:
    try:session.detach()
    finally:device.kill(info['Pid'])
