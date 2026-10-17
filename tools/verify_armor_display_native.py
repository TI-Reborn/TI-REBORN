"""Original 66/3B armor reads and 4E attribute9 serializer/model write.

Unicorn isolation: actor lookup and UI/runtime calls stubbed; original field
readers/writer execute. No live game, account or client asset is changed.
"""
from verify_auth_native import *
from tio.armor_display import encode_armor
from trace_pet_info_native import trace as pet_trace
from trace_battle_soldier_native import trace as battle_trace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tools.battle_actor_fixture import actor_packet


def status(value):
    u=emulator();obj=DATA;attr=DATA+0x100;out=DATA+0x400
    put32(u,obj,17);u.mem_write(obj+4,b'\x01')
    put32(u,obj+8,attr);put32(u,obj+12,1);put32(u,obj+16,DATA+0x200)
    u.mem_write(DATA+0x200,b'\x01');u.mem_write(attr,b'\x09\x01')
    put32(u,attr+4,value);u.mem_write(attr+8,b'\x01')
    put32(u,0xacd0e0,out);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x654f38,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(out,get32(u,0xacd0f0)))
    assert packet==encode_armor(17,value)
    u=emulator();actor=DATA+0x2000
    put32(u,0xac618c,DATA+0x100);put32(u,DATA+0x100,actor)
    put32(u,actor+0x6010,9999)
    def hook(uc,address,size,user):
        if address==0xa93f70:
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,9);u.reg_write(UC_X86_REG_ECX,value)
    u.emu_start(0x8c7320,0x8c78be,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==0x8c78be
    assert get32(u,actor+0x6010)==value
    return {'value':value,'packet_hex':packet.hex()}


if __name__=='__main__':
    cases=[status(value) for value in (0,67,130,186,65535)]
    source=json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())
    pet=decode_pet_info(bytes.fromhex(source['packet_hex']),human_equipment=True)
    pet.fields['0x8c4ac5']=186
    packet=encode_pet_info(pet)
    assert pet_trace(body=packet[1:],human=True)['native_armor']==186
    soldier=actor_packet(packet,1)
    assert battle_trace(body=soldier[1:],human=True)['model']['armor']==186
    (ROOT/'evidence/armor_display_native.json').write_text(json.dumps(
        {'sha256':EXPECTED_SHA,'method':__doc__,'city_armor':186,'battle_armor':186,'updates':cases,'status':'PASS'},indent=2)+'\n')
    print('Original city66/battle3B armor and 5 absolute4E updates PASS')
