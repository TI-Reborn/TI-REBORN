"""Launch owned TIO process, block network connects, dump its loaded ORANGE image."""
import json
import time
import subprocess
import sys
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path
import frida

ROOT = Path(__file__).resolve().parents[1]
CLIENT = Path(r'C:\Program Files (x86)\TIOnline')
OUT = ROOT / 'evidence'


def main():
    global OUT
    expected={'silver.dll':'a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11','ti.exe':'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c','orange.dll':'5fcf649fe389c32c5caed89719a8fc32049b0bca21b6c20cec8ea50afb28b589'}
    for name,digest in expected.items():
        if hashlib.sha256((CLIENT/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Unsupported client build: '+name)
    if '--select-probe' in sys.argv and '--create-success-probe' not in sys.argv:
        raise ValueError('--select-probe requires --create-success-probe')
    if '--create-success-probe' in sys.argv:
        if '--shared-config' not in sys.argv:raise ValueError('--create-success-probe requires --shared-config')
        if '--create-probe' not in sys.argv:sys.argv.append('--create-probe')
    if '--create-probe' in sys.argv and '--empty-characters' not in sys.argv:
        raise ValueError('--create-probe requires --empty-characters')
    if '--shared-config' in sys.argv and '--auth2-result' not in sys.argv:
        raise ValueError('--shared-config requires --auth2-result')
    if '--character-record' in sys.argv and '--auth2-result' not in sys.argv:
        raise ValueError('--character-record requires --auth2-result')
    if '--empty-characters' in sys.argv and '--auth2-result' not in sys.argv:
        raise ValueError('--empty-characters requires --auth2-result')
    if '--auth2-result' in sys.argv and '--mode1-complete' not in sys.argv:
        raise ValueError('--auth2-result requires --mode1-complete')
    if '--mode1-complete' in sys.argv and '--mode1-challenge' not in sys.argv:
        raise ValueError('--mode1-complete requires --mode1-challenge')
    if '--mode1-challenge' in sys.argv and '--server-login' not in sys.argv:
        raise ValueError('--mode1-challenge requires --server-login')
    if '--server-login' in sys.argv and '--server-list-entry' not in sys.argv:
        raise ValueError('--server-login requires --server-list-entry')
    if '--server-list-entry' in sys.argv and '--server-list' not in sys.argv:
        raise ValueError('--server-list-entry requires --server-list')
    if '--server-list' in sys.argv and '--login-result' not in sys.argv:
        raise ValueError('--server-list requires --login-result')
    if '--login-result' in sys.argv and '--completion' not in sys.argv:
        raise ValueError('--login-result requires --completion')
    if '--completion' in sys.argv and '--loopback' not in sys.argv:
        raise ValueError('--completion requires --loopback')
    if '--loopback' in sys.argv and '--fix-user32' not in sys.argv:
        raise ValueError('--loopback requires --fix-user32')
    if '--resolver' in sys.argv or '--fix-user32' in sys.argv:
        OUT = ROOT / 'evidence' / (('loader-user32-fix-' if '--fix-user32' in sys.argv else 'loader-resolver-')+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    OUT.mkdir(parents=True, exist_ok=True)
    exchange=None
    if '--loopback' in sys.argv:
        from loopback_exchange import LoopbackExchange
        exchange=LoopbackExchange(OUT/'loopback.json',completion='--completion' in sys.argv,login_result='--login-result' in sys.argv,server_list='--server-list' in sys.argv,server_entry='--server-list-entry' in sys.argv,server_login='--server-login' in sys.argv,mode1_challenge='--mode1-challenge' in sys.argv,mode1_complete='--mode1-complete' in sys.argv,auth2_result='--auth2-result' in sys.argv,empty_characters='--empty-characters' in sys.argv,character_record='--character-record' in sys.argv,shared_config='--shared-config' in sys.argv,create_probe='--create-probe' in sys.argv,create_success_probe='--create-success-probe' in sys.argv,select_probe='--select-probe' in sys.argv,mychar_probe='--mychar-probe' in sys.argv,inspect_window='--inspect-window' in sys.argv,town_probe='--town-probe' in sys.argv,enter_town_probe='--enter-town-probe' in sys.argv,open_town_probe='--open-town-probe' in sys.argv,observation_seconds=next((int(a.split('=',1)[1]) for a in sys.argv if a.startswith('--observation-seconds=')),None),database=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--database=')),None),owned_pet_probe='--owned-pet-probe' in sys.argv,battle_settings_probe='--battle-settings-probe' in sys.argv)
    if exchange is not None: exchange.turn_timeout_probe='--turn-timeout-probe' in sys.argv
    if exchange is not None: exchange.battle_scene_probe='--battle-scene-probe' in sys.argv
    if exchange is not None: exchange.battle_actor_probe='--battle-actor-probe' in sys.argv
    if exchange is not None: exchange.battle_move_probe='--battle-move-probe' in sys.argv
    if exchange is not None: exchange.two_turns_probe='--two-turns-probe' in sys.argv
    if exchange is not None: exchange.battle_remove_probe='--battle-remove-probe' in sys.argv
    if exchange is not None: exchange.battle_members_probe='--battle-members-probe' in sys.argv
    if '--town-probe' in sys.argv and '--mychar-probe' not in sys.argv:
        raise ValueError('--town-probe requires --mychar-probe')
    if '--enter-town-probe' in sys.argv and '--town-probe' not in sys.argv:
        raise ValueError('--enter-town-probe requires --town-probe')
    if '--town-view-probe' in sys.argv and '--enter-town-probe' not in sys.argv:
        raise ValueError('--town-view-probe requires --enter-town-probe')
    if '--open-town-probe' in sys.argv and '--enter-town-probe' not in sys.argv:
        raise ValueError('--open-town-probe requires --enter-town-probe')
    device = frida.get_local_device()
    late = '--late-attach' in sys.argv
    if late:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        proc = subprocess.Popen([str(CLIENT/'ti.exe')], cwd=CLIENT, startupinfo=startup)
        pid = proc.pid
        time.sleep(12)
    elif '--visible-launch' in sys.argv:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 1
        proc = subprocess.Popen([str(CLIENT/'ti.exe')],cwd=CLIENT,creationflags=0x00000004,startupinfo=startup)
        pid=proc.pid
    else:
        pid = device.spawn([str(CLIENT / 'ti.exe')], cwd=str(CLIENT))
    session = None
    try:
        session = device.attach(pid)
        script = session.create_script('''
        const blocked = new Set();
        let orangeBase = null;
        let resolverAttached = false;
        Process.setExceptionHandler(function(d){
          send({event:'exception',type:d.type,address:d.address.toString(),memory:d.memory,context:d.context});
          if (!orangeBase && d.context.edx && d.context.edx.add(0x4055).equals(d.address)) orangeBase=d.context.edx;
          if (orangeBase) {
            try {send({event:'partial_image',base:orangeBase.toString()},orangeBase.readByteArray(0x10000));}catch(_){}
            if (RESOLVER_PROBE && !resolverAttached && d.address.equals(orangeBase.add(0xf8be))) {
              resolverAttached=true;
              if (FIX_USER32) {
                const slot=orangeBase.add(0x4977+0x9c);
                const prior=slot.readPointer();
                const correct=Process.getModuleByName('user32.dll').base;
                const apphelp=Process.findModuleByName('apphelp.dll');
                if (prior.equals(correct)) {
                  send({event:'user32_slot_already_correct',slot:slot.toString(),value:prior.toString()});
                } else if (apphelp && prior.equals(apphelp.base)) {
                  if (orangeBase.add(0xbc80).readU32()!==0x81ec8b55) throw new Error('Unexpected resolver bytes');
                  send({event:'user32_slot_fix',slot:slot.toString(),before:prior.toString(),after:correct.toString()});
                  slot.writePointer(correct);
                } else {
                  send({event:'user32_slot_patch_skipped',reason:'unrecognized original slot; no write',value:prior.toString()});
                }
              }
              const lookup=orangeBase.add(0xbc80);
              send({event:'attach_resolver',address:lookup.toString()});
              Interceptor.attach(lookup,{
                onEnter(args){this.args=Array.from({length:5},(_,i)=>args[i].toString());send({event:'resolve_enter',args:this.args,returnAddress:this.returnAddress.toString()});},
                onLeave(ret){send({event:'resolve_leave',args:this.args,result:ret.toString(),symbol:DebugSymbol.fromAddress(ret).toString()});}
              });
            }
          }
          return false;
        });

        if (TRACE_WINDOWS) Process.attachModuleObserver({onAdded(m){
          if(m.name.toLowerCase()!=='user32.dll')return;
          for(const name of ['CreateWindowExW','CreateWindowExA','ShowWindow','DestroyWindow']){
            Interceptor.attach(m.getExportByName(name),{onEnter(a){
              this.fields={event:'window_api',name,args:Array.from({length:name.startsWith('Create')?12:2},(_,i)=>a[i].toString()),caller:this.returnAddress.toString()};
              if(name.startsWith('Create')){try{this.fields.title=name.endsWith('W')?a[2].readUtf16String():a[2].readCString();}catch(e){}}
            },onLeave(r){this.fields.result=r.toString();send(this.fields);}});
          }
        }});

        if(TRACE_WINDOWS){
          for(const va of [0x5ba238,0x746470,0x72872d])Interceptor.attach(ptr(va),{onEnter(){send({event:'startup_checkpoint',va:'0x'+va.toString(16),eax:this.context.eax.toString(),app_show_main:ptr('0x76e2b4').readPointer().readPointer().add(0x6f).readU8(),trace:Thread.backtrace(this.context,Backtracer.ACCURATE).map(p=>p.toString())});}});
        }
        const k32 = Process.getModuleByName('kernel32.dll');
        Process.attachModuleObserver({onAdded(m) {
          if(m.name.toLowerCase()!=='silver.dll') return;
          const at=va=>m.base.add(va-0x400000);
          // Russian resources contain CP1251 short strings. Delphi otherwise
          // inherits host ACP1252 and destroys Cyrillic effect descriptions.
          Interceptor.attach(at(0x9d61c0),{onEnter(){
            const cp=at(0xac7900),before=cp.readU32();cp.writeU32(1251);
            send({event:'russian_skill_codepage',before,after:cp.readU32()});
          }});
          function catalogState(){
            const owner=at(0xac637c).readPointer();
            const table=owner.isNull()?ptr(0):owner.readPointer(),bound=at(0xac4e70).readS32();
            const records=[];
            if(!table.isNull() && bound>0 && bound<=10000){
              for(let i=0;i<Math.min(bound,32);i++){
                const row=table.add(i*0x3a78);
                records.push({index:i,id:row.add(0x116).readU16(),type:row.add(0x118).readU16(),weaponType:row.add(0x120).readU16(),equipable:row.add(0x68d).readU8()});
              }
            }
            return {owner:owner.toString(),table:table.toString(),bound,records};
          }
          Interceptor.attach(at(0xa7005c),{onEnter(){send({event:'item_xml_loader_enter',catalog:catalogState()});},onLeave(){send({event:'item_xml_loader_leave',catalog:catalogState()});}});
          Interceptor.attach(at(0x9d1f68),{onEnter(){send({event:'resource_reload_dispatch',name:this.context.eax.isNull()?null:this.context.eax.readUtf16String()});}});
          Interceptor.attach(at(0xa7012d),{onEnter(){send({event:'item_xml_path',path:this.context.eax.readUtf16String()});}});
          Interceptor.attach(at(0x889eac),{onEnter(){send({event:'catalog_before_characters',catalog:catalogState()});}});
        }});
        Interceptor.attach(k32.getExportByName('LoadLibraryW'),{onEnter(a){this.path=a[0].readUtf16String();},onLeave(r){if(this.path.toLowerCase().includes('orange'))send({event:'LoadLibraryW',path:this.path,result:r.toString(),lastError:this.lastError});}});
        const gle = new NativeFunction(k32.getExportByName('GetLastError'),'uint32',[]);
        const cwdBuffer = Memory.alloc(4096);
        const cwd = new NativeFunction(k32.getExportByName('GetCurrentDirectoryW'),'uint32',['uint32','pointer']);
        Interceptor.attach(ptr('0x718ff4'),{onEnter(){cwd(2048,cwdBuffer);send({event:'orange_load_result',eax:this.context.eax.toString(),lastError:gle(),cwd:cwdBuffer.readUtf16String()});}});
        Interceptor.attach(ptr('0x718fb8'),{onEnter(){send({event:'orange_init_enter'});},onLeave(){send({event:'orange_init_leave',handle:ptr('0x76da80').readPointer().toString()});}});
        Process.attachModuleObserver({onAdded(m) {
          if (!/^(ws2_32|wsock32)\\.dll$/i.test(m.name)) return;
          const p = m.findExportByName('connect');
          if (p && !blocked.has(p.toString())) {
            blocked.add(p.toString());
            const originalConnect=new NativeFunction(p,'int',['int','pointer','int']);
            Interceptor.replace(p, new NativeCallback(function(s,a,n) {
              if (LOOPBACK_PORT && n>=16 && a.readU16()===2 && a.add(4).readU32()===0x0100007f && ((a.add(2).readU8()<<8)|a.add(3).readU8())===LOOPBACK_PORT) {
                send({event:'allowed_loopback_connect',socket:s});
                return originalConnect(s,a,n);
              }
              send({event:'blocked_connect', socket:s}); return -1;
            }, 'int', ['int','pointer','int']));
          }
        }});
        rpc.exports.connectloopback = function() {
          const m=Process.getModuleByName('orange.dll');
          const entry=m.getExportByName('AAaAA');
          const target=entry.add(5).add(entry.add(1).readS32());
          const unpacked=target.sub(0x16a0);
          Interceptor.attach(unpacked.add(0x1f70),{onEnter(a){send({event:'transport_queue',length:a[1].toUInt32()&65535,plain_hex:hex(a[0],a[1].toUInt32()&65535)});}});
          Interceptor.attach(unpacked.add(0x2250),{onEnter(a){this.connection=a[0];send({event:'transport_dispatch',state:a[0].add(0x1e).readU16(),command:a[1].readU8()});},onLeave(){send({event:'transport_dispatch_return',state:this.connection.add(0x1e).readU16()});}});
          const silver=Process.getModuleByName('silver.dll').base;
          if(BATTLE_HEAL_PROBE){
            Interceptor.attach(silver.add(0x95e1e0-0x400000),{onLeave(){
              for(const delay of [100,350])setTimeout(()=>{
                const actor=silver.add(0xac618c-0x400000).readPointer().readPointer();
                const id=actor.add(0x28).readU32(),x=actor.add(0x603c).readU32(),y=actor.add(0x6040).readU32();
                const code=Memory.alloc(Process.pageSize),bytes=[0x53,0x68];
                const u32=v=>{for(let n=0;n<4;n++)bytes.push((v>>>(n*8))&255);};
                u32(x);bytes.push(0x68);u32(y);bytes.push(0xb8);u32(23);bytes.push(0xba);u32(id);
                bytes.push(0x31,0xc9,0xbb);u32(silver.add(0x8c0730-0x400000).toUInt32());bytes.push(0xff,0xd3,0x5b,0xc3);
                code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');new NativeFunction(code,'void',[])();
                send({event:'healing_builder_return',id,x,y});
              },delay);
            }});
            const snapshot=label=>{const actor=silver.add(0xac618c-0x400000).readPointer().readPointer();
              const skills=actor.add(0x304).readPointer(),entries=[];
              if(!skills.isNull())for(let i=0;i<skills.sub(4).readU32();i++){const e=skills.add(i*0x348);entries.push({id:e.add(8).readU32(),state:e.add(0x338).readU8(),remaining:e.add(0x328).readU32()});}
              send({event:label,id:actor.add(0x28).readU32(),hp:actor.add(0x6006).readU16(),ap:actor.add(0x6004).readU8(),entries});};
            Interceptor.attach(silver.add(0x8c0790-0x400000),{onLeave(){snapshot('healing_status_return');}});
            Interceptor.attach(silver.add(0x8c82b0-0x400000),{onLeave(){snapshot('healing_health_ap_return');}});
          }

          Interceptor.attach(silver.add(0x95e1e0-0x400000),{onEnter(){send({event:'your_turn_enter'});},onLeave(){send({event:'your_turn_return',owner:silver.add(0xac5cd4-0x400000).readPointer().readU32(),enabled:silver.add(0xac6264-0x400000).readPointer().readU8()});if(BATTLE_MOVE_PROBE){const current=silver.add(0xac618c-0x400000).readPointer().readPointer();const x=current.add(0x603c).readU32(),y=current.add(0x6040).readU32(),dx=x===2?1:-1,dy=y===2?1:-1;for(const [delay,coords] of [[100,[[x+dx,y],[x+2*dx,y]]],[300,[[7,7]]],[500,[[x+2*dx,y+dy]]]])setTimeout(()=>{
              const exe=Process.getModuleByName('ti.exe').base;
              const actor=silver.add(0xac618c-0x400000).readPointer().readPointer().add(0x28).readU32();
              const path=Memory.alloc(coords.length*8);coords.forEach(([x,y],n)=>{path.add(n*8).writeU32(x);path.add(n*8+4).writeU32(y);});
              const code=Memory.alloc(Process.pageSize);const bytes=[0x53,0xb8];
              const u32=v=>{for(let n=0;n<4;n++)bytes.push((v>>>(n*8))&255);};
              u32(actor);bytes.push(0xba);u32(path.toUInt32());bytes.push(0xb9);u32(coords.length-1);
              bytes.push(0xbb);u32(exe.add(0x6dc460-0x400000).toUInt32());bytes.push(0xff,0xd3,0x5b,0xc3);
              code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');new NativeFunction(code,'void',[])();
              send({event:'move_request_builder_return',actor_id:actor,path:coords});
            },delay);} if(ARENA_START_PROBE && !TURN_TIMEOUT_PROBE){setTimeout(()=>{new NativeFunction(silver.add(0x95e08c-0x400000),'void',[])();send({event:'end_turn_builder_return'});},700);}}});
          Interceptor.attach(silver.add(0x95e270-0x400000),{onLeave(){send({event:'your_turn_finished_return',enabled:silver.add(0xac6264-0x400000).readPointer().readU8()});}});
          Interceptor.attach(silver.add(0x95c748-0x400000),{onLeave(){send({event:'known_mines_receiver_return'});}});
          Interceptor.attach(silver.add(0x658b7c-0x400000),{onEnter(){this.record=this.context.eax;},onLeave(){send({event:'known_mines_parsed',count:this.record.add(4).readU32()});}});
          Interceptor.attach(silver.add(0x8c5044-0x400000),{onEnter(){send({event:'battle_actor_enter'});},onLeave(){const table=silver.add(0xac618c-0x400000).readPointer();const actors=[];for(let n=0;n<31;n++){const p=table.add(n*4).readPointer();if(!p.isNull())actors.push({id:p.add(0x28).readU32(),owner:p.add(0x2c).readU32(),level:p.add(0x5ffc).readU32(),hp:p.add(0x6006).readU16(),max_hp:p.add(0x6008).readU16(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32()});}send({event:'battle_actor_return',actors});}});
          Interceptor.attach(silver.add(0x8c82b0-0x400000),{onLeave(){const actor=silver.add(0xac618c-0x400000).readPointer().readPointer();if(!actor.isNull())send({event:'action_points_update_return',points:actor.add(0x6004).readU8()});}});
          Interceptor.attach(silver.add(0x8c71e0-0x400000),{onEnter(){this.id=this.context.eax.readU32();},onLeave(){const table=silver.add(0xac618c-0x400000).readPointer();const actors=[];for(let n=0;n<31;n++){const p=table.add(n*4).readPointer();if(!p.isNull())actors.push({id:p.add(0x28).readU32(),removed:p.add(0x20).readU8(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32()});}send({event:'battle_remove_return',actor_id:this.id,actors});}});
          let warehouseTransfers=0;
          Interceptor.attach(silver.add(0x992598-0x400000),{onLeave(){send({event:'warehouse_list_applied'});if(WAREHOUSE_TRANSFER_PROBE && warehouseTransfers<2){const withdraw=warehouseTransfers++===0;setTimeout(()=>{
            const memory=Memory.alloc(664);memory.writeS32(-1);memory.add(4).writeU32(1);const array=memory.add(8);array.add(0x28).writeU32(WAREHOUSE_PARTIAL_PROBE && !withdraw?1002:1001);array.add(0x1c).writeU32(WAREHOUSE_PARTIAL_PROBE?(withdraw?3:2):1);
            const code=Memory.alloc(Process.pageSize),bytes=[0x53,0x68];const u32=v=>bytes.push(v&255,(v>>>8)&255,(v>>>16)&255,(v>>>24)&255);
            u32(withdraw?array.toUInt32():0);bytes.push(0x31,0xc0,0xba);u32(1);bytes.push(0xb9);u32(withdraw?0:array.toUInt32());bytes.push(0xbb);u32(silver.add(0x992294-0x400000).toUInt32());bytes.push(0xff,0xd3,0x5b,0xc3);
            code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');new NativeFunction(code,'void',[])();send({event:'warehouse_transfer_builder_return',withdraw});
          },200);}}});
          Interceptor.attach(silver.add(0x917528-0x400000),{onEnter(){send({event:'warehouse_mark_received',kind:this.context.edx.toUInt32()&255});}});
          const sceneExe=Process.getModuleByName('ti.exe').base;
          BATTLE_DOOR_GRID_HOOK
          installBattleDoorGrid(sceneExe);
          Interceptor.attach(sceneExe.add(0x6dc600-0x400000),{
            onEnter(){this.actorId=this.context.eax.readU32();},
            onLeave(){
              const models=silver.add(0xac618c-0x400000).readPointer();
              const scenes=sceneExe.add(0x76e430-0x400000).readPointer();
              let model=null,scene=null;
              for(let i=0;i<31;i++){
                const m=models.add(i*4).readPointer(),s=scenes.add(i*4).readPointer();
                if(!m.isNull() && m.add(0x28).readU32()===this.actorId)model=m;
                if(!s.isNull() && s.add(0x16c).readU32()===this.actorId)scene=s;
              }
              if(model && scene)send({event:'battle_move_return',actor_id:this.actorId,
                model_x:model.add(0x603c).readU32(),model_y:model.add(0x6040).readU32(),
                scene_x:scene.add(0x1cc).readU32(),scene_y:scene.add(0x1d0).readU32(),
                rendered_x:scene.add(0x1bc).readU32(),rendered_y:scene.add(0x1c0).readU32(),
                action_points:model.add(0x6004).readU8()});
            }
          });
          for(const [va,label] of [[0x717e1c,'scene_ground'],[0x718138,'scene_load_end'],[0x7175ac,'scene_resources'],[0x726844,'scene_finalize']]){
            Interceptor.attach(sceneExe.add(va-0x400000),{onEnter(){send({event:label+'_enter'});},onLeave(){send({event:label+'_return',state:sceneExe.add(0x76deb4-0x400000).readPointer().readU8()});}});
          }

          Interceptor.attach(silver.add(0xa0a834-0x400000),{onEnter(){send({event:'battle_settings_enter'});},onLeave(){const settings=silver.add(0xac6008-0x400000).readPointer();send({event:'battle_settings_return',mode:settings.add(0x19).readU8(),unknown40:settings.add(0x40).readU32(),owner:silver.add(0xac63b4-0x400000).readPointer().readU8()});}});
          Interceptor.attach(silver.add(0x7d4a88-0x400000),{onLeave(){const table=silver.add(0xac62a4-0x400000).readPointer();let occupied=0;for(let i=0;i<8;i++)if(table.add(i*0x1c0).readU8())occupied++;send({event:'room_leave_return',occupied,owner:silver.add(0xac63b4-0x400000).readPointer().readU8()});}});
          let readyProbeSteps=0;let leaveProbeSent=false;
          Interceptor.attach(silver.add(0xa0a29c-0x400000),{onEnter(){send({event:'battle_members_enter'});},onLeave(){const table=silver.add(0xac62a4-0x400000).readPointer();const members=[];for(let i=0;i<8;i++){const p=table.add(i*0x1c0);if(p.readU8())members.push({slot:i,id:p.add(4).readU32(),own:p.add(0x111).readU8(),ready:p.add(0x110).readU8(),soldiers:Array.from({length:3},(_,j)=>{const u=p.add(0x120+j*0x28);return {level:u.readU8(),equip:u.add(1).readU8(),npc_id:u.add(4).readU32(),avatar_id:u.add(8).readU32()};}).filter(u=>u.npc_id!==0xffffffff)});}send({event:'battle_members_return',members});if(ARENA_READY_PROBE && readyProbeSteps<2 && members.some(m=>m.own)){readyProbeSteps++;new NativeFunction(silver.add(0x81dae8-0x400000),'void',[])();send({event:'arena_ready_probe_sent',step:readyProbeSteps});}else if(ARENA_LEAVE_PROBE && !leaveProbeSent && readyProbeSteps===2 && members.some(m=>m.own && m.ready===0)){leaveProbeSent=true;new NativeFunction(silver.add(0x81db8c-0x400000),'void',[])();send({event:'arena_leave_probe_sent'});}}});
          Interceptor.attach(silver.add(0x66754c-0x400000),{onEnter(){this.fromMembers=this.returnAddress.equals(silver.add(0xa0a3ed-0x400000));},onLeave(result){if(this.fromMembers)send({event:'battle_transition_gate',value:result.toUInt32()&255});}});
          Interceptor.attach(silver.add(0x7d0be8-0x400000),{onEnter(){send({event:'battle_transition_enter',context_count:silver.add(0xac5d58-0x400000).readPointer().readU32()});}});
          let startProbeSent=false;
          Interceptor.attach(silver.add(0x81d37c-0x400000),{onEnter(){send({event:'battle_room_open_enter',enabled:this.context.eax.toUInt32()&255});},onLeave(){send({event:'battle_room_open_return'});
              if(ARENA_START_PROBE && !startProbeSent){
                startProbeSent=true;
                const code=Memory.alloc(Process.pageSize),bytes=[0x53,0xb8,0xff,0,0,0,0xbb];
                const target=silver.add(0xa08ab0-0x400000).toUInt32();
                for(let i=0;i<4;i++)bytes.push((target>>>(8*i))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'arena_start_builder_return'});
              }}});
          Interceptor.attach(silver.add(0x87ce60-0x400000),{onEnter(){send({event:'silver_LSAuthResult',bytes:hex(this.context.eax,5)});}});
          function delphiString(value){const mem=Memory.alloc(12+(value.length+1)*2);mem.writeU16(1200);mem.add(2).writeU16(2);mem.add(4).writeS32(-1);mem.add(8).writeU32(value.length);mem.add(12).writeUtf16String(value);return mem;}
          const syntheticUser=delphiString('probe_user');const syntheticPass=delphiString('probe_password');
          Interceptor.attach(silver.add(0x87c604-0x400000),{onEnter(){
            if(SYNTHETIC_LOGIN){this.context.eax=syntheticUser.add(12);this.context.edx=syntheticPass.add(12);}
            send({event:'silver_login_builder_called',synthetic:SYNTHETIC_LOGIN});
          }});
          Interceptor.attach(silver.add(0x87d00c-0x400000),{onEnter(){send({event:'silver_LSLoginResult',status:this.context.eax.readU8()});}});
          Interceptor.attach(silver.add(0x87c76c-0x400000),{onEnter(){send({event:'silver_server_list_request_builder'});}});
          Interceptor.attach(unpacked.add(0x1a90),{onEnter(a){this.obj=this.context.ecx;this.mode=a[3].toUInt32()&255;},onLeave(){send({event:'transport_connect_initialized',mode:this.mode,state:this.obj.add(0x22).readU16(),cipher_enabled:this.obj.add(9).readU8()});}});
          Interceptor.attach(unpacked.add(0x1cd0),{onEnter(){send({event:'transport_send_counter',value:this.context.ecx.add(0x1ab).readU32()});}});
          Interceptor.attach(unpacked.add(0x1da0),{onEnter(){send({event:'transport_recv_counter',value:this.context.ecx.add(0x1ab).readU32()});}});
          Interceptor.attach(silver.add(0x87c7b4-0x400000),{onEnter(){send({event:'silver_server_login_builder',server_id:this.context.eax.toUInt32()&255,address:this.context.edx.readUtf16String(),port:this.context.ecx.toUInt32()&65535,opaque_hex:hex(silver.add(0xac5958-0x400000).readPointer(),8)});}});
          Interceptor.attach(silver.add(0x87d400-0x400000),{onEnter(){send({event:'silver_LSServerLoginResult',status:this.context.eax.readU8()});}});
          Interceptor.attach(silver.add(0x606080-0x400000),{onEnter(){send({event:'silver_connect_request',host:this.context.eax.readUtf16String(),port:this.context.edx.toUInt32(),mode:this.context.esp.add(4).readU32()});}});
          Interceptor.attach(silver.add(0x87d608-0x400000),{onEnter(){send({event:'silver_AuthReply1',status:this.context.eax.readU8()});}});
          SHOP_REQUEST_RETRY_HOOK
          UPGRADE_KIT_INVENTORY_HOOK
          UPGRADE_KIT_WAREHOUSE_HOOK
          TREATMENT_TARIFF_HOOK
          // Original enhancement dialog reads server-supplied settings+5..7.
          // Same compatibility mechanism as treatment until settings packet is recovered.
          const enhancementPolicy=ENHANCEMENT_POLICY;
          function installEnhancementPolicy(){
            const settings=silver.add(0xac5ac0-0x400000).readPointer();
            settings.add(5).writeU8(enhancementPolicy.safe_levels);
            settings.add(6).writeU8(enhancementPolicy.armor_success_percent);
            settings.add(7).writeU8(enhancementPolicy.weapon_success_percent);
          }
          Interceptor.attach(silver.add(0x7c3904-0x400000),{onEnter:installEnhancementPolicy});
          Interceptor.attach(silver.add(0xa7a2c8-0x400000),{onEnter:installEnhancementPolicy});
          Interceptor.attach(silver.add(0xa7ade4-0x400000),{onEnter:installEnhancementPolicy});
          let parsingAuth2=false;
          Interceptor.attach(silver.add(0x87d8a4-0x400000),{onEnter(){parsingAuth2=true;send({event:'silver_AuthReply2',status:this.context.eax.readU8()});},onLeave(){send({event:'silver_AuthReply2_return'});parsingAuth2=false;}});
          Interceptor.attach(silver.add(0x6061b0-0x400000),{onEnter(){if(parsingAuth2)send({event:'silver_AuthReply2_log',text:this.context.eax.readUtf16String()});}});
          let createSent=false;
          const invalidCreateName=delphiString(CREATE_SUCCESS_PROBE?'ProbeNew':'1');
          // Delphi register ABI: EAX=name, EDX=u16; four stack arguments.
          const createCode=Memory.alloc(Process.pageSize);
          const bytes=[0x6a,0,0x6a,0,0x6a,0,0x6a,0,0xb8];
          function u32code(v){for(let i=0;i<4;i++)bytes.push((v>>>(i*8))&255);}
          u32code(invalidCreateName.add(12).toUInt32());bytes.push(0x31,0xd2,0xb9);
          u32code(silver.add(0x889cdc-0x400000).toUInt32());bytes.push(0xff,0xd1,0xc3);
          createCode.writeByteArray(bytes);Memory.protect(createCode,Process.pageSize,'r-x');
          const createNative=new NativeFunction(createCode,'void',[]);
          Interceptor.attach(silver.add(0x88a79c-0x400000),{onEnter(){send({event:'character_create_result',status:this.context.eax.readU8()});},onLeave(){send({event:'character_create_result_return'});}});
          Interceptor.attach(silver.add(0x88ac80-0x400000),{onEnter(){send({event:'mychar_info_enter'});},onLeave(){const towns=silver.add(0xac63bc-0x400000).readPointer().readPointer();try { const callback=silver.add(0xac60e0-0x400000).readPointer().readPointer(); const module=Process.findModuleByAddress(callback); send({event:'packet_callback_target',address:callback.toString(),module:module?module.name:null,rva:module?callback.sub(module.base).toString():null,code_hex:hex(callback,256)}); } catch(error) { send({event:'packet_callback_target_error',error:String(error)}); } send({event:'mychar_info_return',towns:towns.toString(),town_count:towns.isNull()?0:towns.sub(4).readU32(),town_opcode:silver.add(0xac5b3c-0x400000).readPointer().readU8()});}});
          for(const [va,label] of [[0x7d089c,'town_wrapper'],[0x64a2bc,'town_decode'],[0x7cec78,'town_consumer']]) {
            Interceptor.attach(silver.add(va-0x400000),{onEnter(){send({event:label+'_enter'});},onLeave(){send({event:label+'_return'});if(label==='town_consumer'){const table=silver.add(0xac63bc-0x400000).readPointer().readPointer();const town=table.add(8).readPointer();send({event:'town_state_after',id:town.add(8).readU32(),values:Array.from(new Uint8Array(town.add(0x248).readByteArray(4))),float_bits:town.add(0x22c).readU32()});}}});
          }
          Interceptor.attach(silver.add(0x7d1afc-0x400000),{onEnter(){this.town=this.context.eax.toUInt32()===98;if(this.town)send({event:'enter_town_command_enter'});},onLeave(){if(this.town){send({event:'enter_town_command_return',current_town:silver.add(0xac5d58-0x400000).readPointer().readS32()});if(TOWN_VIEW_PROBE){send({event:'town_view_before',view:silver.add(0xac4c6d-0x400000).readU8()});new NativeFunction(silver.add(0x8596e0-0x400000),'void',[])();send({event:'town_view_callback_return',view:silver.add(0xac4c6d-0x400000).readU8()});}}}});
          Interceptor.attach(silver.add(0x4f2c50-0x400000),{onEnter(){try{const name=this.context.eax.readUtf16String();if(name.includes('loc_reserve')){this.reservation=true;send({event:'reservation_texture_load',name});}}catch(e){}},onLeave(){if(this.reservation)send({event:'reservation_texture_load_return'});}});
          Interceptor.attach(silver.add(0x8596e0-0x400000),{onEnter(){send({event:'open_town_view_enter'});},onLeave(){send({event:'open_town_view_return'});if(CATALOG_REQUEST_PROBE){new NativeFunction(silver.add(0x8c3c14-0x400000),'void',[])();new NativeFunction(silver.add(0x84e1f4-0x400000),'void',[])();const code=Memory.alloc(Process.pageSize);code.writeByteArray([0x53,0x31,0xc0,0xbb,...new Uint8Array(new Uint32Array([silver.add(0x991940-0x400000).toUInt32()]).buffer),0xff,0xd3,0x5b,0xc3]);Memory.protect(code,Process.pageSize,'r-x');new NativeFunction(code,'void',[])();send({event:'catalog_requests_sent'});}}});
          Interceptor.attach(silver.add(0x6d4b44-0x400000),{onEnter(){send({event:'ping_reply_enter'});},onLeave(){send({event:'ping_reply_return',received:silver.add(0xac463c-0x400000).readU8(),elapsed:silver.add(0xac4638-0x400000).readU32()});}});
          for(const [va,label] of [[0x991b34,'item_shop_list'],[0x8c3e2c,'pet_shop_list'],[0x84e320,'service_shop_list']]) {
            Interceptor.attach(silver.add(va-0x400000),{onEnter(){send({event:label+'_enter'});},onLeave(){send({event:label+'_return'});}});
          }
          Interceptor.attach(silver.add(0x8c4380-0x400000),{onEnter(){send({event:'owned_pet_info_enter'});},onLeave(){
            const table=silver.add(0xac618c-0x400000).readPointer();const records=[];
            for(let i=0;i<31;i++){const pet=table.add(i*4).readPointer();if(!pet.isNull())records.push({slot:i,id:pet.add(0x28).readU32(),resource:pet.add(4).readU32(),resource_pointer:pet.add(0x5ff8).readPointer().toString(),level_raw:pet.add(0x5ffc).readU32(),current_raw:pet.add(0x6006).readU16(),maximum_raw:pet.add(0x6008).readU16()});}
            send({event:'owned_pet_info_return',records});
          }});
          let shopErrorActive=false;
          Interceptor.attach(silver.add(0x7d1afc-0x400000),{onEnter(){this.shopError=[47,394].includes(this.context.eax.toUInt32());if(this.shopError){shopErrorActive=true;send({event:'shop_error_enter',waiting:silver.add(0xac4c58-0x400000).readU8()});}},onLeave(){if(this.shopError){send({event:'shop_error_return',waiting:silver.add(0xac4c58-0x400000).readU8()});shopErrorActive=false;}}});
          for(const va of [0x689fb0,0x9fd9e8,0x9fdafc,0x6061b0])Interceptor.attach(silver.add(va-0x400000),{onEnter(){if(shopErrorActive){try{send({event:'shop_error_text',text:this.context.eax.readUtf16String()});}catch(e){send({event:'shop_error_text_failed',reason:String(e)});}}}});
          Interceptor.attach(silver.add(0x8c40d4-0x400000),{onLeave(){const table=silver.add(0xac618c-0x400000).readPointer();const ids=[];for(let i=0;i<31;i++){const pet=table.add(i*4).readPointer();if(!pet.isNull())ids.push(pet.add(0x28).readU32());}send({event:'pet_deleted_return',ids});}});
          let equipRequests=0;let arenaCreateSent=false;let dismissSent=false;let hireSent=false;let shopPurchaseSent=false;let shopSaleSent=false;
          Interceptor.attach(silver.add(0x990638-0x400000),{onEnter(){send({event:'owned_item_list_enter'});},onLeave(){
            const pet=silver.add(0xac618c-0x400000).readPointer().readPointer();const items=[];
            if(!pet.isNull()){const arr=pet.add(0x6c).readPointer();const count=arr.isNull()?0:arr.sub(4).readU32();
              for(let i=0;i<Math.min(count,20);i++){const item=arr.add(i*0x290);items.push({instance_id:item.add(0x28).readU32(),template_id:item.add(8).readU32(),equipped:item.add(0x30).readU8(),slot:item.add(0x34).readU32()});}
              send({event:'owned_item_list_return',count,items,primary_weapon:{instance_id:pet.add(0xdf0+0x28).readU32(),template_id:pet.add(0xdf0+8).readU32()}});
              if(EQUIP_PROBE && equipRequests<(EQUIP_REPLACE_PROBE?3:2) && count>=(EQUIP_REPLACE_PROBE?2:1)){
                const selectedItem=arr.add(EQUIP_REPLACE_PROBE && equipRequests>0?0x290:0);
                equipRequests++;
                const code=Memory.alloc(Process.pageSize),bytes=[0x53,0x68,0xff,0,0,0];
                function immediate(op,value){bytes.push(op);for(let i=0;i<4;i++)bytes.push((value>>>(8*i))&255);}
                immediate(0xb8,pet.add(0x28).readU32());
                immediate(0xba,selectedItem.add(0x28).readU32());
                immediate(0xb9,selectedItem.toUInt32());
                immediate(0xbb,silver.add(0x9903a4-0x400000).toUInt32());
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'equip_request_builder_return'});
              }
              if(ARENA_CREATE_PROBE && !arenaCreateSent){
                arenaCreateSent=true;
                const code=Memory.alloc(Process.pageSize);
                // Delphi register ABI: five callee-cleaned stack arguments.
                const bytes=[0x53,0x6a,1,0x6a,2,0x6a,40,0x6a,0,0x6a,0,0x31,0xc0,0xba,1,0,0,0,0xb9,2,0,0,0,0xbb];
                const target=silver.add(0xa0a6f4-0x400000).toUInt32();
                for(let i=0;i<4;i++)bytes.push((target>>>(i*8))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'arena_create_probe_sent'});
              }
              if(DISMISS_PROBE && !dismissSent){
                dismissSent=true;const code=Memory.alloc(Process.pageSize);const bytes=[0x53,0xb8,2,0,0,0,0xbb];
                const target=silver.add(0x8c3c64-0x400000).toUInt32();for(let i=0;i<4;i++)bytes.push((target>>>(i*8))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');new NativeFunction(code,'void',[])();
              }
              if(HIRE_PROBE && !hireSent){
                hireSent=true;const code=Memory.alloc(Process.pageSize);
                const bytes=[0x53,0xb8,2,0,0,0,0xbb];const target=silver.add(0x8c3c34-0x400000).toUInt32();
                for(let i=0;i<4;i++)bytes.push((target>>>(i*8))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'hire_probe_sent',candidate:2});
              }
              if(SHOP_SALE_PROBE && !shopSaleSent && items.length){
                shopSaleSent=true;
                const instance=items[items.length-1].instance_id;
                const code=Memory.alloc(Process.pageSize);
                const bytes=[0x53,0xb8,1,0,0,0,0xba];
                for(let i=0;i<4;i++)bytes.push((instance>>>(i*8))&255);
                bytes.push(0xb9,1,0,0,0,0xbb);
                const target=silver.add(0x99034c-0x400000).toUInt32();
                for(let i=0;i<4;i++)bytes.push((target>>>(i*8))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'shop_sale_probe_sent',owner:1,instance,quantity:1});
              }
              if(SHOP_PURCHASE_PROBE && !shopPurchaseSent){
                shopPurchaseSent=true;
                const code=Memory.alloc(Process.pageSize);
                const bytes=[0x53,0x6a,0,0xb8,1,0,0,0,0xba,2,0,0,0,0xb9,1,0,0,0,0xbb];
                const target=silver.add(0x9919c8-0x400000).toUInt32();
                for(let i=0;i<4;i++)bytes.push((target>>>(i*8))&255);
                bytes.push(0xff,0xd3,0x5b,0xc3);code.writeByteArray(bytes);Memory.protect(code,Process.pageSize,'r-x');
                new NativeFunction(code,'void',[])();send({event:'shop_purchase_probe_sent',owner:1,offer:2,quantity:1});
              }}
          }});
          Interceptor.attach(silver.add(0x7d4c28-0x400000),{onLeave(){const character=silver.add(0xac5b7c-0x400000).readPointer();send({event:'asset_count_return',credits:character.add(0x230).readU32(),gold:character.add(0x234).readU32()});}});
          let backgroundObserved=false;Interceptor.attach(silver.add(0x9de154-0x400000),{onEnter(){this.first=!backgroundObserved;backgroundObserved=true;if(this.first)send({event:'town_background_render_enter'});},onLeave(){if(this.first){const town=silver.add(0xac63bc-0x400000).readPointer().readPointer().add(8).readPointer();send({event:'town_background_render_return',town_id:town.add(8).readU32(),background_loaded:town.add(0x20d).readU8(),background:town.add(0x10e).readCString(town.add(0x10d).readU8())});}}});
          let selectSent=false;
          const selectCode=Memory.alloc(Process.pageSize);
          const selectBytes=[0x31,0xc0,0x31,0xd2,0xb9];
          const selectTarget=silver.add(0x8a3108-0x400000).toUInt32();
          for(let i=0;i<4;i++)selectBytes.push((selectTarget>>>(i*8))&255);
          selectBytes.push(0xff,0xd1,0xc3);selectCode.writeByteArray(selectBytes);Memory.protect(selectCode,Process.pageSize,'r-x');
          const selectNative=new NativeFunction(selectCode,'void',[]);
          Interceptor.attach(silver.add(0x88a4cc-0x400000),{onEnter(){send({event:'character_select_result',status:this.context.eax.readU8()});},onLeave(){send({event:'character_select_result_return'});}});
          let parsingCharacters=false;
          Interceptor.attach(silver.add(0x9f5548-0x400000),{onEnter(a){if((a[0].toUInt32()&255)===16)send({event:'character_packet_gate',flag:silver.add(0xac5834-0x400000).readPointer().readU8(),override:a[3].toUInt32()&255});}});
          Interceptor.attach(silver.add(0x889eac-0x400000),{onEnter(){this.count=this.context.eax.readU16();parsingCharacters=true;send({event:'silver_CharSelectInfo',count:this.count});},onLeave(){send({event:'silver_CharSelectInfo_return',flag_ac5814:silver.add(0xac5814-0x400000).readPointer().readU8(),flag_ac4c58:silver.add(0xac4c58-0x400000).readU8()});parsingCharacters=false;if(CREATE_PROBE && this.count===0 && !createSent){createSent=true;send({event:'synthetic_character_create',name:invalidCreateName.add(12).readUtf16String(),trampoline:createCode.toString()});createNative();}if(SELECT_PROBE && this.count>0 && !selectSent){selectSent=true;send({event:'synthetic_character_selection',slot:0,trampoline:selectCode.toString()});selectNative();}}});
          Interceptor.attach(silver.add(0x8a2868-0x400000),{onEnter(){if(parsingCharacters)send({event:'character_selection_update',enabled:this.context.eax.toUInt32()&255});}});
          Interceptor.attach(silver.add(0x88a3b7-0x400000),{onEnter(){
            const slots=silver.add(0xac618c-0x400000).readPointer();
            const object=slots.add(this.context.ebx.toUInt32()*4).readPointer();
            const name=object.add(0x5ff4).readPointer();
            send({event:'character_record_processed',slot:this.context.ebx.toUInt32(),record_id:object.add(0x28).readU32(),resource_type:object.add(4).readU32(),name:name.isNull()?'':name.readUtf16String()});
          }});
          if(TRACE_CHARACTER_RECORD){
            for(const va of [0x889f25,0x889fbb,0x88a00a,0x88a03e,0x88a0c6,0x88a289,0x88a354]){
              Interceptor.attach(silver.add(va-0x400000),{onEnter(){if(parsingCharacters)send({event:'character_record_checkpoint',va:'0x'+va.toString(16)});}});
            }
          }
          let parsingList=false,selected=false;

          Interceptor.attach(silver.add(0x87d1cc-0x400000),{
            onEnter(){parsingList=true;send({event:'silver_LSServerList',count:this.context.eax.readU8(),header_unknown:this.context.eax.add(1).readU8()});},
            onLeave(){
              send({event:'silver_LSServerList_return'});parsingList=false;
              if(SERVER_LOGIN && !selected){
                selected=true;
                const control=silver.add(0xacdda0-0x400000).readPointer();
                const prior=control.add(0x280).readS32();
                control.add(0x280).writeS32(0);
                send({event:'synthetic_server_selection',index:0,prior:prior});
                new NativeFunction(silver.add(0x71e998-0x400000),'void',[])();
              }
            }
          });
          Interceptor.attach(silver.add(0x71e594-0x400000),{onEnter(){if(parsingList)send({event:'silver_server_list_refresh'});}});
          Interceptor.attach(silver.add(0x71fea0-0x400000),{onEnter(){if(parsingList)send({event:'silver_server_record',raw_hex:hex(this.context.edx,16)});}});
          const connect=new NativeFunction(m.getExportByName('AaaAa'),'void',['pointer','uint32','pointer','uint32'],'mscdecl');
          const host=Memory.allocUtf8String('127.0.0.1');
          connect(host,LOOPBACK_PORT,ptr(0),0);
          return {port:LOOPBACK_PORT};
        };
        function hex(p,n){return Array.from(new Uint8Array(p.readByteArray(n))).map(v=>v.toString(16).padStart(2,'0')).join('');}
        rpc.exports.capture = function() {
          if(TRACE_WINDOWS)send({event:'startup_state',mode_76dab4:ptr('0x76e2ac').readPointer().readU8(),loaded:ptr('0x76df14').readPointer().readU8(),ready:ptr('0x76dbb0').readU8(),clock:ptr('0x76e314').readPointer().readU32(),deadline:ptr('0x76e568').readPointer().readPointer().add(0x3cc).readU32()});
          if(TRACE_WINDOWS)send({event:'startup_threads',threads:Process.enumerateThreads().map(t=>({id:t.id,state:t.state,pc:t.context.pc.toString(),backtrace:Thread.backtrace(t.context,Backtracer.ACCURATE).map(p=>DebugSymbol.fromAddress(p).toString())}))});
          const silverModule=Process.findModuleByName('silver.dll');
          if(silverModule){
            const owner=silverModule.base.add(0xac5c80-0x400000).readPointer();
            const root=owner.isNull()?ptr(0):owner.readPointer();
            send({event:'shared_config_root',root:root.isNull()?null:root.readUtf16String()});
          }
          send({event:'modules', modules:Process.enumerateModules().map(m=>({name:m.name,base:m.base.toString(),size:m.size}))});
          const m = Process.findModuleByName('orange.dll');
          if (!m) {
            const p = ptr('0x78651c').readPointer();
            send({event:'orange_callback',address:p.toString(),range:Process.findRangeByAddress(p)});
            if (p.isNull()) return null;
            let page = p.and(ptr('0xfffff000'));
            for(let i=0;i<1024;i++,page=page.sub(4096)) {
              try {
                if(page.readU16() !== 0x5a4d) continue;
                const nt = page.add(page.add(0x3c).readU32());
                if(nt.readU32()!==0x4550) continue;
                const size = nt.add(0x50).readU32();
                send({event:'image',base:page.toString(),size:size,callback:p.toString()},page.readByteArray(size));
                return true;
              } catch(_) {}
            }
            return null;
          }
          send({event:'image', base:m.base.toString(), size:m.size,
            exports:m.enumerateExports(),transport_callback:ptr('0x78651c').readPointer().toString()}, m.base.readByteArray(m.size));
          const regions=new Set();
          for (const exp of m.enumerateExports()) {
            const address=exp.address;
            if(address.readU8()!==0xe9) continue;
            const target=address.add(5).add(address.add(1).readS32());
            const range=Process.findRangeByAddress(target);
            if(!range || regions.has(range.base.toString())) continue;
            regions.add(range.base.toString());
            send({event:'unpacked_region',base:range.base.toString(),size:range.size,export:exp.name,target:target.toString()},range.base.readByteArray(range.size));
          }
          return true;
        };
        rpc.exports.loaditems = function() {
          const m=Process.getModuleByName('silver.dll');
          new NativeFunction(m.base.add(0xa7005c-0x400000),'void',[])();
          const table=m.base.add(0xac637c-0x400000).readPointer().readPointer();
          const bound=m.base.add(0xac4e70-0x400000).readS32();
          return {table:table.toString(),bound:bound,ids:table.isNull()?[]:Array.from({length:Math.min(Math.max(bound,0),8)},(_,i)=>table.add(i*0x3a78+0x116).readU16())};
        };
        '''.replace('BATTLE_DOOR_GRID_HOOK',Path(__file__).with_name('battle_door_grid.js').read_text()).replace('TREATMENT_TARIFF_HOOK',Path(__file__).with_name('treatment_tariff.js').read_text()).replace('UPGRADE_KIT_WAREHOUSE_HOOK',Path(__file__).with_name('upgrade_kit_warehouse.js').read_text()).replace('UPGRADE_KIT_INVENTORY_HOOK',Path(__file__).with_name('upgrade_kit_inventory.js').read_text()).replace('ENHANCEMENT_POLICY',json.dumps(__import__('tio.enhancement',fromlist=['EnhancementRules']).EnhancementRules().config)).replace('SHOP_REQUEST_RETRY_HOOK',Path(__file__).with_name('shop_request_retry.js').read_text()).replace('LOCAL_TREATMENT_RATE',str(__import__('tio.battle_recovery',fromlist=['CREDITS_PER_HP']).CREDITS_PER_HP)).replace('WAREHOUSE_PARTIAL_PROBE','true' if '--warehouse-partial-probe' in sys.argv else 'false').replace('WAREHOUSE_TRANSFER_PROBE','true' if '--warehouse-transfer-probe' in sys.argv else 'false').replace('BATTLE_HEAL_PROBE','true' if '--battle-heal-probe' in sys.argv else 'false').replace('BATTLE_MOVE_PROBE','true' if '--battle-move-probe' in sys.argv else 'false').replace('TURN_TIMEOUT_PROBE','true' if '--turn-timeout-probe' in sys.argv else 'false').replace('ARENA_START_PROBE','true' if '--battle-scene-probe' in sys.argv else 'false').replace('EQUIP_REPLACE_PROBE','true' if '--equip-replace-probe' in sys.argv else 'false').replace('EQUIP_PROBE','true' if '--equip-probe' in sys.argv else 'false').replace('ARENA_LEAVE_PROBE','true' if '--arena-leave-probe' in sys.argv else 'false').replace('ARENA_READY_PROBE','true' if '--arena-ready-probe' in sys.argv else 'false').replace('ARENA_CREATE_PROBE','true' if '--arena-create-probe' in sys.argv else 'false').replace('DISMISS_PROBE','true' if '--dismiss-probe' in sys.argv else 'false').replace('HIRE_PROBE','true' if '--hire-probe' in sys.argv else 'false').replace('SHOP_SALE_PROBE','true' if '--shop-sale-probe' in sys.argv else 'false').replace('SHOP_PURCHASE_PROBE','true' if '--shop-purchase-probe' in sys.argv else 'false').replace('CATALOG_REQUEST_PROBE','true' if '--catalog-request-probe' in sys.argv else 'false').replace('TOWN_VIEW_PROBE','true' if '--town-view-probe' in sys.argv else 'false').replace('TRACE_WINDOWS','true' if '--trace-windows' in sys.argv else 'false').replace('RESOLVER_PROBE', 'true' if '--resolver' in sys.argv or '--fix-user32' in sys.argv else 'false').replace('FIX_USER32','true' if '--fix-user32' in sys.argv else 'false').replace('LOOPBACK_PORT',str(exchange.port if exchange else 0)).replace('SELECT_PROBE','true' if '--select-probe' in sys.argv else 'false').replace('CREATE_SUCCESS_PROBE','true' if '--create-success-probe' in sys.argv else 'false').replace('CREATE_PROBE','true' if '--create-probe' in sys.argv else 'false').replace('TRACE_CHARACTER_RECORD','true' if '--character-record' in sys.argv else 'false').replace('SERVER_LOGIN','true' if '--server-login' in sys.argv else 'false').replace('SYNTHETIC_LOGIN','true' if '--login-result' in sys.argv else 'false'))
        def message(m, data):
            if m.get('payload', {}).get('event') == 'unpacked_region':
                item=m['payload']
                (OUT / ('unpacked-'+item['base']+'.bin')).write_bytes(data)
                (OUT / ('unpacked-'+item['base']+'.json')).write_text(json.dumps(item,indent=2),encoding='utf-8')
                print(json.dumps(item),flush=True)
                return
            if m.get('payload', {}).get('event') == 'partial_image':
                (OUT / 'orange.partial.bin').write_bytes(data)
                (OUT / 'orange.partial.json').write_text(json.dumps(m['payload']), encoding='utf-8')
                return
            if m.get('payload', {}).get('event') == 'image':
                (OUT / 'orange.mapped.bin').write_bytes(data)
                (OUT / 'orange.mapped.json').write_text(json.dumps(m['payload'], indent=2), encoding='utf-8')
                print('Captured', len(data), 'bytes', flush=True)
            else:
                print(json.dumps(m), flush=True)
        script.on('message', message)
        script.load()
        if not late:
            if '--visible-launch' in sys.argv and not late:
                import ctypes
                resume=ctypes.WinDLL('ntdll').NtResumeProcess
                resume.argtypes=[ctypes.c_void_p];resume.restype=ctypes.c_long
                if resume(int(proc._handle))!=0:raise RuntimeError('Owned process resume failed')
            else:
                device.resume(pid)
            time.sleep(12)
        if '--visible-launch' in sys.argv:
            from window_compat import install as install_window_compat
            # Keep the adapter alive with this session. Delphi's zero-sized
            # TApplication owner otherwise hides TForm1 from window discovery.
            window_compat_script = install_window_compat(session, message)
        print('capture:', script.exports_sync.capture(), flush=True)
        if '--load-item-fixture' in sys.argv:
            def timeout_owned():
                try: device.kill(pid)
                except frida.ProcessNotFoundError: pass
            watchdog=threading.Timer(20,timeout_owned)
            watchdog.start()
            try: print('item_fixture_result:',script.exports_sync.loaditems(),flush=True)
            finally: watchdog.cancel()
        if exchange:
            exchange.start()
            print('loopback:',script.exports_sync.connectloopback(),flush=True)
            exchange.finish()
            print(json.dumps(exchange.events),flush=True)
    finally:
        if exchange:
            exchange.stop()
            exchange.finish()
        # Terminate only our spawned process before detaching: detach can wait on a
        # client thread blocked inside native UI/resource loading.
        try:
            device.kill(pid)
        except frida.ProcessNotFoundError:
            pass
        if session:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass



if __name__ == '__main__':
    main()

