"""Prepare/launch a separate current published native client for Training QA."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request
import shutil

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import prepare_hosted_graphical_qa as prepare
from tools import hosted_graphical_qa_bridge as auth

WORK=ROOT/'work/training-base-20261018/gui'
REPORT=ROOT/'reports/training-base-20261018'
PRIVATE=ROOT/'.secrets/training-base-20261018.json'
SILVER='54dfaf7c7ede79684aad764540f9847c08710d26433fb11ccd02f73db441f8f0'


def guards(root):
    import pefile
    root=Path(root)
    assert root.resolve()==(WORK/'game-a').resolve() and (root/prepare.MARKER).is_file()
    for name,expected in {**auth.HASHES,'silver.dll':SILVER}.items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
    rows=[]
    with pefile.PE(str(root/'silver.dll')) as pe:
        for name,va,size,expected in auth.SPANS:
            raw=pe.get_data(va-0x400000,size)
            assert hashlib.sha256(raw).hexdigest()==expected,name
            offsets=[entry.rva-(va-0x400000) for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                     if entry.type==3 and 0<=entry.rva-(va-0x400000)<=8]
            rows.append(dict(name=name,va=va,entry12=raw[:12].hex(),entry_relocations=offsets))
    return rows


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('prepare','launch'));args=parser.parse_args()
    prepare.QA_BASE=WORK
    prepare.accepted_native_hashes=lambda name:{SILVER if name=='silver.dll' else auth.HASHES[name]}
    prepare.static_guards=guards;auth.static_guards=guards
    if args.mode=='prepare':
        value=prepare.prepare(('a',));(REPORT/'gui-preparation.json').write_text(json.dumps(value,indent=2));return
    data=json.loads(PRIVATE.read_text());root=WORK/'game-a'
    helper=WORK/'bin/TioQaClient.exe';helper.parent.mkdir(exist_ok=True)
    for name in ('TioQaClient.exe','TioQaClient.dll','TioQaClient.deps.json','TioQaClient.runtimeconfig.json'):
        shutil.copyfile(ROOT/'reports/arena-surroundings-implementation/client-qa/bin'/name,helper.parent/name)
    bridge=auth.HostedGraphicalQaBridge(root,dict(login=data['names'][0],password=data['passwords'][0],fresh_qa=True),auto_select=True,helper=helper)
    print(json.dumps(dict(pid=bridge.pid,started=True,own_qa=True)),flush=True)
    try:
        for line in sys.stdin:
            command=line.strip()
            if command=='status':print(json.dumps(bridge.status()),flush=True)
            elif command=='connect':print(json.dumps(bridge.start_connect()),flush=True)
            elif command in ('trace','builders'):
                assert bridge.status()['authenticated']
                trace=bridge.session.create_script('''
const m=Process.getModuleByName('orange.dll');
const entry=m.getExportByName('AAaAA');
const target=entry.add(5).add(entry.add(1).readS32());
const unpacked=target.sub(0x16a0);
const s=Process.getModuleByName('silver.dll').base;
for(const va of [0x792a50,0x63916c,0x639198,0x639220])
 Interceptor.attach(s.add(va-0x400000),{onEnter(){send({event:'native_training_callback',va:va.toString(16)});}});
Interceptor.attach(unpacked.add(0x1f70),{onEnter(a){
 const n=a[1].toUInt32()&65535,p=a[0];
 if(n>0&&n<=128&&[0x1f,0xb0,0x79].includes(p.readU8()))
  send({event:'own_native_training_request',hex:Array.from(new Uint8Array(p.readByteArray(n))).map(v=>v.toString(16).padStart(2,'0')).join('')});
}});
rpc.exports={state(){const t=s.add(0xac5d58-0x400000).readPointer().readU32();
const zone=s.add(0xac63bc-0x400000).readPointer().readPointer().add((t-1)*4).readPointer();
const a=zone.add(0x358).readPointer().readPointer();return {town:t,training:zone.add(0x23e).readU8(),v4:zone.add(0x255).readU8(),mode:s.add(0xac6284-0x400000).readPointer().readU8(),phase:a.add(0xc).readU32()};}};
''')
                def event(message,_):
                    if message.get('type')=='send':
                        row=message['payload']
                        with (REPORT/'gui-native-requests.jsonl').open('a') as out:out.write(json.dumps(row)+'\n')
                        print(json.dumps(row),flush=True)
                trace.on('message',event);trace.load();print(json.dumps(dict(trace_enabled=True,state=trace.exports_sync.state())),flush=True)
            elif command=='stop':break
    finally:bridge.release(cleanup=True)


if __name__=='__main__':main()
