"""Exact launcher recon payload and original skill-use consumer, UI isolated."""
import os
os.environ['TIO_DOOR_REPORT']=str(__import__('pathlib').Path(__file__).resolve().parents[1]/'reports/scope-square-20261019')
from verify_launcher_doors_native import Probe,REPORT
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from tio.protocol.ability_status import AbilityStatus,encode_ability_status


def recon():
    p=Probe();u=p.u
    put32(u,p.base+0xf00,DATA+0xb000);put32(u,p.base+0xf04,DATA+0xb004)
    cells=[(x,y,3) for x in range(4,7) for y in range(4,7)]
    p.cell(5,5,3)  # A blocked surface still receives its recon visibility byte.
    def snapshot(rows):
        put32(u,DATA+0xb000,len(rows));u.mem_write(DATA+0xb004,bytes(v for row in rows for v in row))
    snapshot(cells);p.refresh()
    assert all(p.seen(x,y)==1 for x,y,_ in cells)
    assert p.cell(5,5)==3
    assert p.seen(3,4)==p.seen(7,7)==0
    # Every stock fog recomputation must retain the authoritative recon cross.
    p.refresh();assert all(p.seen(x,y)==1 for x,y,_ in cells)
    # Empty/invalid coordinates and other visual kinds cannot reveal terrain.
    for rows in ([],[(255,255,3),(8,5,3),(5,8,3)],[(5,5,k) for k in (1,2,4,5)]):
        snapshot(rows);p.refresh();assert all(p.seen(x,y)==0 for x,y,_ in cells)
    # F7 tail is entered inside PUSHFD/PUSHAD. It rebuilds stock fog even on
    # an empty snapshot, restores flags/registers, and returns handled=1.
    snapshot(cells);sp=STACK+0x8000
    saved=[0x11,0x22,0x33,sp+36,0x44,0x55,0x66,0x77]
    u.mem_write(sp,struct.pack('<10I',*saved,0x246,STOP));u.reg_write(UC_X86_REG_ESP,sp)
    u.emu_start(p.base+0x800,STOP,count=100000)
    assert u.reg_read(UC_X86_REG_ESP)==sp+40 and u.reg_read(UC_X86_REG_EAX)==1
    assert u.reg_read(UC_X86_REG_EFLAGS)&0xfff==0x246
    assert all(p.seen(x,y)==1 for x,y,_ in cells)
    snapshot([]);u.mem_write(sp,struct.pack('<10I',*saved,0x246,STOP));u.reg_write(UC_X86_REG_ESP,sp)
    u.emu_start(p.base+0x800,STOP,count=100000)
    assert all(p.seen(x,y)==0 for x,y,_ in cells)
    return dict(square=cells,diagonals_revealed=True,outside_hidden=True,empty_refogs=True,other_effects_do_not_reveal=True,
                stock_refresh_retains_recon=True,reader_tail_restores_stack_and_flags=True)


def scope_use():
    u=emulator();obj=DATA;row=DATA+0x100;flags=DATA+0x200;out=DATA+0x400
    put32(u,obj,17);u.mem_write(obj+4,b'\1');put32(u,obj+8,row);put32(u,obj+12,1);put32(u,obj+16,flags)
    u.mem_write(flags,b'\1');put32(u,row,9);u.mem_write(row+4,bytes((1,1,1,0,1)))
    put32(u,row+12,0);u.mem_write(row+16,b'\1')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x62f038,STOP,count=3000)
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_ability_status(17,[AbilityStatus(9,1,0,0)])
    actor=DATA+0x2000;put32(u,0xac618c,DATA+0x1000);put32(u,DATA+0x1000,actor)
    put32(u,0xac5ef0,DATA+0x9000);put32(u,DATA+0x9000,DATA+0x9100)
    u.mem_write(DATA+0x9437,b'\5') # original target_riflescope metadata
    called=[]
    def hook(uc,address,size,user):
        if address in (0xa93f70,0x9d53b8,0xa867e0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
        elif address==0xa86a34:
            called.append((uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)&255))
            uc.reg_write(UC_X86_REG_EAX,2000);return_from_stub(uc)
        elif address in (0x68a86c,0x95da50):return_from_stub(uc)
        elif address==0x8c0ad7:uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x8c0790,STOP,count=10000)
    assert called==[(actor,1)],called
    return dict(packet=packet.hex(),native_consumer='8c0790',change_state='a86a34',target_state=1,
                animation_resources='animation.xml: human_snip_sit / human_snip_sit_idle / human_snip_sit_fire_')


if __name__=='__main__':
    result=dict(passed=True,recon=recon(),scope_use=scope_use(),limitations=__doc__)
    (REPORT/'native-recon-and-kneeling.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Native recon square/reset/tail and original scope-use kneeling branch PASS')
