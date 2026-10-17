"""Read-only snapshot of native actor coordinates and sight/collision cells."""
import argparse,json
from pathlib import Path
import frida

SCRIPT=r'''
const exe=Process.getModuleByName('ti.exe').base;
const at=a=>exe.add(a-0x400000);
const grid=at(0x76e5f4).readPointer().readPointer();
const width=grid.add(0x24).readU16(),height=grid.add(0x26).readU16();
if(width>128 || height>128)throw Error('Unexpected grid size');
const cells=grid.add(12).readPointer(),actors=[];
const silver=Process.getModuleByName('silver.dll').base;
const table=silver.add(0xac618c-0x400000).readPointer();
for(let i=0;i<31;i++){
  const p=table.add(i*4).readPointer();if(p.isNull())continue;
  actors.push({id:p.add(0x28).readU32(),owner:p.add(0x2c).readU32(),
    hp:p.add(0x6006).readU16(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32()});
}
const tiles=[];
for(let y=0;y<height;y++)for(let x=0;x<width;x++)
  tiles.push(cells.add(x*4).readPointer().add(y*14).readU8());
send({width,height,tiles,actors,v2:at(0x76dbf0).readPointer().readU8()});
'''

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pid',type=int)
    parser.add_argument('--output',type=Path,default=Path('evidence/live_shot_grid.json'))
    args=parser.parse_args();session=frida.attach(args.pid)
    try:
        script=session.create_script(SCRIPT)
        def receive(message,data):
            if message['type']!='send':raise RuntimeError(message)
            args.output.write_text(json.dumps(message['payload'],indent=2)+'\n')
            print({k:v for k,v in message['payload'].items() if k!='tiles'})
        script.on('message',receive);script.load()
    finally:session.detach()
