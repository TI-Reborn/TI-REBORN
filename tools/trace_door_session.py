"""Read-only trace of native movement/door transitions in an existing client."""
import argparse
import json
import time
from pathlib import Path
import frida


SCRIPT = r'''
const base=Process.getModuleByName('ti.exe').base;
const at=a=>base.add(a-0x400000);
function snapshot(){
  const out={busy:at(0x76daac).readU8(),pending:at(0x76d9dc).readU8(),actors:[],doors:[]};
  const actors=at(0x76e430).readPointer();
  for(let i=0;i<31;i++){
    const a=actors.add(i*4).readPointer();if(a.isNull())continue;
    out.actors.push({id:a.add(0x16c).readU32(),owner:a.add(0x64).readU32(),
      model:[a.add(0x1cc).readS32(),a.add(0x1d0).readS32()],
      scene:[a.add(0x1bc).readS32(),a.add(0x1c0).readS32()],waiting:a.add(0x538).readU8()});
  }
  const world=at(0x76e000).readPointer().readPointer();
  const list=world.add(0xd0).readPointer();
  if(!list.isNull()){
    const count=list.add(8).readU32(),items=list.add(4).readPointer();
    for(let i=0;i<Math.min(count,10000);i++){
      const d=items.add(i*4).readPointer(),state=d.add(0x340).readU8();
      if(state)out.doors.push({p:d.toString(),xy:[d.add(4).readS32(),d.add(8).readS32()],state,
        frame:d.add(0x28).readU8(),enabled:d.add(0x3c1).readU8()});
    }
  }
  return out;
}
function report(event,extra={}){try{send({event,...extra,...snapshot()});}catch(e){send({event,error:String(e),...extra});}}
for(const va of [0x6dc460,0x6dc54c,0x6dc600,0x72dc90]){
  Interceptor.attach(at(va),{onEnter(){
    this.args={eax:this.context.eax.toUInt32(),edx:this.context.edx.toUInt32(),ecx:this.context.ecx.toUInt32(),stack:this.context.esp.add(4).readU32()};
    if(va===0x6dc600){const p=this.context.eax;this.args.packet=Array.from(new Uint8Array(p.readByteArray(5+p.add(4).readU8()*2)));}
    if(va===0x6dc460 && this.args.ecx<255){const p=this.context.edx;this.args.path=Array.from({length:this.args.ecx+1},(_,i)=>[p.add(i*8).readS32(),p.add(i*8+4).readS32()]);}
    report(va.toString(16)+'_enter',this.args);
  },onLeave(){report(va.toString(16)+'_leave',this.args);}});
}
let old='';setInterval(()=>{try{const s=snapshot(),value=JSON.stringify(s);if(value!==old){old=value;send({event:'state',...s});}}catch(e){}},500);
'''


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid',type=int)
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--output',type=Path,default=Path('data/door-session.jsonl'))
    parser.add_argument('--apply-grid-fix',action='store_true',help='Apply the launcher door-grid adapter for a live verification')
    args=parser.parse_args()
    with args.output.open('w',encoding='utf-8') as out:
        session=frida.attach(args.pid)
        source=SCRIPT
        if args.apply_grid_fix:
            source+=Path(__file__).with_name('battle_door_grid.js').read_text()
            source+="\ninstallBattleDoorGrid(Process.getModuleByName('ti.exe').base);send({event:'door_grid_fix_installed'});"
        script=session.create_script(source)
        def message(value,data):
            out.write(json.dumps({'time':time.time(),**value})+'\n');out.flush()
        script.on('message',message);script.load()
        try:
            for _ in range(args.seconds):time.sleep(1)
        finally:session.detach()
