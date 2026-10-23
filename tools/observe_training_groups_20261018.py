"""Read-only observations in the owned native training client."""
import json,sys
from pathlib import Path
import frida
OUT=Path(__file__).resolve().parents[1]/'reports/training-groups-20261018'
session=frida.attach(int(sys.argv[1]))
script=session.create_script(r'''
if(!Process.mainModule.path.replace(/\\/g,'/').toLowerCase().endsWith('/work/training-base-20261018/gui/game-a/ti.exe'))throw Error('Not own client');
const b=Process.getModuleByName('silver.dll').base,at=v=>b.add(v-0x400000);
function state(){const p=at(0xac5508).readPointer().readPointer();return {room:at(0xac5f7c).readPointer().readS32(),member:at(0xac585c).readPointer().readU8(),right:p.toString(),right_count:p.add(8).readU32(),generic:at(0xacf394).readPointer().toString(),generic_count:at(0xacf394).readPointer().add(8).readU32()};}
for(const v of [0xa08b20,0xa08c68,0x63aa10,0x639198,0x639220,0x872f7c])Interceptor.attach(at(v),{onEnter(){send({entry:v.toString(16),state:state()});},onLeave(){if(v==0xa08b20||v==0xa08c68)send({list_return:v.toString(16),state:state()});}});
rpc.exports={state};
''')
def message(m,d):
 with (OUT/('native-'+sys.argv[2]+'.jsonl')).open('a') as out:out.write(json.dumps(m)+'\n')
 print(json.dumps(m),flush=True)
script.on('message',message);script.load()
try:
 for line in sys.stdin:
  if line.strip()=='stop':break
  print(json.dumps(script.exports_sync.state()),flush=True)
finally:session.detach()
