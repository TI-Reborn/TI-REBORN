"""Read-only diagnosis of an already running, exact marker-owned QA client."""
import argparse
import json
from pathlib import Path
import sys
import time
import frida

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import hosted_stage9_graphical_qa_revision3 as adapter
from tools import prepare_hosted_graphical_qa as prep
from tools.verify_ui_scale_graphical import native_guards

JS = r'''
rpc.exports = { inspect(expected) {
 const exe=Process.mainModule, silver=Process.getModuleByName('silver.dll');
 function norm(p){return p.replace(/\\/g,'/').toLowerCase();}
 if(norm(exe.path)!==norm(expected.executable)||norm(silver.path)!==norm(expected.silver))
   throw new Error('Owned QA module identity differs');
 function at(va){return silver.base.add(va-0x400000);}
 function value(p){try{return p.readU32();}catch(e){return {error:String(e)}}}
 function words(p,n){return Array.from({length:n},(_,i)=>value(p.add(4*i)));}
 const target=ptr(0x777030).readPointer();
 const manager=at(0xb76650).readPointer();
 const state={guiManager:manager.toString(),silverBase:silver.base.toString(),
   portraitState:words(at(0xc2de00),8),coreState:words(at(0xc28f00),16),
   controlsState:words(at(0xc2af00),16),
   tiRendererReference:ptr(0x76de0c).readPointer().toString(),
   tiCVarManager:ptr(0x786788).readPointer().toString(),
   portrait:target.isNull()?null:{object:target.toString(),fields:words(target,27)},
   nativeThreads:Process.enumerateThreads().map(t=>({id:t.id,state:t.state,pc:t.context.pc.toString(),
      stack:Thread.backtrace(t.context,Backtracer.ACCURATE).slice(0,24).map(a=>({address:a.toString(),symbol:DebugSymbol.fromAddress(a).toString()}))}))};
 return state;
}};
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--copy',choices=('a','b'),required=True)
    p.add_argument('--sha',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    root=adapter.own_copy(prep.QA_BASE/('game-'+args.copy))
    native_guards(root,args.sha)
    handle=adapter.OwnedProcessHandle(args.pid,root)
    session=None
    try:
        session=frida.get_local_device().attach(args.pid)
        script=session.create_script(JS);script.load()
        state=script.exports_sync.inspect(dict(executable=str(root/'ti.exe'),silver=str(root/'silver.dll')))
        result=dict(owned_pid=args.pid,copy=args.copy,candidate_sha256=args.sha,
                    read_only=True,ui_native_calls=0,remote_mutations=0,state=state)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
    finally:
        if session is not None: session.detach()
        handle.close()

if __name__=='__main__':main()
