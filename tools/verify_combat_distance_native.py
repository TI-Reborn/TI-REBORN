"""Execute original a8907c including native square root and integer rounding."""
from verify_auth_native import *
from tio.combat_distance import combat_distance


if __name__=='__main__':
    rows=[]
    for end in ((1,0),(1,1),(2,0),(2,1),(2,2),(5,1),(7,7)):
        u=emulator();sp=u.reg_read(UC_X86_REG_ESP)
        for offset,value in zip((4,8,12,16),(end[1],end[0],0,0)):
            u.mem_write(sp+offset,struct.pack('<f',value))
        u.emu_start(0xa8907c,STOP,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        value=u.reg_read(UC_X86_REG_EAX)&0xffff
        assert value==combat_distance((0,0),end),(end,value)
        rows.append({'delta':end,'distance':value})
    (ROOT/'evidence/combat_distance_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'cases':rows},indent=2)+'\n')
    print('Native combat distance:7 cases PASS')
