"""Execute original49 request and4B result writers against Python encoders."""
from verify_auth_native import *
from tio.protocol.battle_attack import *


def response(r):
    u=emulator();obj=DATA;entries=DATA+0x1000;flags=DATA+0x2000;out=DATA+0x3000
    put32(u,obj,r.actor_id);u.mem_write(obj+4,b'\1')
    for off,(x,y) in ((8,r.origin),(0x1c,r.target),(0x3c,r.impact or r.target)):
        put32(u,obj+off,x);put32(u,obj+off+8,y)
        u.mem_write(obj+off+4,b'\1');u.mem_write(obj+off+12,b'\1');u.mem_write(obj+off+16,b'\1')
    u.mem_write(obj+0x2e,r.weapon_id.to_bytes(2,'little'));u.mem_write(obj+0x30,b'\1')
    put32(u,obj+0x34,r.skill_id);u.mem_write(obj+0x38,b'\1')
    u.mem_write(obj+0x4d,bytes((r.flags,1)))
    if r.mine_state is not None:u.mem_write(obj+0x5c,bytes((r.mine_state,1)))
    put32(u,obj+0x50,entries);put32(u,obj+0x54,len(r.hits));put32(u,obj+0x58,flags)
    for i,h in enumerate(r.hits):
        a=entries+i*28;put32(u,a,h.actor_id);u.mem_write(a+4,bytes((1,h.flags,1)))
        for off,value in zip((8,12,16,20,24),(h.damage,h.left_hp,h.additional_damage,h.absorbed_damage,h.auto_health)):
            u.mem_write(a+off,value.to_bytes(2,'little'));u.mem_write(a+off+2,b'\1')
        u.mem_write(flags+i,b'\1')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x6543fc,STOP,count=8000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_attack_result(r),(packet.hex(),encode_attack_result(r).hex())
    return packet.hex()


def request(r):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac5834,DATA+0x3300);put32(u,0xac5940,DATA+0x3300)
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (flush,0x9dc760):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,r.actor_id);u.reg_write(UC_X86_REG_EDX,r.x);u.reg_write(UC_X86_REG_ECX,r.y)
    u.emu_start(0x95dfe8,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_attack_request(r)
    return packet.hex()


if __name__=='__main__':
    cases=[response(AttackResult(3,(12,14),(18,14),301,(AttackHit(5,20,80),))),
           response(AttackResult(3,(12,14),(18,14),317,(AttackHit(5,99,1),AttackHit(6,80,0)))),
           response(AttackResult(3,(12,14),(18,14),301)),request(AttackRequest(3,18,14)),request(AttackRequest(0x12345678,0,255))]
    (ROOT/'evidence/attack_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Native attack49 / result4B writers:5 cases PASS')
