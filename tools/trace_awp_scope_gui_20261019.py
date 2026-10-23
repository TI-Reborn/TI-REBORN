"""Read-only callbacks in the dedicated own QA client; never calls game functions."""
import frida,json,sys
from pathlib import Path
pid=int(sys.argv[1]);session=frida.attach(pid)
script=session.create_script('''
const b=Process.getModuleByName('silver.dll').base,at=v=>b.add(v-0x400000);
if(!Process.mainModule.path.toLowerCase().includes('groza-20261019'))throw Error('Own QA only');
let depth=0;
for(const va of [0x957fe8,0x8b5424,0x8b5a94,0x8b5d6c,0x9d7440,0x9d71f8,0x6a10f4,0x9c04b8,0x8c0730])
Interceptor.attach(at(va),{onEnter(){this.top=[0x957fe8,0x8b5424,0x8b5a94].includes(va);if(this.top)depth++;this.record=depth>0;if(this.record)send({enter:va.toString(16),mode:at(0xac5a30).readPointer().readU8(),target:at(0xacfb9c).readU8(),selected:at(0xac4960).readS32()});},onLeave(r){if(this.record)send({leave:va.toString(16),result:r.toUInt32()&255});if(this.top)depth--;}});
''')
def record(m,d):
 if m.get('type')=='send':
  print(json.dumps(m['payload']),flush=True)
  with Path('reports/awp-scope-20261019/gui-callbacks.jsonl').open('a') as f:f.write(json.dumps(m['payload'])+'\n')
script.on('message',record);script.load();print('Observing own AWP client',flush=True)
try:
 for line in sys.stdin:
  if line.strip()=='stop':break
finally:session.detach()
