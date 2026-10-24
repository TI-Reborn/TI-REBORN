"""Send one genuine skill request with the original writer in our owned client.

This exercises native transport + hosted authority + graphical rendering.
It is a native-protocol acceptance action, not a mouse-click acceptance test.
"""
import frida,json,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import verify_scope_square_hosted_20261019 as scope
qa=scope.qa;data=qa.load();out=qa.OUT
qa.STATE=qa.STATE.replace('result=dict(match=row[0]',
    'result=dict(remaining=max(0,turn[2]-__import__("time").monotonic()) if turn else 0,match=row[0]')
client=json.loads((out/'gui-client.json').read_text());root=Path(client['root'])
assert (root/'.tio-owned-qa').is_file()
assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'
deadline=time.monotonic()+90
ready=json.loads((out/'gui-ready.json').read_text())
while time.monotonic()<deadline:
    f=qa.state(data)
    a=next((a for a in f['actors'] if a['account']==data['names'][0] and a['owner']==f['turn'] and a['ap']>=3),None)
    if a and f['remaining']>=25:
        start=next(row for row in ready['actors'] if row['id']==a['id'])
        assert (a['x'],a['y'])==(start['x'],start['y'])
        f['aim']=ready['aim'];break
    time.sleep(1)
else:raise AssertionError('No valid own scope turn')
session=frida.attach(client['pid'])
script=session.create_script('''
const request=REQUEST;
if(Process.mainModule.path.toLowerCase()!==request.path.toLowerCase())throw Error('Own client only');
const silver=Process.getModuleByName('silver.dll').base,at=v=>silver.add(v-0x400000);
let actor=null,table=at(0xac618c).readPointer();
for(let i=0;i<31;i++){const p=table.add(i*4).readPointer();if(!p.isNull()&&p.add(0x28).readU32()===request.actor)actor=p;}
if(actor===null||actor.add(0x41).readU8()!==1)throw Error('Own native actor required');
const code=Memory.alloc(Process.pageSize),bytes=[0x53,0x68];
function u32(v){for(let n=0;n<4;n++)bytes.push((v>>>(n*8))&255);}
u32(request.x);bytes.push(0x68);u32(request.y);bytes.push(0xb8);u32(9);
bytes.push(0xba);u32(request.actor);bytes.push(0x31,0xc9,0xbb);u32(at(0x8c0730).toUInt32());
bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
const cast=new NativeFunction(code,'void',[]);let sent=false;
Interceptor.attach(at(0x814608),{onEnter(){if(!sent){sent=true;cast();send({sent:true,actor:request.actor,center:[request.x,request.y],original_writer:'8c0730'});}}});
rpc.exports={sent(){return sent;},state(){
 let actors=[];for(let i=0;i<31;i++){let p=table.add(i*4).readPointer();if(!p.isNull())actors.push({id:p.add(0x28).readU32(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32(),stance:p.add(0x60bc).readU8()});}
 const n=at(0xc18bf8).readU32(),g=ptr(0x76e5f4).readPointer().readPointer(),cells=[];
 for(let i=0;i<n;i++){let p=at(0xc18c00).add(i*3),x=p.readU8(),y=p.add(1).readU8();cells.push({x,y,kind:p.add(2).readU8(),seen:g.add(28).readPointer().add(x*4).readPointer().add(y*6).readU8()});}
 return {actors,cells};
}};
'''.replace('REQUEST',json.dumps(dict(path=str(root/'ti.exe'),actor=a['id'],x=f['aim'][0],y=f['aim'][1]))))
events=[]
script.on('message',lambda m,_:events.append(m.get('payload',m)));script.load()
try:
    deadline=time.monotonic()+8
    while not script.exports_sync.sent() and time.monotonic()<deadline:time.sleep(.1)
    assert script.exports_sync.sent()
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        native=script.exports_sync.state()
        if (len(native['cells'])==9 and all(c['seen']==1 for c in native['cells'])
                and any(r['id']!=a['id'] and r['x']!=255 for r in native['actors'])
                and any(r['id']==a['id'] and r['stance']==1 for r in native['actors'])):break
        time.sleep(.1)
    else:raise AssertionError(native)
    after=qa.state(data)
    assert len(after['cells'][str(a['owner'])])==9
    (out/'gui-native-request.json').write_text(json.dumps(dict(passed=True,method=__doc__,events=events,before=f,after=after,native=native),indent=2))
    print(json.dumps(dict(passed=True,events=events)))
finally:session.detach()
