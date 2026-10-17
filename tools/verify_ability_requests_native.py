"""Execute original 8F/90 writers; isolate transport acquisition/flush only."""
from verify_auth_native import *
from tio.protocol.abilities import encode_ability_request


def run(entry,owner,ability):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
    put32(u,0xac600c,handle)
    def hook(uc,address,size,user):
        if address==0x6748b0:
            uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==flush:return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,owner);u.reg_write(UC_X86_REG_EDX,ability)
    u.emu_start(entry,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==encode_ability_request(owner,ability,opcode=0x8f if entry==0x8c2420 else 0x90)
    return dict(entry=hex(entry),packet_hex=packet.hex())


if __name__=='__main__':
    cases=[run(entry,owner,ability) for entry in (0x8c2420,0x8c245c)
           for owner,ability in ((4,23),(0x12345678,0x87654321),(0xffffffff,0))]
    (ROOT/'evidence/ability_requests_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n')
    print('Original ability request writers:6 cases PASS')
