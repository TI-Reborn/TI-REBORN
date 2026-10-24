"""Read-only instrumentation of our owned graphical QA process."""
import frida,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'reports/molotov-fix-20261019'
client=json.loads((out/'gui-client.json').read_text());root=Path(client['root'])
assert (root/'.tio-owned-qa').is_file()
session=frida.attach(client['pid']);script=session.create_script('''
if(Process.mainModule.path.toLowerCase()!==PATH.toLowerCase())throw Error('Own QA client only');
const b=Process.getModuleByName('silver.dll').base,at=v=>b.add(v-0x400000),fire=at(0xc7a080);
let frames=new Set(),draws=0,loads=[],animations=[];
Interceptor.attach(at(0x4f2cb4),{onEnter(){try{const name=this.context.eax.readUtf16String();if(name.includes('tio-effects'))loads.push({name,width:this.context.edx.toUInt32(),height:this.context.ecx.toUInt32()});}catch(e){}}});
Interceptor.attach(at(0x4f2910),{onEnter(){if(this.context.eax.equals(fire)){draws++;frames.add(this.context.esp.add(12).readU32());}}});
Interceptor.attach(at(0x68a7ec),{onEnter(){try{let name=this.context.edx.readUtf16String();if(/grenade|throw|molotov|burn/i.test(name))animations.push(name);}catch(e){}}});
rpc.exports={state(){
 let cells=[],n=at(0xc18bf8).readU32(),camera=[at(0xac61b0).readPointer().readS32(),at(0xac6068).readPointer().readS32()];
 for(let i=0;i<Math.min(n,4096);i++){let p=at(0xc18c00).add(i*3);cells.push([p.readU8(),p.add(1).readU8(),p.add(2).readU8()]);}
 let actors=[],table=at(0xac618c).readPointer();for(let i=0;i<31;i++){let p=table.add(i*4).readPointer();if(!p.isNull())actors.push({id:p.add(0x28).readU32(),hp:p.add(0x6006).readU16(),x:p.add(0x603c).readU32(),y:p.add(0x6040).readU32()});}
 let record=[fire.readU32(),fire.add(4).readU16(),fire.add(6).readU16(),fire.add(8).readU16(),fire.add(10).readU16()];
 let texture=fire.readPointer(),textureSize=texture.isNull()?null:[texture.add(0x14).readU32(),texture.add(0x18).readU32()];
 return {cells,actors,camera,record,textureSize,frames:[...frames].sort((a,b)=>a-b),draws,loads,animations};
}};
'''.replace('PATH',json.dumps(str(root/'ti.exe'))))
script.load();print(json.dumps(dict(read_only=True,observing=True)),flush=True)
try:
    for line in sys.stdin:
        command=line.strip()
        if command=='stop':break
        state=script.exports_sync.state();(out/('gui-'+command+'.json')).write_text(json.dumps(state,indent=2));print(json.dumps(state),flush=True)
finally:session.detach()
