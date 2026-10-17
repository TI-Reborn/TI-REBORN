"""Bounded read-only observers for the explicitly owned C legacy QA client."""
import argparse,hashlib,json,time
from pathlib import Path
import frida
SHA="853feb6a3803078ffaf1570969c8432bce37f8c20593acbadcdb5a68f798f3a1"
SCRIPT=r"""
const hooks=[],rows=[];let ready=false;
rpc.exports={
 start(path){
 const norm=s=>s.replace(/\\/g,'/').toLowerCase();
 if(norm(Process.mainModule.path)!==norm(path))throw Error('Owned QA path mismatch');
 const silver=Process.getModuleByName('silver.dll'),at=x=>silver.base.add(x-0x400000);
 function capture(source,row){
  try {const name=row.add(0x14).readPointer().readUtf16String(80).split('\0')[0];
   if(!name.startsWith('qs3110ad96a'))return;
   const value={source,identity:row.readU32(),name,mode:row.add(0x10).readU8(),members:row.add(0x1d).readU8(),capacity:row.add(0x1c).readU8(),minimum:row.add(0x1a).readU8(),maximum:row.add(0x1b).readU8(),soldiers:row.add(0x18).readU8(),colour:row.add(0x24).readU32().toString(16)};
   if(!rows.some(v=>JSON.stringify(v)===JSON.stringify(value)))rows.push(value);
  }catch(e){}
 }
 hooks.push(Interceptor.attach(at(0x85fb8e),{onEnter(){capture('real_BA02_parser85fa88',this.context.ebp.add(8).readPointer().sub(4).readPointer());}}));
 hooks.push(Interceptor.attach(at(0x872f7c),{onEnter(){capture('real_C82C_projection_then_original_insert872f7c',this.context.eax);}}));
 hooks.push(Interceptor.attach(at(0x877b1a),{onEnter(){capture('real_full_native_renderer877158',this.context.ebx);}}));
 ready=true;return {ready,pid:Process.id,read_only:true,hooks:hooks.length};
 },stop(){for(const hook of hooks)hook.detach();Interceptor.flush();return {ready,rows,observers_detached:true,read_only:true,auth_game_ui_calls:false};}
};
"""
def main():
 p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--seconds',type=float,default=45);a=p.parse_args()
 root=a.root.resolve();assert hashlib.sha256((root/'silver.dll').read_bytes()).hexdigest()==SHA
 session=frida.get_local_device().attach(a.pid);script=None;report={}
 try:
  script=session.create_script(SCRIPT);script.load();report=script.exports_sync.start(str(root/'ti.exe'));print(json.dumps(report),flush=True)
  time.sleep(min(60,max(1,a.seconds)))
  report.update(script.exports_sync.stop());script.unload();script=None
 finally:
  if script is not None:
   try:report.update(script.exports_sync.stop());script.unload()
   except Exception:report['cleanup_failed']=True
  session.detach()
  report['session_detached']=True;a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
