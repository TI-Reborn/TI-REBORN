"""Exercise passive observer guards/counter cleanup with isolated Node doubles.

This does not attach to, read or control any actual process. All callback return
values and code bytes belong to controlled static fixtures. No game/auth calls.
"""
import argparse
import json
from pathlib import Path
import subprocess

from observe_native_login_route import SOURCE,reference_functions


HARNESS=r"""
const vm=require('vm');
const source=SOURCE;
const spec=SPEC;
const cases=[];
for(const variant of ['normal','fingerprint-failure','architecture-failure','missing-export','hook-failure']){
 const messages=[],hooks=[];let detachCount=0;
 const byAddress=new Map(spec.functions.map(x=>[x.address,x]));
 const bindings=new Map([0x3048,0x3054,0x3058,0x3064].map((x,i)=>[spec.unpacked+x,0x3000+i]));
 const exports={socket:0x1000,connect:0x1001,recv:0x1002,send:0x1003,WSAGetLastError:0x2000};
 function p(value){return {value,toString:()=>value.toString(16),
  readByteArray(n){let x=byAddress.get(value);if(!x)throw new Error('unplanned code read');let raw=Buffer.from(x.expected,'hex');if(raw.length!==n)throw new Error('size');if(variant==='fingerprint-failure'&&x.name==='manual_submit')raw[0]^=1;return new Uint8Array(raw).buffer;},
  readPointer(){if(!bindings.has(value))throw new Error('unplanned pointer read');return p(bindings.get(value));}
 };}
 const ctx={Uint8Array,ptr:p,rpc:{exports:{}},send:x=>messages.push(x),
  Process:{id:1,arch:variant==='architecture-failure'?'x64':'ia32',pointerSize:variant==='architecture-failure'?8:4,
   getModuleByName:name=>({getExportByName:name=>{if(variant==='missing-export'&&name==='socket')throw new Error('missing controlled export');return p(exports[name]);}}),
   findModuleByAddress:addr=>({name:'orange.dll'})},
  NativeFunction:function(){return ()=>10061;},
  Interceptor:{flush(){},attach(addr,callbacks){if(variant==='hook-failure'&&addr.value===0x1001)throw new Error('controlled hook failure');const handle={detach(){detachCount++;}};hooks.push({address:addr.value,callbacks});return handle;}}
 };
 vm.runInNewContext(source,ctx);
 if(variant==='normal'){
  if(hooks.length!==15||messages[0].event!=='observer_ready')throw new Error('normal initialization');
  const result=x=>({toInt32:()=>x});
  for(const h of hooks){h.callbacks.onEnter();h.callbacks.onLeave(result(0));}
  for(const [index,value]of [[11,-1],[11,42],[12,-1],[13,100],[13,-1],[14,42]]){
   hooks[index].callbacks.onEnter();hooks[index].callbacks.onLeave(result(value));
  }
  const c=ctx.rpc.exports.snapshot().counters;
  if(c.os_socket.invalid_socket!==1||c.os_socket.socket_created!==2||c.os_connect.wsa_errors['10061']!==1||c.os_recv.positive!==1||c.os_recv.failure!==1||c.os_send.positive!==1)throw new Error('counter classifications');
 }else if(messages[0].event!=='observer_initialization_failed')throw new Error('guard diagnostic');
 const stopped=ctx.rpc.exports.stop();ctx.rpc.exports.stop();
 if(detachCount!==hooks.length||!stopped.own_observers_detached)throw new Error('cleanup lifecycle');
 if(variant==='normal'&&stopped.os_api_binding_metadata.socket.original_import_module!=='orange.dll')throw new Error('packer trampoline classification');
 cases.push({case:variant,passed:true,installed_hooks:hooks.length,detached_hooks:detachCount,
  diagnostic:messages[0].event==='observer_initialization_failed'?{stage:messages[0].stage,name:messages[0].diagnostic_name}:null});
}
process.stdout.write(JSON.stringify({passed:true,method:'Isolated Node Frida API doubles; controlled static code bytes, imported trampolines and synthetic return values; no target attachment or game/auth calls',cases}));
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--route-report',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();route=json.loads(args.route_report.read_text())
    args.login_port=route['decoded_ports']['login'];args.session_port=route['decoded_ports']['session']
    functions,unpacked=reference_functions(args,route)
    assert len(functions)==11
    assert not any(word in SOURCE for word in ('onEnter(args)','this.context','readUtf8String','readCString','readUtf16String'))
    source=SOURCE.replace('SPEC',json.dumps(dict(functions=functions,unpacked=unpacked)),1)
    harness=HARNESS.replace('SOURCE',json.dumps(source),1).replace('SPEC',json.dumps(dict(functions=functions,unpacked=unpacked)),1)
    run=subprocess.run(['node','-'],input=harness,text=True,capture_output=True,check=True)
    report=json.loads(run.stdout)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],cases=len(report['cases']),actual_processes_observed=0)))


if __name__=='__main__':main()
