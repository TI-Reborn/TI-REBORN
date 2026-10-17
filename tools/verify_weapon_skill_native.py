"""Native weapon-type skill selection and skill-dependent damage, isolated from UI."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EDI


def mapping_case(kind):
    u=emulator();table=DATA+0x1000;actor=DATA+0x5000;slots=DATA+0xc000
    put32(u,0xac637c,DATA);put32(u,DATA,table)
    u.mem_write(table+0x120,struct.pack('<H',kind))
    put32(u,0xac618c,slots);put32(u,slots,actor)
    for n in range(8):u.mem_write(actor+0x330+n*4,struct.pack('<f',10+n))
    def hook(uc,address,size,user):
        if address==0xa7b030:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA+0xd000);u.reg_write(UC_X86_REG_EDX,0)
    # Save x87 return using a real FSTP instruction at the return address.
    u.mem_write(STOP,b'\xd9\x1d'+struct.pack('<I',DATA+0xe000))
    u.emu_start(0xa7abfc,STOP+6,count=1000)
    result=struct.unpack('<f',u.mem_read(DATA+0xe000,4))[0]
    expected={0:0,1:0,2:10,3:11,4:14,5:13,6:12,7:15,8:0,9:17}[kind]
    assert result==expected,(kind,result)
    return dict(weapon_type=kind,effective_skill_offset=None if result==0 else hex(0x330+4*(int(result)-10)))


def damage_case(skill,raw=120):
    u=emulator();frame=STACK+0x7000;out=DATA+0x800
    u.mem_write(frame-0x14,struct.pack('<f',skill))
    u.mem_write(out,struct.pack('<f',raw));put32(u,frame+0x10,out+4)
    u.mem_write(out+4,struct.pack('<f',raw))
    u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EDI,out)
    u.emu_start(0xa7a826,0xa7a890,count=1000)
    values=struct.unpack('<ff',u.mem_read(out,8))
    from tio.weapon_proficiency import damage_endpoint
    expected=damage_endpoint(raw,skill)
    assert values==(expected,expected),(skill,raw,values,expected)
    return dict(skill=skill,multiplier=(67+skill)/120,raw=raw,native_damage=values)


if __name__=='__main__':
    report=dict(sha256=EXPECTED_SHA,method=__doc__,
        mapping=[mapping_case(i) for i in range(10)],
        damage=[damage_case(s) for s in (0,10,35,53,75,100,200)]+[damage_case(s,r) for s,r in ((35,50),(35,75),(35.25,55),(74.5,99))])
    (ROOT/'evidence/weapon_skill_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Native skill mapping10 and damage multiplier11 cases PASS')
