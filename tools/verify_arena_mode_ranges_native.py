"""Original85decc arena range callback; UI track access/setters isolated.
Predicate6a10dc held false (special four-player restriction excluded).
"""
from verify_auth_native import *

def run(mode,players,map_size):
    u=emulator();put32(u,0xac6008,DATA+0x1000);u.mem_write(DATA+0x1019,bytes((mode,)))
    ranges={}
    def key(uc):return bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),100)).decode('utf-16le').split('\0')[0]
    def hook(uc,address,size,user):
        if address==0x85dba4:
            value={'track_players_count':players,'track_map_size':map_size}[key(uc)]
            uc.reg_write(UC_X86_REG_EAX,value);return_from_stub(uc)
        elif address==0x85d9bc:
            ranges[key(uc)]=[uc.reg_read(UC_X86_REG_EDX),uc.reg_read(UC_X86_REG_ECX)]
            return_from_stub(uc)
        elif address==0x6a10dc:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x85decc,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    if mode in (4,8):assert ranges=={'track_soldiers_count':[1,1],'track_players_count':[8,8]}
    return dict(mode=mode,players=players,map_size=map_size,ranges=ranges)

if __name__=='__main__':
    cases=[run(mode,players,size) for mode in (0,1,4) for players,size in ((2,2),(2,3),(8,3))]
    (ROOT/'evidence/arena_mode_ranges_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original arena range callback: 9 cases PASS')
