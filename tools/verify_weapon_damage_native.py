"""Original XML patk stores and base damage interval; no simulated numeric math."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI
from tio.weapons import WeaponCatalog


def run(base,random):
    u=emulator(); frame=STACK+0x7000; table=DATA+0x1000; closure=DATA
    put32(u,closure+12,0);put32(u,0xac637c,DATA+0x9000);put32(u,DATA+0x9000,table)
    # Real shortstring equality and x87 rounding; upstream XML values supplied.
    for operation,value,offset in (('set',base,0x132),('add',random,0x134)):
        u.mem_write(frame-0x3f0,bytes((len(operation),))+operation.encode())
        u.mem_write(frame-0x2f0,b'\x04patk')
        u.mem_write(frame-0x148,struct.pack('<f',value))
        u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EBX,closure)
        u.emu_start(0xa72752,0xa72c22,count=2000)
        assert u.reg_read(UC_X86_REG_EIP)==0xa72c22
        assert int.from_bytes(u.mem_read(table+offset,2),'little')==value
    put32(u,frame+0x10,DATA+0xa004)
    u.reg_write(UC_X86_REG_EAX,0);u.reg_write(UC_X86_REG_EDI,DATA+0xa000)
    u.emu_start(0xa7a4de,0xa7a525,count=100)
    interval=struct.unpack('<ff',u.mem_read(DATA+0xa000,8))
    assert interval==(base,base+random),interval
    return interval


if __name__=='__main__':
    cases=[dict(id=w.template_id,base=w.damage_base,random=w.damage_random,
                interval=run(w.damage_base,w.damage_random)) for w in WeaponCatalog().weapons.values()]
    (ROOT/'evidence/weapon_damage_native.json').write_text(json.dumps(dict(
        sha256=EXPECTED_SHA,method=__doc__,bindings='for/set patk ->132; for/add patk ->134; a7a4de ->base/base+random',cases=cases),indent=2))
    print(f'Original weapon damage stores and interval: {len(cases)} cases PASS')
