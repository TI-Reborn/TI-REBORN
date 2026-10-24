"""Call the original BA03 writer in the owned native client's render thread.

This exercises genuine native transport and hosted scene loading, but is not
an acceptance claim for the arena selection button's mouse callback.
"""
from pathlib import Path
import hashlib,json,threading
import frida,pefile
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/personal-gui-all-20261020'
info=json.loads((OUT/'gui-client.json').read_text());root=Path(info['root'])
assert root==ROOT/'work/personal-gui-all-20261020/gui/game-a' and (root/'.tio-owned-qa').is_file()
assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
with pefile.PE(str(root/'silver.dll')) as pe:entry=pe.get_data(0x85f954-0x400000,8).hex()
session=frida.attach(info['pid']);done=threading.Event();result=[]
script=session.create_script(r'''
const config=CONFIG;
if(Process.mainModule.path.toLowerCase()!==config.path.toLowerCase())throw Error('Owned QA only');
const silver=Process.getModuleByName('silver.dll').base,target=silver.add(0x85f954-0x400000);
function hex(p,n){return Array.from(new Uint8Array(p.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join('');}
if(hex(target,8)!==config.entry)throw Error('Native request writer differs');
const code=Memory.alloc(Process.pageSize),bytes=[0x60,0x31,0xc0,0xba,1,0,0,0,0xb9];
const n=target.toUInt32();bytes.push(n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255,0xff,0xd1,0x61,0xc3);
Memory.patchCode(code,bytes.length,p=>p.writeByteArray(bytes));
const request=new NativeFunction(code,'void',[]),device=ptr(0x76de0c).readPointer().readPointer().add(0x44).readPointer();
let sent=false;
Interceptor.attach(device.readPointer().add(17*4).readPointer(),{onEnter(args){
 if(sent||!args[0].equals(device))return;sent=true;request();
 send({passed:true,original_writer:'85f954',request:'BA030001',mouse_callback_verified:false});
}});
'''.replace('CONFIG',json.dumps({'path':str(root/'ti.exe'),'entry':entry})))
def receive(m,d):
    if m['type']=='send':result.append(m['payload']);done.set()
    elif m['type']=='error':result.append({'passed':False,'error':m.get('description')});done.set()
script.on('message',receive);script.load()
try:
    assert done.wait(15) and result[0]['passed'],result
    (OUT/'native-battle-request.json').write_text(json.dumps(result[0],indent=2)+'\n');print(json.dumps(result[0]))
finally:session.detach()
