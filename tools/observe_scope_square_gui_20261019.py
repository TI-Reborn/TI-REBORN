import frida,json,sys
from pathlib import Path
out=Path('reports/scope-square-20261019');d=json.loads((out/'gui-client.json').read_text());s=frida.attach(d['pid'])
j=s.create_script('''
if(!Process.mainModule.path.toLowerCase().includes('groza-20261019'))throw Error('Own QA only');
const b=Process.getModuleByName('silver.dll').base,a=v=>b.add(v-0x400000);
let markerDraws=0;
Interceptor.attach(a(0xc79227),{onEnter(){markerDraws++;}});
function state(){const g=ptr(0x76e5f4).readPointer().readPointer(),n=a(0xc18bf8).readU32(),cells=[]; for(let i=0;i<Math.min(n,4096);i++){let p=a(0xc18c00).add(i*3),x=p.readU8(),y=p.add(1).readU8(),kind=p.add(2).readU8();cells.push({x,y,kind,seen:g.add(28).readPointer().add(x*4).readPointer().add(y*6).readU8()});}let actors=[],t=a(0xac618c).readPointer();for(let i=0;i<31;i++){let p=t.add(i*4).readPointer();if(!p.isNull()) actors.push({id:p.add(0x28).readU32(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32(),stance:p.add(0x60bc).readU8()});}return {cells,actors};}
Interceptor.attach(a(0xa86a34),{onEnter(){send({event:'scope_change_state',target:this.context.edx.toUInt32()&255});},onLeave(){send({event:'after_change_state',state:state()});}});
Interceptor.attach(a(0x68a7ec),{onEnter(){try{send({event:'native_animation',actor:this.context.eax.toUInt32(),name:this.context.edx.readUtf16String()});}catch(e){}}});
Interceptor.attach(a(0xc798a7),{onLeave(){try{send({event:'after_f7',state:state()});}catch(e){send({error:String(e)});}}});
rpc.exports={state(){return {...state(),markerDraws,markerBranch:Array.from(new Uint8Array(a(0xc7920c).readByteArray(6))).map(v=>v.toString(16).padStart(2,'0')).join('')};}};
''')
def msg(m,_):
 if m.get('type')=='send':
  with (out/'gui-visibility-animation.jsonl').open('a') as f:f.write(json.dumps(m['payload'])+'\n')
  print(json.dumps(m['payload']),flush=True)
j.on('message',msg);j.load();print(json.dumps(j.exports_sync.state()),flush=True)
try:
 for line in sys.stdin:
  if line.strip()=='stop':break
  value=j.exports_sync.state();(out/('gui-'+line.strip()+'.json')).write_text(json.dumps(value,indent=2));print(json.dumps(value),flush=True)
finally:s.detach()
