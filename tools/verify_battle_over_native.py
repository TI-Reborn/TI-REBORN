"""Execute original4C ordinary summary reader95e55e..95ea7d.

UI initialization/logging skipped; original numeric readers and stores run.
Includes per-soldier experience and skill deltas; no special-mode extension.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI
from tio.protocol.battle_over import encode_battle_over,SoldierExperience
from tio.weapon_proficiency import bits


def main():
    cases=[]
    for result in (0,1,2):
        u=emulator();packet=encode_battle_over(result,kills=3,losses=1,damage_dealt=275,damage_received=99,credits=1000 if result==1 else 0)
        u.mem_write(DATA,packet[1:]);cursor=DATA+0x1000;obj=DATA+0x2000
        put32(u,cursor,DATA);put32(u,0xac6200,obj);put32(u,0xac5d58,DATA+0x3000)
        u.reg_write(UC_X86_REG_EBP,STACK+0x7000);u.reg_write(UC_X86_REG_ESI,cursor)
        def hook(uc,a,size,user):
            if a==0x7660e4:return_from_stub(uc)
            elif a==0x66754c:
                uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
            elif a==0x95e747:uc.reg_write(UC_X86_REG_EIP,0x95e78b)
        u.hook_add(UC_HOOK_CODE,hook)
        u.emu_start(0x95e55e,0x95ea7d,count=2000)
        assert u.reg_read(UC_X86_REG_EIP)==0x95ea7d
        assert get32(u,cursor)-DATA==len(packet)-1
        assert u.mem_read(obj+8,1)[0]==result
        assert int.from_bytes(u.mem_read(obj+10,2),'little')==3
        assert int.from_bytes(u.mem_read(obj+12,2),'little')==1
        assert get32(u,obj+16)==275
        assert get32(u,obj+20)==99
        assert get32(u,obj+24)==(1000 if result==1 else 0)
        cases.append({'result':result,'packet_hex':packet.hex(),'consumed':len(packet)-1})
    for gain,xp,expected in ((400,1400,2),(10,1410,0),(10000,10000,4),(0,366016,0)):
        u=emulator();cursor=DATA+0x1000;obj=DATA+0x2000;actor=DATA+0x4000
        previous=tuple(bits(i+30) for i in range(7))
        profile=tuple(bits(50+i) for i in range(16))
        packet=encode_battle_over(1,soldiers=(SoldierExperience(17,gain,previous,profile),))
        u.mem_write(DATA,packet[1:]);put32(u,cursor,DATA)
        put32(u,0xac6200,obj);put32(u,0xac5d58,DATA+0x3000)
        put32(u,0xac618c,DATA+0x3100);put32(u,DATA+0x3100,actor)
        put32(u,actor+0x602c,xp)
        u.reg_write(UC_X86_REG_EBP,STACK+0x7000);u.reg_write(UC_X86_REG_ESI,cursor)
        def hook(uc,a,size,user):
            if a in (0x7660e4,0xa0f760):return_from_stub(uc)
            elif a==0x66754c:uc.reg_write(UC_X86_REG_EAX,1);return_from_stub(uc)
            elif a==0xa93f70:uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
            elif a==0x95e747:uc.reg_write(UC_X86_REG_EIP,0x95e78b)
            elif a==0x95e806:uc.reg_write(UC_X86_REG_EIP,0x95e83d)
        u.hook_add(UC_HOOK_CODE,hook)
        u.emu_start(0x95e55e,0x95ea7d,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==0x95ea7d
        assert get32(u,cursor)-DATA==len(packet)-1
        assert get32(u,actor+0x388)==gain
        assert u.mem_read(actor+0x38c,1)[0]==expected
        for i,offset in enumerate((0x310,0x358,0x314,0x35c,0x318,0x360,0x31c,0x364,0x320,0x368,0x324,0x36c,0,0,0x32c,0x374)):
            if offset:assert get32(u,actor+offset)==profile[i]
        for i,index in enumerate((0,1,4,3,2,5,7)):
            offset=(0x394,0x398,0x3a4,0x3a0,0x39c,0x3a8,0x3ac)[i]
            actual=struct.unpack('<f',u.mem_read(actor+offset,4))[0]
            assert actual==(50+index*2+1)-(30+i),(i,actual)
        cases.append(dict(gain=gain,xp=xp,level_up=expected,consumed=len(packet)-1))
    (ROOT/'evidence/battle_over_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original battle-over summary and experience reader:7 cases PASS')


if __name__=='__main__':main()
