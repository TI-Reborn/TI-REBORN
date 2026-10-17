"""Original67 sender and mercenary selector predicate; transport isolated."""
from verify_auth_native import *
from tio.protocol.pet_state import encode_pet_state_request,encode_squad_slot


def sender(actor,action,enabled,assignment=False):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    put32(u,0xac5dec,DATA+0x3300);u.mem_write(DATA+0x3300,bytes((enabled,)))
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,actor);u.reg_write(UC_X86_REG_EDX,action)
    u.emu_start(0x8c379c if assignment else 0x8c3c94,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==(encode_squad_slot(actor,action) if assignment else encode_pet_state_request(actor,action) if enabled else b'')
    return {'actor':actor,'action':action,'enabled':enabled,'packet_hex':packet.hex()}


def predicate(state):
    u=emulator();u.mem_write(DATA+0x5ff1,bytes((state,)))
    u.reg_write(UC_X86_REG_EDX,DATA);u.emu_start(0x93f6ac,STOP,count=30)
    result=u.reg_read(UC_X86_REG_EAX)
    assert result==int(state==4)
    return {'state':state,'result':result}


if __name__=='__main__':
    result={'sha256':EXPECTED_SHA,'method':__doc__,
            'sender_cases':[sender(1,0,1),sender(4,1,1),sender(17,255,1),sender(1,0,0)],
            'predicate_cases':[predicate(s) for s in range(5)],
            'slot_assignment_cases':[sender(17,s,1,True) for s in (1,2,3)],
            'remaining':'Establish selector predicate binding, action0 transition and server response before changing saved states.'}
    (ROOT/'evidence/pet_state_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original67 sender4cases and selector predicate5cases PASS')
