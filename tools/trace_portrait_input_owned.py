"""Observe real mouse dispatch in an exact owned QA client; never send input."""
import argparse
import json
from pathlib import Path
import sys
import time
import frida
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import prepare_hosted_graphical_qa as prep, hosted_stage9_graphical_qa_revision3 as adapter
from tools.verify_ui_scale_graphical import native_guards

JS=r'''
'use strict';
rpc.exports={install(expected){
 const silver=Process.getModuleByName('silver.dll');
 function norm(s){return s.replace(/\\/g,'/').toLowerCase();}
 if(norm(Process.mainModule.path)!==norm(expected.exe)||norm(silver.path)!==norm(expected.silver))throw new Error('Foreign process');
 function at(va){return silver.base.add(va-0x400000);}
 function name(p){try{const s=p.add(0x68).readPointer();if(s.isNull())return null;const n=s.sub(4).readU32();return n<=128?s.readUtf16String(n):'invalid:'+n;}catch(e){return 'error:'+e;}}
 function geo(p){if(p.isNull())return null;return {ptr:p.toString(),vmt:p.readPointer().sub(silver.base).add(0x400000).toString(),name:name(p),namePtr:p.add(0x68).readPointer().toString(),
  visible:p.add(0x49).readU8(),x:p.add(0x30).readS32(),y:p.add(0x34).readS32(),w:p.add(0x38).readS32(),h:p.add(0x3c).readS32(),parent:p.add(0x4c).readPointer().toString()};}
 function ancestors(p){const a=[];for(let i=0;i<20&&!p.isNull();i++,p=p.add(0x4c).readPointer())a.push(geo(p));return a;}
 let active=false;
 const charVmt=at(0x8a22e4),renderVmt=at(0xa2c1b0).readPointer();
 Interceptor.attach(at(0x9f484c),{onEnter(args){send({event:'native_mouse_input',button:args[0].toUInt32(),x:args[1].toUInt32(),y:args[2].toUInt32()});}});
 Interceptor.attach(at(0xc2c000),{onEnter(){active=true;const manager=at(0xb76650).readPointer(),hover=manager.add(0x2d4).readPointer();
  send({event:'portrait_dispatch_enter',button:this.context.ebx.toUInt32(),x:this.context.esi.toInt32(),y:this.context.edi.toInt32(),hover:geo(hover),hoverAncestors:ancestors(hover),charVmt:charVmt.toString(),renderVmt:renderVmt.toString(),shopNameLiteral:at(0x8d5acc).readUtf16String()});}});
 Interceptor.attach(at(0xc2c200),{onEnter(){this.ptr=this.context.eax;const vmt=this.ptr.readPointer();this.candidate=vmt.equals(charVmt)||vmt.equals(renderVmt);
  if(this.candidate)send({event:'portrait_walk_candidate',control:geo(this.ptr),ancestors:ancestors(this.ptr),x:this.context.edx.toInt32(),y:this.context.ecx.toInt32()});},
  onLeave(result){if(this.candidate)send({event:'portrait_walk_result',control:this.ptr.toString(),matched:result.toString()});}});
 Interceptor.attach(at(0xc2b000),{onEnter(){send({event:'portrait_mouse_match',control:geo(this.context.eax),button:this.context.edx.toUInt32()&255,x:this.context.ecx.toInt32(),y:this.context.esp.add(4).readS32()});}});
 return {ready:true,ownedPid:Process.id,uiInputsSent:0};
}};
'''

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--pid',type=int,required=True);p.add_argument('--sha',required=True)
 p.add_argument('--copy',choices=('a','b'),required=True);p.add_argument('--seconds',type=int,default=180)
 p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 root=adapter.own_copy(prep.QA_BASE/('game-'+args.copy));native_guards(root,args.sha)
 h=adapter.OwnedProcessHandle(args.pid,root);s=None
 try:
  s=frida.get_local_device().attach(args.pid);script=s.create_script(JS)
  args.output.parent.mkdir(parents=True,exist_ok=True)
  def receive(message,_):
   row=message.get('payload',message)
   with args.output.open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
   print(json.dumps(row,ensure_ascii=False),flush=True)
  script.on('message',receive);script.load()
  print(json.dumps(script.exports_sync.install(dict(exe=str(root/'ti.exe'),silver=str(root/'silver.dll')))),flush=True)
  time.sleep(args.seconds)
 finally:
  if s:s.detach()
  h.close()
if __name__=='__main__':main()
