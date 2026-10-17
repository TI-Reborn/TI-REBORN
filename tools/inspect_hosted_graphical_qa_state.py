"""Read-only state snapshot from an explicitly owned hosted native QA PID."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.hosted_graphical_qa_bridge import static_guards

SCRIPT=r'''
rpc.exports.snapshot=function(expectedPath){
  const norm=s=>s.replace(/\\/g,'/').toLowerCase();
  if(norm(Process.mainModule.path)!==norm(expectedPath))throw new Error('Not the owned QA client');
  const silver=Process.getModuleByName('silver.dll');
  const at=va=>silver.base.add(va-0x400000);
  const result={pid:Process.id,read_only:true,fields:{},characters:[],threads:[]};
  function sample(name,read){try{result.fields[name]=read();}catch(e){result.fields[name]='unavailable';}}
  sample('startup_mode',()=>ptr('0x76e2ac').readPointer().readU8());
  sample('startup_loaded',()=>ptr('0x76df14').readPointer().readU8());
  sample('startup_ready',()=>ptr('0x76dbb0').readU8());
  sample('load_state',()=>ptr('0x76deb4').readPointer().readU8());
  sample('startup_clock',()=>ptr('0x76e314').readPointer().readU32());
  sample('startup_deadline',()=>ptr('0x76e568').readPointer().readPointer().add(0x3cc).readU32());
  sample('character_gate',()=>at(0xac5814).readPointer().readU8());
  sample('waiting',()=>at(0xac4c58).readU8());
  sample('selected_character_id',()=>at(0xac4954).readU32());
  sample('town',()=>{const town=at(0xac63bc).readPointer().readPointer().add(8).readPointer();return {id:town.add(8).readU32(),background_loaded:town.add(0x20d).readU8(),background:town.add(0x10e).readCString(town.add(0x10d).readU8())};});
  try{const table=at(0xac618c).readPointer();for(let index=0;index<31;index++){const actor=table.add(index*4).readPointer();if(actor.isNull())continue;result.characters.push({index,id:actor.add(0x28).readU32(),type:actor.add(4).readU32(),unselectable:actor.add(0x60e8).readU8()});}}catch(e){}
  result.threads=Process.enumerateThreads().map(t=>({id:t.id,state:t.state,pc:t.context.pc.toString(),backtrace:Thread.backtrace(t.context,Backtracer.ACCURATE).slice(0,12).map(p=>DebugSymbol.fromAddress(p).toString())}));
  return result;
};
'''

def main():
    import frida
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('game_root',type=Path);p.add_argument('--pid',type=int,required=True)
    p.add_argument('--output',type=Path)
    args=p.parse_args();root=args.game_root.resolve();static_guards(root)
    session=frida.get_local_device().attach(args.pid)
    try:
        script=session.create_script(SCRIPT);script.load()
        result=script.exports_sync.snapshot(str(root/'ti.exe'))
        result['native_files_sha256']={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('ti.exe','orange.dll','silver.dll')}
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result))
    finally:
        session.detach()

if __name__=='__main__':main()
