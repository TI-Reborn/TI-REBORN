"""Execute original customization92 writer and appearance reader; transport stubbed."""
from verify_auth_native import *
from tio.appearance import encode_request, FIELDS
from trace_pet_info_native import trace
from tio.protocol.pet_info import decode_pet_info,encode_pet_info


def request(owner,values):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vtable);put32(u,vtable,flush);put32(u,0xac600c,handle)
    # Native six words are hair, beard, color, head, body, legs.
    u.mem_write(DATA,struct.pack('<6H',values[1],values[2],values[3],values[0],values[4],values[5]))
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,owner);u.reg_write(UC_X86_REG_EDX,DATA)
    u.emu_start(0x6d0268,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    actual=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert actual==encode_request(owner,bytes(values))
    return actual.hex()


def submit_without_body_catalog():
    u=emulator();u.mem_write(STACK+0x7000,b'\xab'*0x1000)
    obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac6574,DATA+0x3400);put32(u,DATA+0x3400,DATA+0x3504);put32(u,DATA+0x3500,4)
    for n,(kind,value) in enumerate([(1,3),(2,2),(3,1),(4,1)]):
        at=DATA+0x3504+n*56;put32(u,at,value);u.mem_write(at+4,bytes([kind]));u.mem_write(at+32,b'\1')
    put32(u,0xac64b4,DATA+0x3800);put32(u,0xac618c,DATA+0x3900);put32(u,DATA+0x3900,DATA+0x4000)
    put32(u,DATA+0x4004,1);put32(u,DATA+0x4028,27)
    u.mem_write(DATA+0x4060,struct.pack('<6H',3,2,1,1,0,0))
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (flush,0x6d02e8,0x6d06d0):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x6d1d04,STOP,count=10000)
    actual=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert actual==bytes.fromhex('921b00000001030201abab')
    return dict(submit=actual.hex(),uninitialized_body_legs=True)


if __name__=='__main__':
    cases=[submit_without_body_catalog()]
    for values in [(1,3,4,2,0,0),(2,12,0,4,0,0),(1,16,2,3,0,0)]:
        packet=request(27,values)
        baseline=trace(human=True,appearance=True,owner_fields=True)
        pet=decode_pet_info(b'\x66'+bytes.fromhex(baseline['body_hex']),human_equipment=True)
        pet.fields.update(dict(zip(FIELDS,values)))
        pet.fields['0x8c446f']=values[0]
        wire=encode_pet_info(pet)
        actual=trace(body=wire[1:],human=True,new_slot=True)
        assert actual['consumed']==len(wire)-1
        cases.append(dict(values=values,request=packet,pet_bytes=actual['consumed']))
    (ROOT/'evidence/appearance_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,cases=cases),indent=2)+'\n')
    print('3 native customization writers + 3 PetInfo readers: PASS')
