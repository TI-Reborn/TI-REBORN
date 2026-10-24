"""Capture the owned QA client's actual D3D9 back buffer, without desktop input."""
from pathlib import Path
import argparse,json,threading
import frida

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/personal-gui-all-20261020'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--name',default='native-reservation')
    args=parser.parse_args()
    assert args.name.replace('-','').isalnum()
    info=json.loads((OUT/'gui-client.json').read_text())
    root=Path(info['root']);assert root==(ROOT/'work/personal-gui-all-20261020/gui/game-a') and (root/'.tio-owned-qa').is_file()
    target=OUT/(args.name+'.png')
    session=frida.attach(info['pid']);event=threading.Event();results=[]
    config={'path':str(root/'ti.exe'),'output':str(target)}
    script=session.create_script('''
const config=CONFIG;
if(Process.mainModule.path.toLowerCase()!==config.path.toLowerCase())throw Error('Own QA only');
const renderer=ptr(0x76de0c).readPointer().readPointer(),device=renderer.add(0x44).readPointer();
function com(p,index,type,args){return new NativeFunction(p.readPointer().add(index*4).readPointer(),type,args,'stdcall');}
const output=Memory.allocUtf16String(config.output),surface=Memory.alloc(4);
const save=new NativeFunction(Process.getModuleByName('d3dx9_26.dll').getExportByName('D3DXSaveSurfaceToFileW'),
 'int',['pointer','int','pointer','pointer','pointer'],'stdcall');
let captured=false;
Interceptor.attach(device.readPointer().add(17*4).readPointer(),{onEnter(args){
 if(captured||!args[0].equals(device))return;captured=true;
 const hr=com(device,18,'int',['pointer','uint','uint','int','pointer'])(device,0,0,0,surface);
 if(hr<0){send({passed:false,getBackBuffer:hr});return;}
 const target=surface.readPointer();
 const saved=save(output,3,target,ptr(0),ptr(0));com(target,2,'uint',['pointer'])(target);
 const silver=Process.getModuleByName('silver.dll').base;
 const chatColors=[0x602b03,0x602b1e,0x602bab].map(r=>silver.add(r+1).readU32().toString(16));
 send({passed:saved>=0,saveHRESULT:saved,chatColors,source:'real native D3D9 back buffer before Present'});
}});
'''.replace('CONFIG',json.dumps(config)))
    def receive(message,data):
        if message['type']=='send':results.append(message['payload']);event.set()
        elif message['type']=='error':results.append({'passed':False,'error':message.get('description')});event.set()
    script.on('message',receive);script.load()
    try:
        assert event.wait(15),'Native frame was not presented'
        assert results[0]['passed'],results
        assert target.exists()
        (OUT/(args.name+'.json')).write_text(json.dumps(results[0],indent=2),encoding='utf-8')
        print(json.dumps(results[0]))
    finally:session.detach()


if __name__=='__main__':main()
