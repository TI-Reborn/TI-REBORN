"""Extract door cells using the installed ti.exe TILE v2/v4/v5 record readers.

Stream I/O, allocation, initialization, managed ASCII conversion and render setup are isolated.
The original numeric/string readers and record field writes execute unchanged.
"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator


def read_doors(path):
    raw=path.read_bytes()
    if raw[:8]!=b'TI TILE\0' or raw[10] not in (2,4,5):
        raise ValueError('Expected original TILE v2/v4/v5')
    count=struct.unpack_from('<H',raw,8)[0]
    u=exe_emulator();stream=DATA;vt=DATA+0x100;read=DATA+0x200;obj=DATA+0x1000
    put32(u,stream,vt);put32(u,vt+12,read)
    put32(u,0x76e3d8,DATA+0x300);put32(u,DATA+0x300,stream)
    # Validated against complete record consumption in the 19 reviewed models.
    # Legacy2 starts immediately after24;4/5 carry204 bytes plus the extra words.
    position=24 if raw[10]==2 else 24+204+4*struct.unpack_from('<I',raw,12)[0]
    doors=[]
    from collections import deque
    trace=deque(maxlen=16)
    def hook(uc,a,size,user):
        nonlocal position
        trace.append(hex(a))
        if a==read:
            size=uc.reg_read(UC_X86_REG_ECX);target=uc.reg_read(UC_X86_REG_EDX)
            if position+size>len(raw):raise ValueError('Truncated TILE record')
            uc.mem_write(target,raw[position:position+size]);position+=size
            uc.reg_write(UC_X86_REG_EAX,size)
        elif a==0x40cc78:
            uc.mem_write(obj,bytes(0x720));uc.reg_write(UC_X86_REG_EAX,obj)
        elif a==0x67e534:
            pointer=DATA+0x9000;source=uc.reg_read(UC_X86_REG_EAX);length=uc.mem_read(source,1)[0]
            put32(uc,pointer-4,length);put32(uc,pointer-8,2)
            uc.mem_write(pointer,bytes(uc.mem_read(source+1,length))+b'\0');put32(uc,uc.reg_read(UC_X86_REG_ECX),pointer)
        elif a==0x40beac:
            source=uc.reg_read(UC_X86_REG_EDX);length=min(get32(uc,source-4),uc.reg_read(UC_X86_REG_ECX))
            uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes((length,))+bytes(uc.mem_read(source,length)))
        elif a==0x40afb4:pass
        elif a==0x6d7e20:pass
        elif a==0x6d7eb0:uc.reg_write(UC_X86_REG_EAX,1)
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    for i in range(count):
        put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
        u.reg_write(UC_X86_REG_EAX,stream);u.reg_write(UC_X86_REG_EDX,0)
        try:u.emu_start({2:0x74a4b4,4:0x749b30,5:0x74a9d8}[raw[10]],STOP,count=30000)
        except Exception as e:raise ValueError((position,list(trace))) from e
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
