"""Execute original XP table lookup, NextLvl_Exp and4E XP model write.

No level function is stubbed. UI work after the4E model write is excluded.
"""
from verify_auth_native import *
from tio.level_progression import FLOORS,MAX_XP,level_for_xp


def main():
    u=emulator()
    table=get32(u,0xac54e8)
    assert table==0xac4fa0
    values=struct.unpack('<22I',u.mem_read(table,88))
    assert values[0]==0 and tuple(values[1:21])==FLOORS and values[21]==MAX_XP+1
    cases=[]
    for xp in sorted({0,MAX_XP,MAX_XP+1,*FLOORS,*(v-1 for v in FLOORS[1:])}):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,xp);u.emu_start(0x9b336c,STOP,count=1000)
        level=u.reg_read(UC_X86_REG_EAX)&255
        assert level==(0 if xp>MAX_XP else level_for_xp(xp))
        cases.append(dict(xp=xp,level=level))
    actor=DATA+0x2000
    for level in range(1,21):
        put32(u,actor+0x5ffc,level)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_EAX,actor);u.emu_start(0xa853f8,STOP,count=100)
        assert u.reg_read(UC_X86_REG_EAX)==values[level+1]
    u=emulator();actor=DATA+0x2000;parent=DATA+0x1000
    put32(u,0xac618c,DATA+0x100);put32(u,DATA+0x100,actor)
    u.mem_write(actor+0x41,b'\x01')
    put32(u,parent-4,DATA);put32(u,STACK+0x8004,parent)
    reached=[]
    def hook(uc,a,size,user):
        if a in (0xa93f70,0x6552c0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif a==0x8c77d5:reached.append(True);uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,2);u.reg_write(UC_X86_REG_ECX,7355)
    u.emu_start(0x8c7320,STOP,count=1000)
    assert reached and get32(u,actor+0x602c)==7355
    (ROOT/'evidence/level_progression_native.json').write_text(json.dumps(dict(
        sha256=EXPECTED_SHA,method=__doc__,table_address=hex(table),table=values,
        boundaries=cases,next_level_thresholds=20,xp_status_attribute=2),indent=2)+'\n',encoding='utf-8')
    print(f'Original XP lookup:{len(cases)} boundaries,20 next thresholds,4E model write PASS')


if __name__=='__main__':main()
