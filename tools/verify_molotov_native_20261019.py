"""Real Unicode/cache loader and native quad/UV pipeline, GPU/file decode isolated."""
import json,struct,sys
from pathlib import Path
import pefile
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_throwable_runtime_fix_20261019 import plan
from tools.verify_ui_hd_icons_native import NativeLoaderFixture,put,get,DATA,close
from deploy import client_throwable_effects as fx

class Fixture(NativeLoaderFixture):
    def texture(self,w,h):
        texture=super().texture(w,h);put(self.u,texture+4,0);return texture

def verify():
    root=ROOT/'work/groza-20261019/gui/game-a'
    source=bytearray((root/'silver.dll').read_bytes());pe=pefile.PE(data=source)
    for p in plan()['patches']:
        at=pe.get_offset_from_rva(p['rva']);before=bytes.fromhex(p['before']);after=bytes.fromhex(p['after'])
        assert source[at:at+len(before)]==before;source[at:at+len(after)]=after
    results=[]
    for base,ti_base in ((0x10000000,0x400000),(0x17000000,0x600000)):
        f=Fixture(bytes(source),(root/'ti.exe').read_bytes(),base,ti_base)
        put(f.u,f.va(0xacc424),f.tva(0x71bd8c))
        for name,_,_,_ in fx.RESOURCES:
            f.asset_dimensions['base\\'+name]=Image.open(root/'base'/name.replace('\\','/')).size
        f.run(fx.LOAD)
        assert len(f.loads)==4
        for i,(name,w,h,count) in enumerate(fx.RESOURCES):
            row=f.va(0x400000+fx.ROWS+i*64)
            assert f.loads[i]['path']==name and f.loads[i]['tile']==[w,h],f.loads
            packed=bytes(f.u.mem_read(row,12));texture,aw,ah,tw,th=struct.unpack('<IHHHH',packed)
            assert texture and (tw,th)==(w,h),(name,packed.hex())
            columns=aw//tw
            for frame in range(count):
                start=len(f.quads)
                f.run(0x4f2910,row,200,300,args=(0,0xffffffff,frame,64,32))
                assert len(f.quads)==start+1
                quad=f.quads[-1];assert quad['texture']==texture
                expected=(((frame%columns)*w+0.5)/get(f.u,texture+0x14),((frame//columns)*h+0.5)/get(f.u,texture+0x18))
                close(quad['vertices'][0][5],expected[0]);close(quad['vertices'][0][6],expected[1])
                assert all(v[4]==0xffffffff for v in quad['vertices'])
                assert bytes(f.u.mem_read(row,12))==packed
        f.run(fx.LOAD);assert len(f.loads)==4,'Resources must be cached'
        results.append(dict(base=hex(base),ti_base=hex(ti_base),loads=f.loads,quads=len(f.quads),actual_native_loader=sorted(f.loader_executed),native_render=sorted(f.executed)))
    out=dict(passed=True,cases=results,fire_frames=32,texture_unicode=True,frame_geometry=True,graphical_clients=False)
    (ROOT/'reports/molotov-fix-20261019/native-loader-render.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))

if __name__=='__main__':verify()
