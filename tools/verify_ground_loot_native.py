"""Execute original empty-ground UI branch, ground44/45 scene reader and bag renderer.
UI, object lookup, texture draw and sound are isolated; no graphical-client claim.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI,UC_X86_REG_EBX
from verify_battle_loaded_native import exe_emulator,EXE_SHA


def ground_ui():
    u=emulator();actor=DATA+0x4000;cell=DATA+0x2000;frame=STACK+0x7000
    put32(u,DATA,actor);put32(u,actor+0x603c,18);put32(u,actor+0x6040,11)
    put32(u,actor+0x6c,DATA+0x3000)
    called=[]
    def hook(uc,a,size,user):
        if a==0x9db9a4:uc.reg_write(UC_X86_REG_EAX,cell)
        elif a in (0x6675e0,0x9b122c):pass
        elif a==0x95e114:raise AssertionError('Empty ground unexpectedly requested46')
        elif a==0x9b1440:
            assert uc.reg_read(UC_X86_REG_EDX)==DATA+0x3000
            assert uc.reg_read(UC_X86_REG_ECX)==0
            called.append('local two-panel inventory without46');uc.emu_stop();return
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_ESI,DATA);u.reg_write(UC_X86_REG_EBX,0);u.reg_write(UC_X86_REG_EBP,frame)
    u.emu_start(0x9b7fc5,STOP,count=1000)
    assert called
    u=emulator();u.reg_write(UC_X86_REG_EBX,DATA)
    u.emu_start(0x9dc861,0x9dc885,count=100)
    assert bytes(u.mem_read(DATA+8,3))==bytes((1,2,2))
    return dict(empty_ground=called[0],open_ap=1,drop_ap=2)


def scene(opcode):
    u=exe_emulator();record=DATA+0x100
    payload=bytes((18,11,0,0)) if opcode==0x44 else bytes((18,11))
    u.mem_write(DATA,payload);put32(u,record,opcode);put32(u,record+12,DATA)
    put32(u,0x76e5f4,DATA+0x3000);put32(u,DATA+0x3000,DATA+0x3100)
    put32(u,DATA+0x310c,DATA+0x3200);put32(u,DATA+0x3200+18*4,DATA+0x4000)
    u.mem_write(DATA+0x4000+11*14+9,bytes((1,)))
    consumed=[]
    def hook(uc,a,size,user):
        if a==0x6f607c:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-0x10)-DATA);uc.emu_stop();return
        if a==0x72da00:uc.reg_write(UC_X86_REG_EAX,1)
        elif a==0x72dc90:pass
        else:return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x6f57d0,STOP,count=10000)
    assert consumed==[len(payload)],consumed
    flag=u.mem_read(DATA+0x4000+11*14+9,1)[0]
    assert flag==int(opcode==0x44)
    return dict(opcode=hex(opcode),consumed=consumed[0],cell_flag=flag)


def renderer():
    u=exe_emulator();frame=STACK+0x7000;outer=STACK+0x7100
    u.mem_write(frame-4,struct.pack('<HH',11,18));put32(u,frame+8,outer)
    put32(u,0x76e2f4,DATA+0x5000);put32(u,DATA+0x5000,0x12345678)
    # Original branch reads grid flag;1 selects ordinary rucksack,2 Santa sack.
    u.mem_write(DATA+11*14+9,bytes((1,)))
    seen=[]
    def hook(uc,a,size,user):
        if a==0x7408bc:
            seen.append(uc.reg_read(UC_X86_REG_EAX));uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EBP,frame);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x730aa8,STOP,count=1000)
    assert seen==[0x12345678],seen
    return dict(grid_flag=1,texture='gfx/rucksack.png',renderer='730AA8..730B12',texture_load='7432B4..7432D0')


if __name__=='__main__':
    from verify_battle_loot_native import container,consumer
    from tio.protocol.item_list import ItemRecord
    upgraded=ItemRecord(123,301,bytes(2),1,0,0,(100,200,300),bytes((3,0,0,0)),None,bytes((20,0,0)))
    cases=[ground_ui(),scene(0x44),scene(0x45),renderer(),container((upgraded,)),consumer((upgraded,))]
    (ROOT/'evidence/ground_loot_native.json').write_text(json.dumps(dict(method=__doc__,silver_sha256=EXPECTED_SHA,exe_sha256=EXE_SHA,cases=cases),indent=2)+'\n')
    print('Original ground UI, AP settings,44/45 scene reader and backpack renderer and upgraded loot:6 PASS')

