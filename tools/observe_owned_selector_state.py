"""One read-only selector/roster snapshot of an explicitly owned QA PID."""
import argparse,hashlib,json
from pathlib import Path
import frida
SCRIPT=r"""
rpc.exports={snapshot(path){
 const norm=s=>s.replace(/\\/g,'/').toLowerCase();
 if(norm(Process.mainModule.path)!==norm(path))throw Error('Owned QA process path mismatch');
 const silver=Process.getModuleByName('silver.dll'),at=x=>silver.base.add(x-0x400000);
 function control(name,va){
   const p=at(va).readPointer();if(p.isNull())return{name,va:va.toString(16),pointer:p.toString()};
   const r={name,va:va.toString(16),pointer:p.toString()};
   for(const off of [0x49,0x4a,0x4b])try{r['byte'+off.toString(16)]=p.add(off).readU8();}catch(e){}
   for(const off of [0x4c,0x50,0x54,0x58,0x5c,0x60])try{r['word'+off.toString(16)]=p.add(off).readU32();}catch(e){}
   return r;
 }
 const slots=at(0xac618c).readPointer(),actors=[];
 for(let i=0;i<31;i++){
   const p=slots.add(4*i).readPointer();if(p.isNull()){actors.push({slot:i,present:false});continue;}
   const r={slot:i,pointer:p.toString()};
   try{r.populated=p.add(0x41).readU8();r.selected=p.add(0x5ff1).readU8();r.level=p.add(0x5ffc).readU32();r.identity=p.add(0x28).readU32();r.species=p.add(4).readU32();}catch(e){r.readFailed=true;}
   actors.push(r);
 }
 return{pid:Process.id,path:Process.mainModule.path,silver_base:silver.base.toString(),selector_mode:at(0xac4a84).readU8(),controls:[control('Survival',0xad0428),control('Team',0xad0430),control('Wall',0xad042c),control('selectorOK',0xac4a64)],actors,read_only:true,native_calls:false,ui_inputs:false,interceptor_hooks:0};
}};
"""
def main():
 p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--sha',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 root=a.root.resolve();assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()==a.sha
 session=frida.get_local_device().attach(a.pid);script=None
 try:
  script=session.create_script(SCRIPT);script.load();report=script.exports_sync.snapshot(str(root/'ti.exe'));script.unload();script=None
 finally:
  if script is not None:script.unload()
  session.detach()
 report.update(silver_sha256=a.sha,session_detached=True);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps({k:v for k,v in report.items() if k!='actors'}));print(json.dumps(dict(populated_actors=[r for r in report['actors'] if r.get('populated')])))
if __name__=='__main__':main()
