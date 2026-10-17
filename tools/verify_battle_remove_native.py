"""Execute original43 reader and model removal writes, stopping before UI notification.

Actor lookup is isolated; no live scene removal is claimed.
"""
from verify_auth_native import *
from tio.protocol.battle_remove import encode_battle_remove


def run(actor_id):
    u=emulator()
    actor=DATA+0x2000
    put32(u,0xac618c,DATA+0x1000)
    put32(u,DATA+0x1000,actor)
    put32(u,actor+0x603c,2);put32(u,actor+0x6040,3)
    packet=encode_battle_remove(actor_id)
    u.mem_write(DATA,packet[1:])
    consumed=[]
    def hook(uc,address,size,user):
        if address==0xa93f70:
            assert uc.reg_read(UC_X86_REG_EAX)==actor_id
            uc.reg_write(UC_X86_REG_EAX,0)
            return_from_stub(uc)
        elif address==0x8c7257:
            consumed.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x8c71e0,STOP,count=1000)
    assert consumed==[4]
    assert bytes(u.mem_read(actor+0x20,1))==b'\x01'
    assert (get32(u,actor+0x603c),get32(u,actor+0x6040))==(255,255)
    return dict(packet_hex=packet.hex(),consumed=4,removed_flag=1,position=[255,255])


if __name__=='__main__':
    cases=[run(i) for i in (1,101,0xffffffff)]
    (ROOT/'evidence/battle_remove_native.json').write_text(json.dumps(
        dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n',encoding='utf-8')
    print('Original actor removal reader/model writes: 3 cases PASS')
