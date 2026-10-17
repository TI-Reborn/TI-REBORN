"""Observe one explicitly selected player game's login route without arguments.

Only code fingerprints, fixed transport bindings, PID/parent metadata and
aggregate function/result counters are read. No credential/UI/packet reads,
game commands, input simulation, return replacement or auth calls. Temporary
Frida observers are detached in finally. One bounded run never follows a new PID.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import struct
import threading
import time

import frida
import pefile

from inspect_native_tls_route import inspect,api,require,UNPACKED_SHA,LAUNCHER_014_SHA

LAUNCHER_SHA='8a34ea68124eebfb6ded5f2c9d8c96dee85befb9eb99b5efb57d5dea708b4d52'


class ProcessEntry(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('usage',wintypes.DWORD),('pid',wintypes.DWORD),
        ('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),
        ('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),
        ('name',wintypes.WCHAR*260)]


def parent_guard(pid,expected):
    k=api()
    k.Process32FirstW.argtypes=k.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(ProcessEntry)]
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    require(snapshot not in (None,ctypes.c_void_p(-1).value),'Process parent snapshot unavailable')
    found=False
    try:
        row=ProcessEntry();row.size=ctypes.sizeof(row)
        require(k.Process32FirstW(snapshot,ctypes.byref(row)),'Process parent metadata unavailable')
        while True:
            if row.pid==pid:
                require(row.parent==expected,'Target game helper parent mismatch')
                found=True;break
            if not k.Process32NextW(snapshot,ctypes.byref(row)):break
    finally:k.CloseHandle(snapshot)
    require(found,'Target game PID is no longer present')
    helper=k.OpenProcess(0x1000,False,expected)
    require(helper,'Expected helper process unavailable')
    try:
        path=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(path))
        require(k.QueryFullProcessImageNameW(helper,0,path,ctypes.byref(size)),'Helper image metadata unavailable')
        require(hashlib.sha256(Path(path.value).read_bytes()).hexdigest() in (LAUNCHER_SHA,LAUNCHER_014_SHA),
            'Helper is not the reviewed published launcher; observer refused')
    finally:k.CloseHandle(helper)


def relocated_reference(image,rva,size,basis):
    raw=bytearray(image.get_data(rva,size));delta=basis-image.OPTIONAL_HEADER.ImageBase
    for block in image.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if rva<=entry.rva<rva+size:
                require(entry.type==3 and entry.rva<=rva+size-4,'Unknown observer code relocation')
                offset=entry.rva-rva
                struct.pack_into('<I',raw,offset,(struct.unpack_from('<I',raw,offset)[0]+delta)&0xffffffff)
    return raw.hex()


def reference_functions(args,route):
    rows=[]
    for filename,specs in (
            ('silver.dll',(('manual_submit',0x87ddd8,64),('silver_transport',0x606080,107))),
            ('ti.exe',(('ti_unicode_adapter',0x71c1b8,189),('ti_connect_dispatch',0x718b94,327)))):
        image=pefile.PE(str(args.root/filename));basis=int(route['module_bases'][filename],16)
        try:
            for name,va,size in specs:
                rows.append(dict(name=name,address=basis+va-0x400000,
                    expected=relocated_reference(image,va-0x400000,size,basis)))
        finally:image.close()
    orange=int(route['module_bases']['orange.dll'],16)
    thunk=int(route['export_target'],16);original=int(route['original_connect_target'],16);unpacked=original-0x1670
    rows.append(dict(name='orange_export',address=orange+0x118f,
        expected=(b'\xe9'+struct.pack('<i',thunk-(orange+0x118f+5))).hex()))
    # BuildThunk's constant bytes and the two known destination operands were
    # already fully validated read-only. Reconstruct its exact live bytes.
    from inspect_native_tls_route import THUNK_TEMPLATE
    native=bytearray(THUNK_TEMPLATE)
    if route.get('route_variant')=='0.1.4-byte-mode':native[14]=0x80
    for offset,value in ((6,thunk-2048+2304),(18,args.login_port),(25,args.session_port)):
        struct.pack_into('<I',native,offset,value)
    struct.pack_into('<i',native,36,original-(thunk+40))
    rows.append(dict(name='tls_thunk',address=thunk,expected=native.hex()))
    raw=(Path(__file__).resolve().parents[1]/'evidence/loader-user32-fix/unpacked-0xc9b0000.bin').read_bytes()
    require(hashlib.sha256(raw).hexdigest()==UNPACKED_SHA,'Unknown native transport observer fixture')
    for name,rva,size,relocs in (
            ('orange_original',0x1670,40,((1,0x50f5),(11,0x50f0))),
            ('orange_connect_mode',0x1a90,290,((61,0x3008),(276,0x3004))),
            ('orange_start_thread',0x28a0,102,((76,0x2830),(86,0x3030))),
            ('orange_thread_entry',0x2830,33,()),
            ('orange_socket_worker',0x2910,27,((23,0x3048),))):
        expected=bytearray(raw[rva:rva+size])
        for offset,operand in relocs:
            require(struct.unpack_from('<I',expected,offset)[0]==0xc9b0000+operand,'Unknown observer native relocation')
            struct.pack_into('<I',expected,offset,unpacked+operand)
        rows.append(dict(name=name,address=unpacked+rva,expected=expected.hex()))
    return rows,unpacked


SOURCE=r"""
'use strict';
const spec=SPEC;
const counters={};
const hooks=[];
let stopped=false;
let initialized=false;
let stage='process-architecture';
let diagnosticName='none';
const apiMetadata={};
function bytes(p,n){return Array.from(new Uint8Array(p.readByteArray(n))).map(x=>x.toString(16).padStart(2,'0')).join('');}
function slot(name){return counters[name]??(counters[name]={entered:0,returned:0});}
rpc.exports={
  snapshot(){return {counters};},
  stop(){if(!stopped){for(const hook of hooks)hook.detach();Interceptor.flush();stopped=true;}return {counters,initialized,installed_hooks:hooks.length,own_observers_detached:true,
    architecture:Process.arch,pointer_size:Process.pointerSize,os_api_binding_metadata:apiMetadata};}
};
try{
diagnosticName='process-architecture';
if(Process.arch!=='ia32'||Process.pointerSize!==4)throw new Error('Unsupported observer target architecture');
// Fingerprints are read only before any observers alter their own code entry.
for(const item of spec.functions){
  stage='fingerprint';
  diagnosticName=item.name;
  if(bytes(ptr(item.address),item.expected.length/2)!==item.expected)throw new Error('Unknown native code fingerprint: '+item.name);
}
stage='winsock-export';diagnosticName='WSAGetLastError';
const winsock=Process.getModuleByName('ws2_32.dll');
const lastError=new NativeFunction(winsock.getExportByName('WSAGetLastError'),'int',[]);
const apiBindings=[];
const apiTypes=[['socket',0x3048],['connect',0x3054],['recv',0x3058],['send',0x3064]];
for(const [name,offset] of apiTypes){
  stage='api-binding';diagnosticName=name;
  const imported=ptr(spec.unpacked+offset).readPointer();
  const owner=Process.findModuleByAddress(imported);
  const basename=owner===null?null:(/^[a-z0-9_.-]{1,64}$/i.test(owner.name)?owner.name:'other-module');
  // ORANGE's packer may interpose its own import trampoline. No arbitrary
  // trampoline bytes are read or followed. Observe the known system exports
  // in this one guarded process; native counters correlate the same retry.
  const address=winsock.getExportByName(name);
  apiMetadata[name]={original_import_pointer:imported.toString(),original_import_module:basename,
    observed_export_module:'ws2_32.dll',observed_export_name:name};
  apiBindings.push([name,address]);
}
function attach(name,address,kind){
  stage='hook-install';diagnosticName=name;
  slot(name);
  hooks.push(Interceptor.attach(address,{
    onEnter(){slot(name).entered++;},
    onLeave(result){
      const row=slot(name);row.returned++;
      if(!kind)return;
      const value=result.toInt32();
      if(kind==='socket'){
        const key=value===-1?'invalid_socket':'socket_created';row[key]=(row[key]??0)+1;
      }else{
        const key=value===-1?'failure':(value===0?'zero':'positive');row[key]=(row[key]??0)+1;
        if(kind==='recv'&&value>0){row.positive_sizes??={};const size=String(value);row.positive_sizes[size]=(row.positive_sizes[size]??0)+1;}
        if((kind==='connect'||kind==='recv')&&value===-1){const error=String(lastError());row.wsa_errors??={};row.wsa_errors[error]=(row.wsa_errors[error]??0)+1;}
      }
    }
  }));
}
for(const item of spec.functions)attach(item.name,ptr(item.address),null);
// Observe known Winsock export result counts, without inspecting any args.
for(const [name,address] of apiBindings)attach('os_'+name,address,name);
Interceptor.flush();
initialized=true;
send({event:'observer_ready',pid:Process.id,entry_count:spec.functions.length,arguments_read:false,registers_read:false,payloads_read:false});
}catch(error){
  // Never forward a Frida exception or stack: it may contain runtime memory.
  // These two fields come only from the fixed guard/hook labels above.
  send({event:'observer_initialization_failed',stage,diagnostic_name:diagnosticName,installed_hooks:hooks.length});
}
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--bridge-pid',type=int,required=True)
    parser.add_argument('--created-utc',required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--login-port',type=int,required=True)
    parser.add_argument('--session-port',type=int,required=True)
    parser.add_argument('--duration',type=int,default=90)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();require(60<=args.duration<=120,'Observation duration must be 60–120 seconds')
    args.root=args.root.resolve();parent_guard(args.pid,args.bridge_pid)
    route=inspect(args)
    require(route['passed'] and route['created_utc']==args.created_utc,'Target route/creation guard mismatch')
    functions,unpacked=reference_functions(args,route)
    source=SOURCE.replace('SPEC',json.dumps(dict(functions=functions,unpacked=unpacked)),1)
    report=dict(kind='bounded passive owned game login counters',pid=args.pid,bridge_pid=args.bridge_pid,
        created_utc=route['created_utc'],requested_duration_s=args.duration,credentials_read=False,
        ui_fields_read=False,packet_buffers_read=False,arguments_read=False,registers_read=False,
        auth_or_game_functions_called=False,network_requests_initiated=0,input_simulated=False,
        return_values_replaced=False,observer_own_hooks_only=True,counters={})
    changed=threading.Event();ready=threading.Event();failures=[];session=None;script=None
    allowed_names={row['name'] for row in functions}|{'none','process-architecture','WSAGetLastError','socket','connect','recv','send',
        'os_socket','os_connect','os_recv','os_send'}
    allowed_stages={'process-architecture','fingerprint','winsock-export','api-binding','hook-install'}
    def message(message,data):
        if message.get('type')=='send' and message.get('payload',{}).get('event')=='observer_ready':
            ready.set();print(json.dumps(dict(event='observer_ready',pid=args.pid,duration_s=args.duration)),flush=True)
        elif message.get('type')=='send' and message.get('payload',{}).get('event')=='observer_initialization_failed':
            payload=message['payload'];stage=payload.get('stage');name=payload.get('diagnostic_name')
            if stage in allowed_stages and name in allowed_names:
                report.update(initialization_stage=stage,diagnostic_name=name)
                count=payload.get('installed_hooks')
                if type(count) is int and 0<=count<=15:report['installed_hooks']=count
            else:report.update(initialization_stage='unrecognized',diagnostic_name='unrecognized')
            failures.append('Observer guarded initialization failed');changed.set()
            print(json.dumps(dict(event='observer_initialization_failed',
                stage=report['initialization_stage'],diagnostic_name=report['diagnostic_name'])),flush=True)
        elif message.get('type')=='error':failures.append('Observer script initialization/runtime error');changed.set()
    try:
        session=frida.get_local_device().attach(args.pid)
        session.on('detached',lambda reason,*extra:(report.update(detached_reason=str(reason)),changed.set()))
        script=session.create_script(source);script.on('message',message);script.load()
        require(ready.wait(5) and not failures,'Passive observer did not initialize safely')
        started=time.monotonic()
        while not changed.wait(min(5,max(0,args.duration-(time.monotonic()-started)))):
            report['counters']=script.exports_sync.snapshot()['counters']
            if time.monotonic()-started>=args.duration:break
        report['observed_duration_s']=round(time.monotonic()-started,3)
        report['passed']=not failures
    except Exception as error:
        report['passed']=False;report['error_type']=type(error).__name__
    finally:
        if script is not None:
            try:report.update(script.exports_sync.stop())
            except Exception:report['own_observers_detached']=False
            try:script.unload();report['script_unloaded']=True
            except Exception:report['script_unloaded']=False
        if session is not None:
            try:session.detach();report['session_detached']=True
            except Exception:report['session_detached']=False
        if report.get('script_unloaded'):report['own_observers_detached']=True
        # Process exit unloads all injected observers, with no guessed reattach.
        if report.get('detached_reason')=='process-terminated':report['own_observers_detached']=True
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(event='observer_finished',passed=report['passed'],pid=args.pid,report=str(args.output))),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
