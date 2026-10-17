"""Bounded read-only owned client cache/filter observer; no native UI calls."""
import argparse,hashlib,json,time
from pathlib import Path
import frida
SCRIPT=r"""
const hooks=[],events=[];let snapshots=[],takeSnapshot=null;
rpc.exports={start(path){
 const norm=s=>s.replace(/\\/g,'/').toLowerCase();if(norm(Process.mainModule.path)!==norm(path))throw Error('Owned QA path mismatch');
 const silver=Process.getModuleByName('silver.dll'),at=x=>silver.base.add(x-0x400000);
 function row(p){try{const name=p.add(0x14).readPointer().readUtf16String(100);if(!name.startsWith('qs3110ad96a'))return null;return{pointer:p.toString(),name,id:p.readU32(),mode:p.add(0x10).readU8(),members:p.add(0x1d).readU8(),capacity:p.add(0x1c).readU8(),status:p.add(0x1e).readU8(),levelMin:p.add(0x1a).readU8(),levelMax:p.add(0x1b).readU8(),filter21:p.add(0x21).readU8(),colour:p.add(0x24).readU32().toString(16),blocked:p.add(0x28).readU8()};}catch(e){return null;}}
 function collection(p){try{const count=p.add(8).readU32(),items=p.add(4).readPointer(),rows=[];if(count>256)return{count,error:'count bound'};for(let i=0;i<count;i++){const value=row(items.add(4*i).readPointer());if(value)rows.push(value);}return{pointer:p.toString(),count,ownedCaptainRows:rows};}catch(e){return{pointer:p.toString(),error:String(e)};}}
 function control(va){try{const p=at(va).readPointer(),ancestors=[];let q=p;for(let i=0;i<6&&!q.isNull();i++){const r={pointer:q.toString(),visible:q.add(0x49).readU8()};try{r.name=q.add(0x68).readPointer().readUtf16String(80);}catch(e){}ancestors.push(r);q=q.add(0x4c).readPointer();}return{pointer:p.toString(),visible:p.add(0x49).readU8(),parent:p.add(0x4c).readPointer().toString(),ancestors,type2ac:p.add(0x2ac).readU8(),selected280:p.add(0x280).readS32(),filtered:collection(p.add(0x2a8).readPointer())};}catch(e){return{error:String(e)};}}
 function snapshot(source){const r={source,mode:at(0xac48a0).readU32(),selectorMode:at(0xac4a84).readU8(),BAparserMode:at(0xac55a4).readPointer().readU32(),BAparserCharacterLevel:at(0xac5b7c).readPointer().add(0x24c).readU32(),BAcache:collection(at(0xacf398).readPointer()),C8cache:collection(at(0xacf394).readPointer()),BAtable:control(0xacf3a0),C8table:control(0xacf39c)};try{let actors=[];const slots=at(0xac618c).readPointer();for(let i=0;i<31;i++){const p=slots.add(4*i).readPointer();if(!p.isNull()&&p.add(0x41).readU8())actors.push({slot:i,id:p.add(0x28).readU32(),level:p.add(0x5ffc).readU32(),selected:p.add(0x5ff1).readU8()});}r.actors=actors;}catch(e){}if(!snapshots.some(v=>JSON.stringify(v)===JSON.stringify(r)))snapshots.push(r);return r;}
 takeSnapshot=snapshot;
 function capture(source,p,extra={}){const value=row(p);if(value){const r={source,row:value,...extra};if(events.length<128&&!events.some(v=>JSON.stringify(v)===JSON.stringify(r)))events.push(r);}}
 hooks.push(Interceptor.attach(at(0x876c44),{onEnter(){this.p=this.context.eax;snapshot('876c44-entry');},onLeave(){snapshot('876c44-exit');}}));
 hooks.push(Interceptor.attach(at(0x85fb8e),{onEnter(){capture('BA02-parse',this.context.ebp.add(8).readPointer().sub(4).readPointer());}}));
 hooks.push(Interceptor.attach(at(0x85fc7c),{onEnter(){capture('BA02-rejected-before-cache',this.context.ebp.add(8).readPointer().sub(4).readPointer(),{parserMode:at(0xac55a4).readPointer().readU32(),characterLevel:at(0xac5b7c).readPointer().add(0x24c).readU32()});}}));
 hooks.push(Interceptor.attach(at(0x872f7c),{onEnter(){capture('C82C-projection',this.context.eax);}}));
 for(const va of [0x876dcc,0x876dee,0x876e45,0x876e78,0x876ec0])hooks.push(Interceptor.attach(at(va),{onEnter(){capture(va.toString(16),this.context.edi,{currentCharacterType:this.context.ebx.toUInt32()&255,tableType:this.context.esi.add(0x2ac).readU8()});}}));
 const initial=snapshot('initial');return{ready:true,pid:Process.id,read_only:true,native_ui_calls:false,hooks:hooks.length,initial};
},stop(){takeSnapshot('final');for(const h of hooks)h.detach();Interceptor.flush();return{events,snapshots,observers_detached:true,read_only:true,native_ui_calls:false};}};
"""

def main():
 p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--sha',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seconds',type=int,default=30);a=p.parse_args()
 root=a.root.resolve();assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()==a.sha
 session=frida.get_local_device().attach(a.pid);script=None;report={}
 try:
  script=session.create_script(SCRIPT);script.load();report=script.exports_sync.start(str(root/'ti.exe'));print(json.dumps(report),flush=True)
  time.sleep(min(50,max(1,a.seconds)));report.update(script.exports_sync.stop());script.unload();script=None
 finally:
  if script is not None:
   try:report.update(script.exports_sync.stop())
   finally:script.unload()
  session.detach()
 report.update(silver_sha256=a.sha,session_detached=True);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8');print(json.dumps(dict(events=len(report['events']),snapshots=len(report['snapshots']),session_detached=True)))
if __name__=='__main__':main()
