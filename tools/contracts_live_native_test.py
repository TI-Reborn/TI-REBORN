"""Narrow local QA driver for already authenticated, owned native clients.

Submits only whitelisted C2S test requests through original Silver encryption /
ORANGE transport. No server replies, database writes, GUI handlers, input events,
authentication changes, or native-code patches. Snapshots are read-only.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
import time

import frida
import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OWNED = ROOT/'reports/contracts-local/clients'
PINS = {
    'ti.exe': 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c',
    'orange.dll': '5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589',
    'silver.dll': 'f05790b04bbb6a76349d1540f12e45e14912bcbcd5a6c746b72288635e9c69eb',
}
COMMANDS = {
    'ready': '!party ready', 'party-status': '!party status',
    'take-camp': '!contracts take camp', 'status': '!contracts status',
    'start': '!contracts start',
}

SCRIPT = r'''
let silver, exe, expectedPath;
const tickCounts={};
const norm=s=>s.replace(/\\/g,'/').toLowerCase();
const bytes=p=>Array.from(new Uint8Array(p));
const at=va=>silver.base.add(va-0x400000);
rpc.exports.initialize=function(options){
  expectedPath=options.path;
  if(Process.arch!=='ia32' || norm(Process.mainModule.path)!==norm(expectedPath))throw Error('Unexpected owned process');
  exe=Process.mainModule;
  silver=Process.getModuleByName('silver.dll');
  if(norm(silver.path)!==norm(options.silverPath))throw Error('Unexpected Silver path');
  if(norm(Process.getModuleByName('orange.dll').path)!==norm(options.orangePath))throw Error('Unexpected Orange path');
  for(const span of options.spans){
    const expected=Uint8Array.from(span.bytes);
    const delta=silver.base.toUInt32()-0x400000;
    const view=new DataView(expected.buffer);
    for(const offset of span.relocations)view.setUint32(offset,(view.getUint32(offset,true)+delta)>>>0,true);
    const live=bytes(at(span.va).readByteArray(expected.length));
    if(live.some((value,index)=>value!==expected[index]))throw Error('Original network span differs');
  }
  return {pid:Process.id,original_network_spans_verified:true};
};
rpc.exports.submit=function(action){
  const commands={ready:'!party ready','party-status':'!party status','take-camp':'!contracts take camp',status:'!contracts status',start:'!contracts start'};
  const code=[];
  const u32=n=>[n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255];
  // Preserve registers/flags around the original networking-only function.
  code.push(0x9c,0x60);
  let payload;
  if(action==='travel-city' || action==='travel-camp'){
    const target=action==='travel-city'?[-154,-318]:[-280,-235];
    code.push(0xb8,...u32(target[0]),0xba,...u32(target[1]),0xb9,...u32(at(0x889e5c).toUInt32()),0xff,0xd1);
  }else{
    if(!Object.prototype.hasOwnProperty.call(commands,action) && !['heal-result','heal-current','exit-result','abort','end-turn'].includes(action))throw Error('Action is not whitelisted');
    const command=commands[action];
    let raw;
    if(action==='exit-result' || action==='abort')raw=[0x2a,1];
    else if(action==='end-turn'){
      if(at(0xac64a0).readPointer().readU8()!==1 || at(0xac6264).readPointer().readU8()!==1 || at(0xac5a98).readPointer().readU32()!==at(0xac5cd4).readPointer().readU32())throw Error('Native own turn required');
      raw=[0x3a,0,0,0,0];
    }
    else if(action==='heal-current'){
      const table=at(0xac618c).readPointer(),ids=[];
      for(let i=0;i<31;i++){const actor=table.add(4*i).readPointer();if(!actor.isNull() && actor.add(0x41).readU8()===1)ids.push(actor.add(0x28).readU32());}
      const expectedActor=norm(expectedPath).endsWith('/game-a/ti.exe')?0x40000001:0x40000002;
      if(ids.length!==1 || ![1,expectedActor].includes(ids[0]))throw Error('Observed owned fixture squad required');
      raw=[0x7c,1,...u32(ids[0])];
    }
    else if(action==='heal-result'){
      const expectedActor=norm(expectedPath).endsWith('/game-a/ti.exe')?0x40000001:0x40000002;
      const table=at(0xac618c).readPointer();let owned=false;
      for(let i=0;i<31;i++){const actor=table.add(4*i).readPointer();if(!actor.isNull() && actor.add(0x28).readU32()===expectedActor && actor.add(0x41).readU8()===1)owned=true;}
      if(!owned)throw Error('Observed own result actor required');
      raw=[0x7c,1,...u32(expectedActor)];
    }else{
      raw=[0x21,0];
      for(let i=0;i<command.length;i++)raw.push(command.charCodeAt(i)&255,command.charCodeAt(i)>>>8);
      raw.push(0,0);
    }
    payload=Memory.alloc(raw.length);payload.writeByteArray(raw);
    // Original 6060F0 encrypts and submits via the genuine ORANGE callback.
    code.push(0xb8,...u32(payload.toUInt32()),0xba,...u32(raw.length),0xb9,...u32(at(0x6060f0).toUInt32()),0xff,0xd1);
  }
  code.push(0x61,0x9d,0xc3);
  const thunk=Memory.alloc(4096);thunk.writeByteArray(code);Memory.protect(thunk,4096,'r-x');
  new NativeFunction(thunk,'void',[],'stdcall')();
  return {pid:Process.id,action,method:'original native networking only',server_replies_injected:false};
};
rpc.exports.snapshot=function(){
  const result={pid:Process.id,read_only:true,fields:{},actors:[]};
  function sample(name,read){try{result.fields[name]=read();}catch(e){result.fields[name]='unavailable';}}
  const ex=va=>exe.base.add(va-0x400000);
  result.modules={exe:{base:exe.base.toString(),name:exe.name},silver:{base:silver.base.toString()},gold:{base:Process.getModuleByName('gold.dll').base.toString()}};
  result.tick_counts=tickCounts;
  sample('engine_imports',()=>Object.fromEntries([0x76deb4,0x76e2ac,0x76df14,0x76e1f0,0x76e5f4].map(va=>[va.toString(16),ex(va).readPointer().toString()])));
  sample('battle_mode',()=>at(0xac6008).readPointer().add(0x19).readU8());
  sample('load_state',()=>ex(0x76deb4).readPointer().readU8());
  sample('load_overlay',()=>ex(0x76e2ac).readPointer().readU8());
  sample('graphics',()=>ex(0x76dbb0).readU8());
  sample('background_queue_gate_bytes',()=>bytes(ex(0x6f6aff).readByteArray(2)).map(b=>b.toString(16).padStart(2,'0')).join(''));
  sample('modal',()=>ex(0x76e1f0).readPointer().readU8());
  sample('silver_packet_gate',()=>at(0xac5834).readPointer().readU8());
  sample('render_mode',()=>at(0xac4c6d).readU8());
  sample('world_view_visible',()=>at(0xac4c6c).readU8());
  sample('world_overlay_kind',()=>at(0xac4c6e).readU8());
  sample('battle_active',()=>at(0xac64a0).readPointer().readU8());
  sample('current_town',()=>at(0xac5d58).readPointer().readS32());
  sample('local_owner',()=>at(0xac5a98).readPointer().readU32());
  sample('turn_owner',()=>at(0xac5cd4).readPointer().readU32());
  sample('active_input',()=>at(0xac6264).readPointer().readU8());
  sample('arena_room',()=>at(0xac6184).readPointer().readU32());
  sample('character',()=>{const p=at(0xac5b7c).readPointer();return {state:p.add(0x22c).readU8(),x:p.add(12).readS32(),y:p.add(16).readS32()};});
  sample('grid',()=>{const p=ex(0x76e5f4).readPointer().readPointer();const width=p.add(0x24).readU16(),height=p.add(0x26).readU16();if(width>128||height>128)throw Error('Grid bound');return {width,height};});
  sample('ground',()=>{const p=ex(0x76e330).readPointer();return {width:p.add(4).readU8(),height:p.add(5).readU8(),persistent_fog:p.add(6).readU8()};});
  sample('members',()=>{const p=at(0xac62a4).readPointer(),rows=[];for(let i=0;i<8;i++){const row=p.add(i*0x1c0);if(row.readU8())rows.push({id:row.add(4).readU32(),loaded:row.add(0x111).readU8()});}return rows;});
  sample('callback_gate',()=>{const p=ex(0x76e17c).readPointer().readPointer();return {progress:p.add(8).readS32(),busy:p.add(0x18).readU8(),halt:p.add(0x19).readU8(),delay_until:p.add(0x1c).readU32(),bypass:p.add(0x21).readU8(),clock:ex(0x76e314).readPointer().readU32(),animation_until:ex(0x76dccc).readPointer().readU32()};});
  sample('queue_contexts',()=>({import_slot:ex(0x76e17c).readPointer().toString(),import_context:ex(0x76e17c).readPointer().readPointer().toString(),tick_context:ex(0x78720c).readPointer().toString()}));
  sample('pending_animations',()=>{const table=ex(0x76e430).readPointer(),rows=[];for(let i=0;i<31;i++){const actor=table.add(4*i).readPointer();if(actor.isNull())continue;const slots=[];for(let j=0;j<20;j++)if(actor.add(0x1dc+20*j).readU8())slots.push(j);if(slots.length)rows.push({slot:i,animations:slots});}return rows;});
  sample('callback_queue',()=>{const context=ex(0x76e17c).readPointer().readPointer(),p=context.add(0x10).readPointer(),count=p.add(8).readU32();if(count>2048)throw Error('Queue bound');const rows=[],table=p.add(4).readPointer();for(let i=0;i<Math.min(count,12);i++){const row=table.add(4*i).readPointer();rows.push({done:row.readU8(),processed:row.add(0x18).readU8(),opcode:row.add(0x10).readU16(),callback:row.add(12).readPointer().sub(silver.base).add(0x400000).toString()});}return {count,rows};});
  result.threads=Process.enumerateThreads().map(t=>({id:t.id,state:t.state,pc:t.context.pc.toString(),backtrace:Thread.backtrace(t.context,Backtracer.ACCURATE).slice(0,5).map(p=>DebugSymbol.fromAddress(p).toString())}));
  try{const table=at(0xac618c).readPointer();for(let i=0;i<31;i++){
    const p=table.add(4*i).readPointer();if(p.isNull())continue;
    result.actors.push({id:p.add(0x28).readU32(),owner:p.add(0x2c).readU32(),own:p.add(0x41).readU8(),ap:p.add(0x6004).readU8(),hp:p.add(0x6006).readU16(),max_hp:p.add(0x6008).readU16(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32()});
  }}catch(e){result.actor_error=String(e);}
  return result;
};
rpc.exports.observe=function(){
  for(const [va,label] of [[0x6f6bf0,'mark_busy'],[0x6f6e00,'queue_tick'],[0x6f627c,'callback_tick'],[0x749050,'engine_idle']]){
    tickCounts[label]=0;
    Interceptor.attach(exe.base.add(va-0x400000),{onEnter(){tickCounts[label]++;}});
  }
  for(const [va,label] of [[0x95e1e0,'your_turn'],[0x95e170,'turn_now'],[0x95e050,'member_loaded'],[0x95e270,'turn_finished']]){
    Interceptor.attach(at(va),{onEnter(){send({event:label+'_enter'});},onLeave(){
      send({event:label+'_leave',turn_owner:at(0xac5cd4).readPointer().readU32(),active_input:at(0xac6264).readPointer().readU8()});
    }});
  }
};
'''


def guards(root):
    if not (root/'.tio-owned-contracts-local').is_file():
        raise ValueError('Owned client marker required')
    marker=json.loads((root/'.tio-owned-contracts-local').read_text(encoding='utf-8'))
    if marker != dict(schema=1,creator='tools/prepare_contracts_local.py',root=str(root)):
        raise ValueError('Owned local client marker differs')
    hashes = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in PINS}
    if hashes != PINS:
        raise ValueError('Owned native resources differ')
    # Read only endpoint entries; never expose persisted account/settings values.
    import re
    for name in ('config.cfg', 'autoexec.cfg'):
        text = (root/'base'/name).read_text(encoding='cp1251')
        addresses = re.findall(r'^\s*orange_addr\s+"?([^"\s]+)', text, re.M)
        ports = re.findall(r'^\s*orange_port\s+"?([^"\s]+)', text, re.M)
        if not addresses or set(addresses) != {'127.0.0.1'} or not ports or set(ports) != {'28512'}:
            raise ValueError('Local-only client endpoint required')
    pe = pefile.PE(str(root/'silver.dll'))
    try:
        spans = []
        for va, length in ((0x6060f0,189), (0x889e5c,78), (0x95e1e0,144),
                           (0x95e170,112), (0x95e050,60), (0x95e270,96)):
            rva=va-0x400000
            relocations=[]
            for block in pe.DIRECTORY_ENTRY_BASERELOC:
                for entry in block.entries:
                    offset=entry.rva-rva
                    if 0<=offset<length:
                        if entry.type!=3 or offset+4>length:
                            raise ValueError('Unsupported original span relocation')
                        relocations.append(offset)
            spans.append(dict(va=va,bytes=list(pe.get_data(rva,length)),relocations=relocations))
        return hashes, spans
    finally:
        pe.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('client',choices=('a','b'))
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--action',choices=(*COMMANDS,'travel-city','travel-camp','heal-result','heal-current','exit-result','abort','end-turn'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--quiet',action='store_true')
    parser.add_argument('--observe-seconds',type=int,choices=range(1,51))
    args=parser.parse_args()
    root=(OWNED/('game-'+args.client)).resolve()
    hashes,spans=guards(root)
    # Pin the observed authenticated client and loopback server selection.
    login=json.loads((ROOT/'reports/contracts-local/city-ui/group-map-fix'/('login-'+args.client+'.json')).read_text(encoding='utf-8'))
    state=login['state']
    if login['pid']!=args.pid or not state['connected'] or state['selectedServer']['host']!='127.0.0.1' or state['selectedServer']['port']!=28513:
        raise ValueError('PID differs from authenticated local client evidence')
    from tio.locations import center
    if center(3)!=(-154,-318):
        raise ValueError('Whitelisted city route differs')
    if args.action in ('heal-result','exit-result','abort','end-turn'):
        from tools.inspect_contracts_live_checkpoint import audit
        state=audit();account='contract_'+args.client
        bindings=[b for b in state['bindings'] if b['account']==account]
        expected_finished=args.action in ('heal-result','exit-result')
        if len(bindings)!=1 or not any(b['match_id']==bindings[0]['match_id'] and b['kind']=='contract' and b['finished']==expected_finished for b in state['checkpoints']):
            raise ValueError('Action requires this account bound to the expected local contract state')
    if args.action=='heal-current':
        from tools.inspect_contracts_live_checkpoint import audit
        state=audit();account='contract_'+args.client
        if state['bindings'] or len(state['parties'])!=1 or state['parties'][0]['state']!='city' or not any(m['owner']==account for m in state['party_members']):
            raise ValueError('Fixture treatment requires the party returned to city without a battle')
    session=frida.get_local_device().attach(args.pid)
    try:
        script=session.create_script(SCRIPT);observed=[]
        script.on('message',lambda message,data:observed.append(message))
        script.load()
        result=script.exports_sync.initialize(dict(path=str(root/'ti.exe'),silverPath=str(root/'silver.dll'),orangePath=str(root/'orange.dll'),spans=spans))
        if args.action:
            result['submitted']=script.exports_sync.submit(args.action)
        if args.observe_seconds:
            script.exports_sync.observe()
            time.sleep(args.observe_seconds)
            result['passive_callbacks']=observed
        result['snapshot']=script.exports_sync.snapshot()
        result['at']=datetime.now(timezone.utc).isoformat()
        result['native_files_sha256']=hashes
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(pid=args.pid,action=args.action,output=str(args.output))) if args.quiet else json.dumps(result))
    finally:
        session.detach()


if __name__=='__main__':
    main()
