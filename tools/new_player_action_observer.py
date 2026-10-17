"""Passive native action evidence for the exact published new-player client.

``source(game_root)`` returns a Frida script to load in the already ownership-
checked native session. The script checks its PID's executable/module paths and
relocated native entries before attaching observers. It has no RPC actions,
NativeFunction calls, packet hooks, credential reads, or client memory writes.
An observed callback still needs a matching physical UI action/screenshot;
metadata alone does not prove that a human clicked the interface.

Import and --check perform only local file reads. Do not run legacy onboarding
or reward provisioners to prepare these accounts: creation and play belong to UI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PUBLISHED_SILVER_SHA256 = '2d9e0f83b3ff94ef2c7ac5df2d396cd7b7a55a7ac03168c0ef252e977b75b359'
IMAGE_BASE = 0x400000
# Pinned from the complete published menu-layout SILVER, not an arbitrary local
# DLL. The complete file hash is checked in addition to each static code span.
SPANS = (
    ('character_create', 0x889cdc, 172, '365675c20a1ba995501b436f97e9b8068e136bcd456b6da03945694ebf447c6b'),
    ('character_create_result', 0x88a79c, 224, '0990a0bdb29885f0a22f251e5a2dc04affefb3c09e502155007755e9e33b695a'),
    ('appearance_submit', 0x6d1d04, 128, 'dd72190db53841cf9e39924f5feef788a44b454b48c30d782ba2ce8222c49f99'),
    ('appearance_request', 0x6d0268, 128, 'a54f5847882cc75688a4347f3fafb1d1f80dfc886e50e1aa599faa5f16e0a6b0'),
    ('equipment_double_click', 0xa4dba0, 128, '8f2ee181d66215418d794a9dd14d012f53dac87a3712f4e5ab1d4433fa9569c6'),
    ('equipment_policy', 0xa6516c, 128, '2b4571783ec20d0dad330c0b5ac3b1e6d85f94235dd76fe06ee02a7c47aef755'),
    ('equipment_request', 0x9903a4, 128, '8dc6df5b15c4cab5dc28531264b88721787879eef991f0edce509a040b8115c1'),
    ('shop_purchase', 0x9919c8, 128, '0ae95f2212e3a02e8a6e2ca112dcfb2a093f6fe9bb6dc56597ec72fa487fab90'),
    ('survival_button', 0x875570, 74, '50d1b82ea6e92485f02c3e7f0f59c9bc39e46487cfe961fe30f91293e8749e93'),
    ('survival_alternate', 0x8756a4, 76, '4e801c7ee5b8d9aa39270952aa24313516cd218b62fd6a08add65ad314b25e5a'),
    ('arena_search', 0x875118, 46, '4ea551252a4a33c71dcbc26c986f4ed3d25c226200476eefb0ba0e5b6a6c2854'),
    ('arena_admission', 0x85f954, 72, '5c6988fd2911ed6ef338d938323759bb09e376a4c91685f56b6ba56369ee5032'),
    ('modern_battle_continue', 0x94e0d8, 128, '461097a7a9c04362e61c173aad80acb40fda99409b9669f8b264abd65a301a59'),
    ('modern_battle_admission', 0x952bfc, 128, '48c2cbe3a05db77ed61533807e6a5aec488a5e0fb0184bb9b622e6159606f4dc'),
    ('battle_actor', 0x8c5044, 128, 'de2292ba10c77fa6635287ebbf66fea176875419d04df22f3b3b76d38121c834'),
    ('battle_attack', 0x95dfe8, 128, '86fa07122cd52faf3f3aceab15e44d768b8705ac7d6f470eda8cc9e3a022b90c'),
    ('battle_end_turn', 0x95e08c, 128, '7306290e8cea31ec9a6ad6c1e72528f42e9e7ec74bf761fdb5f233063fec3f42'),
    ('battle_over', 0x95e4d0, 128, '12354d868f24f9986b779d77469c9271ddbb6e0c1dcefc5eb65aeecd2ca6d86e'),
    ('battle_finish', 0x719f60, 128, '702930974ac0c73df71cccd3b10e1860689757c1ad643d3b98534e4dd0a48dff'),
    ('battle_turn', 0x95e1e0, 128, 'b63b122eb7bc42fce076a62fe704ddfa1d500a225ea74b4d7aa6b62dc1178f13'),
    ('owned_pet', 0x8c4380, 128, '6c3f990fed443f86e9cfdea347e0e2612a96f78d096b5bf518f253eaad85b59e'),
    ('inventory_reply', 0x990638, 128, 'f94eaddb9f88d6277c748a62e4e86940a14d490a55fe880e6058b866b359182d'),
    ('asset_count', 0x7d4c28, 128, '80426741923c784269d2fb5d1a579895591481a2a3308f95cd2aa2f1827d979d'),
)


def guards(game_root: Path) -> list[dict]:
    """Validate full published file and return relocation-aware live entries."""
    import pefile
    game_root = Path(game_root).resolve()
    if not (game_root / '.tio-owned-qa').is_file():
        raise ValueError('Dedicated owned QA marker is required')
    raw = (game_root / 'silver.dll').read_bytes()
    if hashlib.sha256(raw).hexdigest() != PUBLISHED_SILVER_SHA256:
        raise ValueError('Action observer requires the exact published SILVER')
    pe = pefile.PE(data=raw)
    try:
        if pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE or pe.FILE_HEADER.Machine != 0x14c:
            raise ValueError('Unexpected native image architecture/base')
        result = []
        relocations = [entry for block in getattr(pe, 'DIRECTORY_ENTRY_BASERELOC', ())
                       for entry in block.entries if entry.type]
        for name, va, length, expected in SPANS:
            data = pe.get_data(va - IMAGE_BASE, length)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Pinned action function differs: ' + name)
            size = 32
            offsets = []
            # Extend a signature if its final bytes bisect a relocation word.
            for entry in relocations:
                offset = entry.rva - (va - IMAGE_BASE)
                if 0 <= offset < size:
                    if entry.type != 3:
                        raise ValueError('Unsupported action entry relocation')
                    size = max(size, offset + 4)
                    offsets.append(offset)
            if size > length:
                raise ValueError('Action entry signature exceeds the pinned span')
            result.append(dict(name=name, va=va, entry=data[:size].hex(), relocations=offsets))
        return result
    finally:
        pe.close()


SCRIPT = r'''
(() => {
  'use strict';
  const config = __CONFIG__;
  const normalized = p => p.replace(/\\/g,'/').toLowerCase();
  if(Process.arch !== 'ia32' || normalized(Process.mainModule.path)!==normalized(config.executable))
    throw new Error('Action observer PID is not the owned x86 game');
  const silver = Process.getModuleByName('silver.dll');
  if(normalized(silver.path)!==normalized(config.silver_path))
    throw new Error('Action observer SILVER path differs');
  const at = va => silver.base.add(va-0x400000);
  // Validate every entry before adding any hooks. Existing auth observers use
  // different entries; a second action observer on the same PID is rejected.
  for(const guard of config.guards) {
    const wanted = guard.entry.match(/../g).map(v=>parseInt(v,16));
    const delta = (silver.base.toUInt32()-0x400000)>>>0;
    for(const offset of guard.relocations) {
      const original = (wanted[offset]|wanted[offset+1]<<8|wanted[offset+2]<<16|wanted[offset+3]<<24)>>>0;
      const value=(original+delta)>>>0;
      for(let n=0;n<4;n++) wanted[offset+n]=(value>>>(n*8))&255;
    }
    const actual = new Uint8Array(at(guard.va).readByteArray(wanted.length));
    if(wanted.some((value,index)=>actual[index]!==value))
      throw new Error('Action observer native entry differs: '+guard.name);
  }
  const stacks = new Map();
  const LIMIT = 20000;
  let events=0, sequence=0;
  function emit(event, fields={}) {
    if(events++>=LIMIT) return;
    send({event:'action_'+event,action_sequence:++sequence,...fields});
    if(events===LIMIT)send({event:'action_observation_bound_reached',limit:LIMIT});
  }
  function safely(label, fn) {
    try {return fn();} catch(_) {emit('read_unavailable',{field:label});return null;}
  }
  function caller(invocation) {
    const p=invocation.returnAddress;
    return p.compare(silver.base)>=0 && p.compare(silver.base.add(silver.size))<0
      ? p.sub(silver.base).toUInt32()+0x400000 : null;
  }
  function provenance(invocation) {
    return {caller_va:caller(invocation),native_gui_callbacks:[...(stacks.get(invocation.threadId)||[])]};
  }
  function hook(name, enter, leave) {
    const guard=config.guards.find(g=>g.name===name);
    Interceptor.attach(at(guard.va),{
      onEnter() {if(enter)safely(name+'_enter',()=>enter.call(this));},
      onLeave() {if(leave)safely(name+'_leave',()=>leave.call(this));},
    });
  }
  function gui(name) {
    hook(name,function(){
      const stack=stacks.get(this.threadId)||[];
      stack.push(name);stacks.set(this.threadId,stack);
      emit('gui_callback',{callback:name,caller_va:caller(this)});
    },function(){
      const stack=stacks.get(this.threadId)||[];stack.pop();
      if(!stack.length)stacks.delete(this.threadId);
    });
  }
  function actors() {
    const table=at(0xac618c).readPointer(), result=[];
    if(table.isNull())return result;
    for(let index=0;index<31;index++) {
      const actor=table.add(index*4).readPointer();if(actor.isNull())continue;
      result.push({id:actor.add(0x28).readU32(),owner:actor.add(0x2c).readU32(),
        own:actor.add(0x41).readU8(),resource:actor.add(4).readU32(),
        level:actor.add(0x5ffc).readU32(),hp:actor.add(0x6006).readU16(),
        max_hp:actor.add(0x6008).readU16(),ap:actor.add(0x6004).readU8(),
        x:actor.add(0x603c).readU32(),y:actor.add(0x6040).readU32()});
    }
    return result;
  }
  gui('survival_button');gui('survival_alternate');gui('arena_search');
  gui('modern_battle_continue');gui('equipment_double_click');gui('appearance_submit');
  gui('battle_finish');
  hook('character_create',function(){
    // Do not read the name/string or its content; sex is a native stack byte.
    emit('character_create_request',{sex:this.context.esp.add(16).readU8(),...provenance(this)});
  });
  hook('character_create_result',function(){this.createStatus=this.context.eax.readU8();},function(){
    emit('character_create_result',{status:this.createStatus});
  });
  hook('appearance_request',function(){
    const words=[];for(let i=0;i<6;i++)words.push(this.context.edx.add(i*2).readU16());
    emit('appearance_request',{owner:this.context.eax.toUInt32(),
      head:words[3],hair:words[0],beard:words[1],color:words[2],body:words[4],legs:words[5],...provenance(this)});
  });
  hook('equipment_policy',function(){
    emit('equipment_policy',{owner:this.context.eax.toUInt32(),instance_id:this.context.edx.add(0x28).readU32(),
      equipped_before:this.context.edx.add(0x30).readU8(),target:this.context.ecx.toUInt32(),...provenance(this)});
  });
  hook('equipment_request',function(){
    emit('equipment_request',{owner:this.context.eax.toUInt32(),instance_id:this.context.edx.toUInt32(),
      option:this.context.esp.add(4).readU8(),...provenance(this)});
  });
  hook('shop_purchase',function(){
    emit('shop_purchase_request',{owner:this.context.eax.toUInt32(),offer_id:this.context.edx.toUInt32(),
      quantity:this.context.ecx.toUInt32(),category:this.context.esp.add(4).readU8(),...provenance(this)});
  });
  hook('arena_admission',function(){
    emit('arena_admission_request',{protocol:'BA03',mode:this.context.eax.toUInt32()&255,
      count:this.context.edx.toUInt32()&255,...provenance(this)});
  });
  hook('modern_battle_admission',function(){
    emit('modern_battle_admission_request',{protocol:'C6/21',...provenance(this)});
  });
  hook('battle_attack',function(){
    emit('battle_attack_request',{actor_id:this.context.eax.toUInt32(),
      x:this.context.edx.toUInt32(),y:this.context.ecx.toUInt32(),...provenance(this)});
  });
  hook('battle_end_turn',function(){emit('battle_end_turn_request',provenance(this));});
  for(const name of ['battle_actor','owned_pet','inventory_reply','battle_turn'])
    hook(name,null,function(){emit(name+'_applied',{actors:actors()});});
  hook('asset_count',null,function(){
    const character=at(0xac5b7c).readPointer();
    emit('assets_applied',{credits:character.add(0x230).readU32(),gold:character.add(0x234).readU32()});
  });
  hook('battle_over',null,function(){
    const result=at(0xac6200).readPointer();
    emit('battle_results_applied',{result:result.add(8).readU8(),kills:result.add(10).readU16(),
      losses:result.add(12).readU16(),damage_dealt:result.add(16).readU32(),
      damage_received:result.add(20).readU32(),credits:result.add(24).readU32(),
      rental_tax:result.add(28).readU32(),actors:actors()});
  });
  emit('observer_ready',{read_only:true,packet_payloads_logged:false,credentials_read:false,
    native_callbacks_invoked:false,hook_count:config.guards.length,
    silver_sha256:config.silver_sha256,pid:Process.id});
})();
'''


def source(game_root: Path) -> str:
    """Return bounded passive JS; caller already proved launcher/PID ownership."""
    game_root = Path(game_root).resolve()
    config = dict(executable=str(game_root / 'ti.exe'), silver_path=str(game_root / 'silver.dll'),
                  silver_sha256=PUBLISHED_SILVER_SHA256, guards=guards(game_root))
    return SCRIPT.replace('__CONFIG__', json.dumps(config, separators=(',', ':')))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game_root', type=Path)
    parser.add_argument('--check', action='store_true', required=True,
                        help='Verify local full hash/spans only; no process or network operations')
    args = parser.parse_args(argv)
    entries = guards(args.game_root)
    print(json.dumps(dict(local_only=True, native_hooks=len(entries),
                          silver_sha256=PUBLISHED_SILVER_SHA256,
                          source_generated=bool(source(args.game_root)))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
