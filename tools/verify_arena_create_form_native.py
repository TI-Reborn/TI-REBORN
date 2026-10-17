"""Execute original confirmation85d658 through C8/2B numeric serialization.

UI lookup/track reads and string parsing are fixtures; callback arithmetic,
argument placement, typed setters and serializer execute original instructions.
"""
from verify_auth_native import *

if __name__ == '__main__':
    cases=[]
    for soldiers, levels, players, map_size, stake in ((1,1,2,1,0),(3,5,8,3,12345)):
        u=emulator();settings=DATA+0x2000;window=DATA+0x3000
        put32(u,0xac6008,settings);u.mem_write(settings+0x19,b'\x04')
        put32(u,0xac622c,DATA+0x4000)
        put32(u,0xacf068,DATA+0x5000)
        put32(u,window,DATA+0x6000);put32(u,DATA+0x6000,DATA+0x7000)
        u.mem_write(DATA+0x7000,b'\xc3')
        put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
        tracks={'track_soldiers_count':soldiers,'track_levels_range':levels,
                'track_players_count':players,'track_map_size':map_size}
        def hook(uc,address,size,user):
            eax=uc.reg_read(UC_X86_REG_EAX)
            result=None
            if address==0xa3fca8:result=1
            elif address==0xa3f2a0:result=window
            elif address==0xa424d4:result=0
            elif address==0x85dba4:
                key=bytes(uc.mem_read(eax,80)).decode('utf-16le').split('\0')[0]
                result=tracks[key]
            elif address==0x424724:result=stake
            elif address in (0x629764,0x629938,0x40b09c):
                return_from_stub(uc)
            if result is not None:
                uc.reg_write(UC_X86_REG_EAX,result);return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook)
        u.emu_start(0x85d658,STOP,count=5000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
        assert packet==b'\xc8\x2b'+struct.pack('<IBBBIBBBI',4,map_size,players,2,20*soldiers+20,soldiers,soldiers,levels-1,stake)
        key=bytes(u.mem_read(0x85f884,24)).decode('utf-16le').split('\0')[0]
        cases.append({'tracks':tracks,'numeric_edit':stake,'edit_label_key':key,'packet_hex':packet.hex()})
    (ROOT/'evidence/arena_create_form_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original create form -> C8/2B: 2 cases PASS')
