"""Bounded read-only native flow observer in an explicitly owned QA client."""
import argparse,hashlib,json,time
from pathlib import Path
import frida
SCRIPT=r"""
let hooks=[],events=[],counts={};
rpc.exports={start(path){
 const norm=s=>s.replace(/\\/g,'/').toLowerCase();if(norm(Process.mainModule.path)!==norm(path))throw Error('Owned path mismatch');
 const silver=Process.getModuleByName('silver.dll'),at=x=>silver.base.add(x-0x400000);
 function field(va){try{const p=at(va).readPointer();return{pointer:p.toString(),visible:p.add(0x49).readU8(),enabled:p.add(0x4a).readU8(),parent:p.add(0x4c).readPointer().toString(),parentVisible:p.add(0x4c).readPointer().add(0x49).readU8()};}catch(e){return{};}}
 function state(){let actors=[];try{const slots=at(0xac618c).readPointer();for(let i=0;i<31;i++){const p=slots.add(i*4).readPointer();if(!p.isNull()&&p.add(0x41).readU8())actors.push({slot:i,id:p.add(0x28).readU32(),level:p.add(0x5ffc).readU32(),selected:p.add(0x5ff1).readU8()});}}catch(e){}return{mode:at(0xac48a0).readU32(),selectorMode:at(0xac4a84).readU8(),mainTable:field(0xacf3a0),typedTable:field(0xacf39c),Team:field(0xad0430),Wall:field(0xad042c),actors};}
 function capture(source,extra={}){counts[source]=(counts[source]||0)+1;const item={source,...extra,state:state()};if(events.length<128&&!events.some(v=>JSON.stringify(v)===JSON.stringify(item)))events.push(item);}
 for(const va of [0x9443d0,0x944434,0x873ad0,0x8723a0,0x8756f0,0x875714,0x85f890,0x873e40,0x873e7f,0x8723e4])hooks.push(Interceptor.attach(at(va),{onEnter(){capture(va.toString(16),{eax:this.context.eax.toUInt32()});}}));
 for(const va of [0xa69ab0,0xa6a114])hooks.push(Interceptor.attach(at(va),{onEnter(){this.keep=false;try{const name=this.context.eax.readUtf16String(80);if(['window_serverlist','window_mercenaries_selector'].includes(name)){this.keep=true;this.name=name;capture(va.toString(16)+'enter',{window:name});}}catch(e){}},onLeave(){if(this.keep)capture(va.toString(16)+'leave',{window:this.name});}}));
 capture('initial');return{pid:Process.id,ready:true,read_only:true,native_ui_calls:false,hooks:hooks.length};
 },stop(){for(const h of hooks)h.detach();Interceptor.flush();return{events,counts,observers_detached:true,read_only:true,native_ui_calls:false};}};
"""
def main():
 p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--sha',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seconds',type=int,default=35);a=p.parse_args()
 root=a.root.resolve();assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()==a.sha
 session=frida.get_local_device().attach(a.pid);script=None;report={}
 try:
  script=session.create_script(SCRIPT);script.load();report=script.exports_sync.start(str(root/'ti.exe'));print(json.dumps(report),flush=True)
  time.sleep(min(50,max(1,a.seconds)));report.update(script.exports_sync.stop());script.unload();script=None
 finally:
  if script is not None:report.update(script.exports_sync.stop());script.unload()
  session.detach()
 report.update(silver_sha256=a.sha,session_detached=True);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(dict(counts=report.get('counts'),events=len(report.get('events',[])),session_detached=True)))
if __name__=='__main__':main()
