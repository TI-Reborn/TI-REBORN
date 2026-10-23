"""Original moving1D, stop1E, map step9EDD18 and visual interpolation9EDF92.

Movement readers/step/interpolation are unstubbed. F0/97 branch uses UI-call
stubs; command table and clear-current-town assignment are original code.
"""
from verify_auth_native import *
from tio.locations import movement_packet,stop_packet,MAP_SPEED
import math


def main():
    u=emulator();char=DATA+0x2000
    for a,p in ((0xac5a98,DATA+0x1000),(0xac5b7c,char),(0xac5a4c,DATA+0x3000),
                (0xac60a4,DATA+0x4000),(0xac5fe4,DATA+0x5000)):
        put32(u,a,p)
    put32(u,DATA+0x1000,42)
    def run(entry,end=STOP):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
        u.emu_start(entry,end,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==end
    def receive(packet,entry):
        u.mem_write(DATA,packet[1:]);u.reg_write(UC_X86_REG_EAX,DATA);run(entry)
    def floats():return struct.unpack('<ff',u.mem_read(char+0x1c,8))
    receive(movement_packet(42,-154,-318),0x88b130)
    old=floats()
    moving=movement_packet(42,-154,-318,destination=(-77,-447))
    receive(moving,0x88b130)
    assert floats()==old and get32(u,char+0x224)==0xffffffff
    put32(u,char+8,MAP_SPEED);put32(u,char+0x228,1000);put32(u,DATA+0x5000,1500)
    run(0x9edd18)
    stepped=struct.unpack('<ii',u.mem_read(char+0xc,8))
    assert abs(math.dist(old,stepped)-MAP_SPEED*.5)<1.5 and stepped!=(-77,-447)
    # Execute just the native interpolation arithmetic; renderer setup supplied.
    u.reg_write(UC_X86_REG_EAX,30);u.reg_write(UC_X86_REG_EBP,STACK+0x7000)
    run(0x9edf92,0x9edff0)
    smoothed=floats()
    assert math.dist(smoothed,stepped)<math.dist(old,stepped)
    assert smoothed!=stepped and smoothed!=old
    receive(stop_packet(42,-77,-447),0x88b248)
    assert get32(u,char+0x224)==0
    assert struct.unpack('<ii',u.mem_read(char+0xc,8))==(-77,-447)
    assert floats()==smoothed  # Stop also leaves render interpolation intact.
    index=u.mem_read(0x7d1db4+97,1)[0]
    assert get32(u,0x7d1fbf+4*index)==0x7d2de6
    put32(u,0xac5d58,DATA+0x6000);put32(u,DATA+0x6000,3)
    put32(u,0xac5630,DATA+0x6100);put32(u,0xac54d8,DATA+0x6200)
    def hook(uc,addr,size,user):
        if addr in (0xa00c60,0xa01ef4,0x8a36c0,0x9e58a8):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);run(0x7d2de6,0x7d2e35)
    assert get32(u,DATA+0x6000)==0xffffffff
    report={'method':__doc__,'sha256':EXPECTED_SHA,'packet':moving.hex(),'initial':old,
            'after_half_second':stepped,'after_render_step':smoothed,'leave_town_command':97}
    (ROOT/'evidence/map_motion_native.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Original map motion: moving/stop/step/smoothing/leave-town PASS')


if __name__=='__main__':main()
