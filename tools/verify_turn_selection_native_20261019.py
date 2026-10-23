"""Run the exact compiled launcher adapter and native ti.exe selection code.

Camera/highlight rendering is isolated. The YourTurn branch, ownership/health
scan, native clear/select routine and subsequent selected-actor getter run.
"""
from verify_auth_native import *
from verify_battle_loaded_native import exe_emulator,EXE_SHA
from unicorn.x86_const import UC_X86_REG_EBX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EFLAGS
OUT=ROOT/'reports/turn-selection-equipment-20261019'

def run(rows,*,key=199,allocation=None):
    plan=json.loads((OUT/'launcher-turn-proof.json').read_text())
    u=exe_emulator();allocation=allocation or plan['allocation']
    if allocation!=plan['allocation']:raise ValueError('Use the compiled launcher allocation proof')
    u.mem_map(allocation,4096);u.mem_write(allocation,bytes.fromhex(plan['code']))
    assert bytes(u.mem_read(0x71da3d,5))==bytes.fromhex('e9c60f0000')
    u.mem_write(0x71da3d,bytes.fromhex(plan['hook']))
    for global_,value in ((0x76dfac,DATA+0x100),(0x76e068,DATA+0x104),
                          (0x76e430,DATA+0x1000),(0x76e17c,DATA+0x108),
                          (0x76dcf8,DATA+0x10c),(0x76dc08,DATA+0x110),
                          (0x76e314,DATA+0x114),(0x76dccc,DATA+0x118),
                          (0x76df04,DATA+0x11c),(0x76df10,DATA+0x120)):
        put32(u,global_,value)
    put32(u,DATA+0x100,7);put32(u,DATA+0x104,key)
    put32(u,DATA+0x108,DATA+0x200);put32(u,DATA+0x10c,38);put32(u,DATA+0x110,38)
    put32(u,DATA+0x114,1000)
    for index,row in enumerate(rows):
        if row is None:continue
        owner,hp,selected=row;actor=DATA+0x2000+index*0x500
        put32(u,DATA+0x1000+index*4,actor);put32(u,actor+0x64,owner)
        u.mem_write(actor+8,struct.pack('<H',hp^key));u.mem_write(actor+0x4d,bytes((selected,)))
        put32(u,actor+0x1bc,3+index);put32(u,actor+0x1c0,4)
    calls=[]
    def hook(uc,a,size,user):
        if a in (0x70be74,0x70627c):
            calls.append(hex(a));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    regs={UC_X86_REG_EBX:0x12345678,UC_X86_REG_ESI:0x23456789,UC_X86_REG_EDI:0x34567890,UC_X86_REG_EBP:0x456789ab}
    for reg,value in regs.items():u.reg_write(reg,value)
    sp=STACK+0x8000;u.reg_write(UC_X86_REG_ESP,sp)
    u.emu_start(0x71da27,0x71ea08,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==0x71ea08 and u.reg_read(UC_X86_REG_ESP)==sp
    for reg,value in regs.items():assert u.reg_read(reg)==value
    expected=next((i for i,r in enumerate(rows) if r is not None and r[0]==7 and r[1]>0),None)
    selected=[i for i,r in enumerate(rows) if r is not None and u.mem_read(DATA+0x2000+i*0x500+0x4d,1)[0]]
    assert selected==([expected] if expected is not None else [i for i,r in enumerate(rows) if r and r[2]])
    put32(u,sp,STOP);u.reg_write(UC_X86_REG_ESP,sp)
    u.emu_start(0x723f44,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    got=u.reg_read(UC_X86_REG_EAX)
    assert got==(0xffffffff if expected is None else expected)
    # The adapter changes no actor HP, AP, position or ownership.
    for i,r in enumerate(rows):
        if r is None:continue
        actor=DATA+0x2000+i*0x500
        assert get32(u,actor+0x64)==r[0] and (struct.unpack('<H',u.mem_read(actor+8,2))[0]^key)==r[1]
        assert (get32(u,actor+0x1bc),get32(u,actor+0x1c0))==(3+i,4)
    return dict(rows=rows,key=key,first_living_owned=expected,native_getter=got,render_calls=calls)

if __name__=='__main__':
    cases=[]
    for key in (0,199,255):
        for rows in ([],[None,(7,100,0)],[(8,100,1),(7,100,0),(7,100,0)],
                     [(7,0,0),(7,100,0),(8,100,1)],[(8,100,1),(7,0,0)],
                     [(7,100,0),(7,100,1)], [None]*30+[(7,100,0)]):
            cases.append(run(rows,key=key))
    (OUT/'native-turn-selection.json').write_text(json.dumps(dict(passed=True,exe_sha256=EXE_SHA,
        method=__doc__,cases=cases,stack_and_saved_registers_preserved=True,no_gameplay_packets=True),indent=2))
    print('Compiled launcher turn adapter:21 native first/dead/foreign/empty/last-slot cases PASS')
