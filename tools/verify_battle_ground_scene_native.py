"""ti.exe717e1c ground numeric reads and both scene-grid layers.

Resource/scene allocation and events isolated; stop before scene loading7175ac.
Zero width probe stops on its first erroneous cell read, before buffer overrun.
"""
from verify_battle_loaded_native import exe_emulator, EXE_SHA
from verify_auth_native import *


def run(width,height,fog_mode=1):
    u=exe_emulator();grid=DATA+0x4000
    count=width*height
    first=bytes(i%100 for i in range(count))
    second=bytes(100+i%100 for i in range(count))
    body=bytes((fog_mode,width,height))+first+b'\0\0'+second
    u.mem_write(DATA,body)
    for index,address in enumerate((0x76dc8c,0x76e330,0x76e5f4)):
        put32(u,address,DATA+0x1000+index*0x100)
    put32(u,DATA+0x1200,DATA+0x1300)
    put32(u,DATA+0x130c,DATA+0x1400)
    for x in range(max(1,width)):
        put32(u,DATA+0x1400+x*4,grid+x*0x400)
    result={'width':width,'height':height,'packet_hex':(b'\x35'+body).hex()}
    def hook(uc,address,size,user):
        if address==0x6693c4:
            sp=uc.reg_read(UC_X86_REG_ESP)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address in (0x43a480,0x7225a8,0x43a7dc,0x726798,0x726f94):
            return_from_stub(uc)
        elif address==0x717f5b and width==0:
            result['zero_width_enters_cell_loop']=True
            uc.emu_stop()
        elif address==0x718081:
            result['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA)
    u.reg_write(UC_X86_REG_EDX,len(body))
    u.emu_start(0x717e1c,STOP,count=200000)
    if width==0:
        assert result.get('zero_width_enters_cell_loop')
        return result
    assert result['consumed']==len(body)
    for name,offset,expected in (('first_layer',8,list(first)),
                                 ('second_layer',0,list(second))):
        result[name]=[u.mem_read(grid+x*0x400+y*14+offset,1)[0]
                      for y in range(height) for x in range(width)]
        assert result[name]==expected
    result['persistent_fog']=u.mem_read(DATA+0x1106,1)[0]
    assert list(u.mem_read(DATA+0x1104,3))==[width,height,int(fog_mode==1)]
    return result


if __name__=='__main__':
    result={'method':__doc__,'exe_sha256':EXE_SHA,
            'cases':[run(1,1),run(2,3),run(3,2),run(38,38),run(0,1)]}
    (ROOT/'evidence/battle_ground_scene_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original scene ground:4 cases including 38x38 +zero-width hazard confirmed')
