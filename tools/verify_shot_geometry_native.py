"""Compare server sight with original ti.exe CanTraceCells and CanTrace.

Supplies tile arrays and map dimensions; ray and intersection code is unstubbed.
The live client uses legacy tracing (76DBF0=0); V2 is not claimed recovered.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from unicorn.x86_const import UC_X86_REG_FPCW
from tio.shot_geometry import clear_shot
import random


class NativeSight:
    def __init__(self):
        self.u=exe_emulator();u=self.u;self.grid=0x5000000
        u.mem_map(self.grid,0x20000)
        put32(u,DATA+12,self.grid)
        for index,address in enumerate((0x76dbf0,0x76dcf8,0x76dc08)):
            put32(u,address,DATA+0x100+index*4)
        put32(u,DATA+0x100,0)
        u.reg_write(UC_X86_REG_FPCW,0x1332)

    def load(self,width,height,tiles):
        u=self.u;put32(u,DATA+0x104,width);put32(u,DATA+0x108,height)
        for x in range(width):
            column=self.grid+0x1000+x*height*14;put32(u,self.grid+4*x,column)
            data=bytearray(height*14)
            for y in range(height):data[y*14]=tiles[y*width+x]
            u.mem_write(column,bytes(data))

    def trace(self,start,end):
        u=self.u;sp=STACK+0x8000
        put32(u,sp,STOP);put32(u,sp+4,end[1]);put32(u,sp+8,end[0])
        u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_EAX,DATA)
        u.reg_write(UC_X86_REG_EDX,start[0]);u.reg_write(UC_X86_REG_ECX,start[1])
        u.emu_start(0x6e1c88,STOP,count=1000000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        return bool(u.reg_read(UC_X86_REG_EAX)&255)


if __name__=='__main__':
    native=NativeSight();cases=[];rng=random.Random(19)
    for kind in (0,1,2,3,4):
        tiles=[0]*64;tiles[3*8+3]=kind;native.load(8,8,tiles)
        result=native.trace((1,3),(5,3))
        assert result==(kind!=3)
        cases.append(dict(tile=kind,clear=result))
    maps=json.loads((ROOT/'config/mine_maps.json').read_text());count=0
    for source in maps:
        w,h=source['width'],source['height'];tiles=source['tiles'];native.load(w,h,tiles)
        opaque=frozenset((x,y) for y in range(h) for x in range(w) if tiles[y*w+x]==3)
        walkable=[(x,y) for y in range(h) for x in range(w) if tiles[y*w+x]<2]
        for _ in range(40):
            a=rng.choice(walkable)
            near=[p for p in walkable if 0<(a[0]-p[0])**2+(a[1]-p[1])**2<=18**2]
            b=rng.choice(near)
            expected=native.trace(a,b);actual=clear_shot(a,b,opaque)
            assert actual==expected,(source['file'],a,b,actual,expected)
            count+=1
    (ROOT/'evidence/shot_geometry_native.json').write_text(json.dumps(dict(
        method=__doc__,sha256=EXE_SHA,tile_cases=cases,maps=len(maps),rays=count,status='PASS'),indent=2)+'\n')
    print('Original sight geometry: five tile classes and',count,'rays across all 20 mines PASS')
