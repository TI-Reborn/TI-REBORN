"""Extract door cells using the installed ti.exe TILE v4/v5 record readers.

Only stream I/O, allocation, initialization and render setup are isolated.
The original numeric/string readers and record field writes execute unchanged.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator


def read_doors(path):
    raw=path.read_bytes()
    if raw[:8]!=b'TI TILE\0' or raw[10] not in (4,5):
        raise ValueError('Expected original TILE v4/v5')
    count=struct.unpack_from('<H',raw,8)[0]
    if raw[10]==5 and struct.unpack_from('<I',raw,12)[0]>1:
        raise ValueError('Extended TILE header is not supported by this extractor')
    u=exe_emulator();stream=DATA;vt=DATA+0x100;read=DATA+0x200;obj=DATA+0x1000
    put32(u,stream,vt);put32(u,vt+12,read)
    put32(u,0x76e3d8,DATA+0x300);put32(u,DATA+0x300,stream)
    position=24+204
    doors=[]
    def hook(uc,a,size,user):
        nonlocal position
        if a==read:
            size=uc.reg_read(UC_X86_REG_ECX);target=uc.reg_read(UC_X86_REG_EDX)
            if position+size>len(raw):raise ValueError('Truncated TILE record')
            uc.mem_write(target,raw[position:position+size]);position+=size
            uc.reg_write(UC_X86_REG_EAX,size)
        elif a==0x40cc78:
            uc.mem_write(obj,bytes(0x720));uc.reg_write(UC_X86_REG_EAX,obj)
        elif a==0x6d7e20:pass
        elif a==0x6d7eb0:uc.reg_write(UC_X86_REG_EAX,1)
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    for i in range(count):
        put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
        u.reg_write(UC_X86_REG_EAX,stream);u.reg_write(UC_X86_REG_EDX,0)
        u.emu_start(0x749b30 if raw[10]==4 else 0x74a9d8,STOP,count=30000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        state=u.mem_read(obj+0x340,1)[0]
        if state:
            name=bytes(u.mem_read(obj+0x32+1,u.mem_read(obj+0x32,1)[0])).decode('ascii')
            doors.append(dict(x=struct.unpack('<i',u.mem_read(obj+4,4))[0],
                              y=struct.unpack('<i',u.mem_read(obj+8,4))[0],state=state,name=name))
    if position!=len(raw):raise ValueError('Unconsumed TILE data')
    return doors


if __name__=='__main__':
    base=Path(r'C:\Program Files (x86)\TIOnline\base\setting')
    for name in ('hangar.t','m_house01.t','village_house_02.t'):
        print(name,read_doors(next(base.rglob(name))))
