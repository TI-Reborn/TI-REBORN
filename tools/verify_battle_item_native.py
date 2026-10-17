"""Execute native4E sight writer/consumer and33/49/4B item envelopes.

Actor lookup, Delphi allocation/randomization and network flush are isolated.
Original sight encryption/getter/setter execute. Neither GUI targeting routes
nor persistent smoke/light rendering are claimed by this isolated ABI probe.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX
from tio.protocol.battle_item_status import encode_sight
from tio.protocol.item_action import ItemAction, encode_item_action
from tio.protocol.battle_attack import AttackRequest, AttackResult, AttackHit
from verify_attack_native import request, response


def sight(value):
    u = emulator(); obj = DATA; attr = DATA+0x100; out = DATA+0x400
    put32(u,obj,17); u.mem_write(obj+4,b'\1'); put32(u,obj+8,attr)
    put32(u,obj+12,1); put32(u,obj+16,DATA+0x200); u.mem_write(DATA+0x200,b'\1')
    u.mem_write(attr,b'\x0c\1'); put32(u,attr+4,value); u.mem_write(attr+8,b'\1')
    put32(u,0xacd0e0,out); put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj); u.emu_start(0x654f38,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0))); assert packet==encode_sight(17,value)
    u=emulator(); actor=DATA+0x2000
    put32(u,0xac618c,DATA+0x100); put32(u,DATA+0x100,actor)
    put32(u,actor+8,DATA+0x8100); u.mem_write(DATA+0x8100,b'\x09')
    calls=[]
    def hook(uc,address,size,user):
        if address==0xa93f70: uc.reg_write(UC_X86_REG_EAX,0); return_from_stub(uc)
        elif address==0x406a50: uc.reg_write(UC_X86_REG_EAX,DATA+0x8200); return_from_stub(uc)
        elif address in (0x406a6c,0x406f9c):
            if address==0x406f9c: uc.reg_write(UC_X86_REG_EAX,0)
            return_from_stub(uc)
        elif address==0xa86df8: calls.append('original_setSight')
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17); u.reg_write(UC_X86_REG_EDX,12); u.reg_write(UC_X86_REG_ECX,value)
    u.emu_start(0x8c7320,0x8c7b66,count=2000); assert u.reg_read(UC_X86_REG_EIP)==0x8c7b66
    assert calls==['original_setSight']
    put32(u,STACK+0x8000,STOP); u.reg_write(UC_X86_REG_ESP,STACK+0x8000); u.reg_write(UC_X86_REG_EAX,actor)
    u.emu_start(0xa86de4,STOP,count=100); assert u.reg_read(UC_X86_REG_EAX)==value
    return dict(actor=17,sight=value,packet_hex=packet.hex(),native_consumer='8c7a8b→a86df8→a86de4')


def use(value):
    u=emulator(); obj=DATA+0x1000; handle=DATA+0x3000; vt=DATA+0x3100; flush=DATA+0x3200; frame=STACK+0x7000
    put32(u,handle,obj); put32(u,obj,vt); put32(u,vt,flush); put32(u,0xac600c,handle)
    put32(u,frame-0x294,value.pet_id); put32(u,frame+8,value.option)
    def hook(uc,address,size,user):
        if address==0x6748b0: uc.reg_write(UC_X86_REG_EAX,handle); return_from_stub(uc)
        elif address==flush: return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook); u.reg_write(UC_X86_REG_EBP,frame); u.reg_write(UC_X86_REG_EBX,value.instance_id)
    u.emu_start(0x9904f2,0x99052e,count=1000); assert u.reg_read(UC_X86_REG_EIP)==0x99052e
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004))); assert packet==encode_item_action(value)
    return dict(fields=vars(value),packet_hex=packet.hex(),writer='9904f2..99052c')


def main():
    report=dict(binary_sha256=EXPECTED_SHA,method=__doc__,status='PASS',
        sight_updates=[sight(i) for i in (0,4,6,8,10,255)],
        item_uses=[use(ItemAction(17,1001,255)),use(ItemAction(0x40000001,0xffffffff,255))],
        attack_requests=[request(AttackRequest(17,5,6))],
        attack_results=[response(AttackResult(17,(2,3),(5,6),t,
            (AttackHit(18,0,100),) if t==320 else (),impact=(4,6))) for t in (318,320,5001)])
    (ROOT/'evidence/battle_item_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Native sight writer/model/getter6, item33writers2, attack49writer1, no-damage4Bwriters3:12 cases PASS')


if __name__=='__main__': main()
