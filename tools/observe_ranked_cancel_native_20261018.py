import frida,json,sys
from pathlib import Path
out=Path('reports/ranked-cancel-20261018/native-outgoing.jsonl')
s=frida.attach(int(sys.argv[1]))
p=s.create_script(r'''
const b=Process.getModuleByName('silver.dll').base;const at=v=>b.add(v-0x400000);const obj=at(0xac600c).readPointer().readPointer();const flush=obj.readPointer().readPointer();
Interceptor.attach(flush,{onEnter(){let p=this.context.eax,n=p.add(0x1004).readU32();if(n>0&&n<4096){const raw=new Uint8Array(p.add(4).readByteArray(n));if([0xc6,0x67,0x70].includes(raw[0]))send({event:'native_outgoing',hex:Array.from(raw).map(v=>v.toString(16).padStart(2,'0')).join('')});}}});
rpc.exports={state(){const slots=at(0xac618c).readPointer();const pets=[];for(let i=0;i<31;i++){let p=slots.add(i*4).readPointer();if(!p.isNull())pets.push({slot:i,id:p.add(0x28).readU32(),selected:p.add(0x5ff1).readU8()});}return {pets,queue_ui:at(0xac4aa0).readU8()};}};
''')
def msg(m,_):
 if m.get('type')=='send':
  with out.open('a') as f:f.write(json.dumps(m['payload'])+'\n')
  print(json.dumps(m['payload']),flush=True)
p.on('message',msg);p.load();print(json.dumps(p.exports_sync.state()),flush=True)
try:
 for line in sys.stdin:
  if line.strip()=='stop':break
  print(json.dumps(p.exports_sync.state()),flush=True)
finally:s.detach()
