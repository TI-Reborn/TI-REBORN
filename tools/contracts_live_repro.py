"""Restart only the two owned loopback fixtures and observe native packet metadata.

Real authentication uses the existing local bridge. No server replies or GUI
inputs are injected. The passive observer excludes authentication payloads and
records only opcodes, lengths, callback addresses and battle gating flags.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.contracts_live_native_test import guards
from tools.verify_contracts_city_graphical import LocalBridge


OBSERVER = r'''
const silver=Process.getModuleByName('silver.dll'),exe=Process.mainModule;
const at=va=>silver.base.add(va-0x400000),ex=va=>exe.base.add(va-0x400000);
let sequence=0;
function state(){return {replay:at(0xac5834).readPointer().readU8(),battle:at(0xac64a0).readPointer().readU8(),load:ex(0x76deb4).readPointer().readU8(),overlay:ex(0x76e2ac).readPointer().readU8()};}
Interceptor.attach(at(0x9f5548),{
  onEnter(args){
    const opcode=args[0].toUInt32()&255,length=args[2].toUInt32();
    this.row={event:'native_packet',sequence:++sequence,opcode,length,forced:args[3].toUInt32()&255,before:state()};
    if((opcode===0xc8 || opcode===0xf0) && length>=3 && length<=65533)this.row.subopcode=args[1].add(1).readU16();
    if(opcode===0x37 && length>=5 && length<=65533)this.row.owner=args[1].add(1).readU32();
    if(opcode===0x38 && length>=5 && length<=65533)this.row.seconds=args[1].add(1).readU32();
  },onLeave(result){this.row.handled=result.toUInt32();this.row.after=state();send(this.row);}
});
Interceptor.attach(ex(0x71cc6c),{onEnter(args){
  const opcode=args[0].toUInt32()&65535,length=args[2].toUInt32();
  send({event:'native_callback_queued',opcode,length,callback:args[3].sub(silver.base).add(0x400000).toString()});
}});
send({event:'passive_native_observer_ready',pid:Process.id});
'''


def main():
    import frida
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-pids',type=int,nargs=2,required=True)
    parser.add_argument('--seconds',type=int,default=1200)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.seconds<=1800 or len(set(args.replace_pids))!=2:
        parser.error('Require two distinct owned PIDs and a bounded observation')
    directory=args.output.resolve()
    allowed=(ROOT/'reports/contracts-local').resolve()
    if allowed not in directory.parents or directory.exists():
        raise ValueError('Require a fresh report directory under owned local reports')
    device=frida.get_local_device()
    roots={c:ROOT/('reports/contracts-local/clients/game-'+c) for c in ('a','b')}
    # Validate both exact live images before stopping either process.
    for c,pid in zip(('a','b'),args.replace_pids):
        guards(roots[c])
        session=device.attach(pid)
        try:
            script=session.create_script("rpc.exports.image=()=>({pid:Process.id,path:Process.mainModule.path});")
            script.load();image=script.exports_sync.image()
            if image['pid']!=pid or Path(image['path']).resolve()!=roots[c]/'ti.exe':
                raise ValueError('Replacement PID is not this owned loopback fixture')
        finally:session.detach()
    directory.mkdir(parents=True)
    events=(directory/'events.jsonl').open('w',encoding='utf-8')
    lock=threading.Lock()
    def record(copy,event):
        with lock:
            events.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),copy=copy,**event))+'\n')
            events.flush()
    for pid in args.replace_pids:device.kill(pid)
    secrets=[line.split('\t') for line in (ROOT/'data/contracts-local/LOCAL_TEST_ACCOUNTS.txt').read_text(encoding='utf-8').splitlines() if line and not line.startswith('#')]
    if [(s[0],s[2]) for s in secrets]!=[('contract_a','ContractA'),('contract_b','ContractB')]:
        raise ValueError('Unexpected local test fixtures')
    bridges={};observers=[]
    commands=queue.Queue()
    def input_loop():
        for line in sys.stdin:
            try:commands.put(json.loads(line))
            except ValueError:commands.put({})
    threading.Thread(target=input_loop,daemon=True).start()
    try:
        for c,secret in zip(('a','b'),secrets):
            bridge=LocalBridge(roots[c],secret,lambda event,c=c:record(c,event))
            bridges[c]=bridge
            bridge.start_connect()
            deadline=time.monotonic()+40
            while True:
                state=bridge.status()
                if state['worldStartSent'] and state['authenticated']:
                    break
                if state.get('fault') or state.get('runtime_errors') or time.monotonic()>deadline:
                    raise RuntimeError('Owned local native authentication did not complete')
                time.sleep(.2)
            login=dict(pid=bridge.pid,state=state,at=datetime.now(timezone.utc).isoformat())
            login_path=ROOT/('reports/contracts-local/city-ui/group-map-fix/login-'+c+'.json')
            if login_path.exists():(directory/('previous-login-'+c+'.json')).write_bytes(login_path.read_bytes())
            login_path.write_text(json.dumps(login,indent=2)+'\n',encoding='utf-8')
            (directory/('login-'+c+'.json')).write_text(json.dumps(login,indent=2)+'\n',encoding='utf-8')
            # Authentication has completed before any packet metadata is observed.
            observer=bridge.session.create_script(OBSERVER)
            observer.on('message',lambda message,data,c=c:record(c,message['payload'] if message.get('type')=='send' else {'event':'observer_error','type':message.get('type')}))
            observer.load();observers.append(observer)
            print(json.dumps(dict(event='client_authenticated',copy=c,pid=bridge.pid)),flush=True)
        secrets.clear()
        pids={c:b.pid for c,b in bridges.items()}
        (directory/'clients.json').write_text(json.dumps(dict(pids=pids,loopback_only=True,hosted_connections=0),indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(event='ready',pids=pids,report=str(directory))),flush=True)
        deadline=time.monotonic()+args.seconds
        while time.monotonic()<deadline:
            if (directory/'stop-observer.request').exists():break
            try:command=commands.get(timeout=.25)
            except queue.Empty:continue
            if command.get('action')=='finish':break
        (directory/'final-auth-status.json').write_text(json.dumps({c:b.status() for c,b in bridges.items()},indent=2)+'\n',encoding='utf-8')
    finally:
        for bridge in bridges.values():bridge.release(cleanup=False)
        events.close()
    print(json.dumps(dict(event='observer_finished',clients_left_running=True)),flush=True)


if __name__=='__main__':main()
