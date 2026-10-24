"""Read-only native callback/room evidence for the owned regression client."""
import argparse,json,sys
from pathlib import Path
import frida
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/training-disband-20261018'
def main():
 p=argparse.ArgumentParser();p.add_argument('pid',type=int);p.add_argument('label',choices=('before','after'));args=p.parse_args()
 session=frida.attach(args.pid)
 script=session.create_script('''
const root=Process.mainModule.path.replace(/\\\\/g,'/').toLowerCase();
if(!root.endsWith('/work/training-base-20261018/gui/game-a/ti.exe'))throw new Error('Not own regression process');
const b=Process.getModuleByName('silver.dll').base,at=v=>b.add(v-0x400000);
function state(){return {room_id:at(0xac5f7c).readPointer().readS32(),member:at(0xac585c).readPointer().readU8(),queued:at(0xac5520).readPointer().readU8(),leader:at(0xac63b4).readPointer().readU8(),town:at(0xac5d58).readPointer().readU32()};}
for(const v of [0x792c74,0x639384,0x639220,0xa0948c])Interceptor.attach(at(v),{onEnter(){send({entry:v.toString(16),state:state()});},onLeave(){if(v==0xa0948c)send({deleted_return:state()});}});
rpc.exports={state};send({initial:state()});
''')
 def message(m,d):
  with (OUT/('native-'+args.label+'.jsonl')).open('a') as out:out.write(json.dumps(m)+'\n')
  print(json.dumps(m),flush=True)
 script.on('message',message);script.load()
 try:
  for line in sys.stdin:
   if line.strip()=='state':print(json.dumps(script.exports_sync.state()),flush=True)
   elif line.strip()=='stop':break
 finally:session.detach()
if __name__=='__main__':main()
