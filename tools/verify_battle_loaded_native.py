"""Original ti.exe load completion gate36 and silver.dll member-loaded37.

Pending resource count is supplied; scene-finalization and transport endpoints
are isolated. Native state transition, packet builder and member lookup run.
"""
from verify_auth_native import *

EXE_SHA='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'


def exe_emulator():
    raw=BINARY.with_name('ti.exe').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==EXE_SHA
    mapped=pefile.PE(data=raw).get_memory_mapped_image()
    u=Uc(UC_ARCH_X86,UC_MODE_32)
    for address,size in ((0,0x1000),(0x400000,(len(mapped)+0xfff)&~0xfff),
                         (DATA,0x10000),(STACK,0x10000)):
        u.mem_map(address,size)
    u.mem_write(0x400000,mapped)
    put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    return u


def completed(state,pending,load_end=False):
    u=exe_emulator();sent=[]
    for index,address in enumerate((0x76deb4,0x76e17c,0x76e214,0x76e1b4)):
        put32(u,address,DATA+index*0x100)
    u.mem_write(DATA,bytes((state,)))
    def hook(uc,address,size,user):
        if address==0x6f5734:
            uc.reg_write(UC_X86_REG_EAX,pending);return_from_stub(uc)
        elif address==0x726844:
            return_from_stub(uc)
        elif address in (0x41389c,0x413b18):
            sp=uc.reg_read(UC_X86_REG_ESP)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif address in (0x71944c,0x718e68):
            packet=bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)&65535))
            sent.append((hex(address),packet.hex()));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    if load_end:
        u.reg_write(UC_X86_REG_EAX,0x41)
        u.reg_write(UC_X86_REG_EDX,DATA+0x400)
        u.reg_write(UC_X86_REG_ECX,0)
        u.emu_start(0x7182c0,STOP,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert u.mem_read(DATA,1)[0]==3
        assert u.reg_read(UC_X86_REG_EAX)&255==1
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.emu_start(0x717de0,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    gated_state=3 if load_end else state
    expected=gated_state==3 and pending==0
    assert sent==([('0x71944c','36'),('0x718e68','36')] if expected else [])
    assert u.mem_read(DATA,1)[0]==(4 if expected else gated_state)
    assert u.mem_read(DATA+0x200,1)[0]==int(expected)
    return {'state_before':state,'pending':pending,'load_end_packet': '41' if load_end else None,
            'state_after':u.mem_read(DATA,1)[0],
            'transport_calls':sent}


def member_loaded(member_id):
    u=emulator();slots=DATA+0x1000
    put32(u,0xac62a4,slots)
    for slot,identity,occupied in ((0,11,True),(3,22,True),(7,33,False)):
        u.mem_write(slots+slot*0x1c0,bytes((int(occupied),)))
        put32(u,slots+slot*0x1c0+4,identity)
    put32(u,DATA,member_id)
    u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x95e050,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    flags=[u.mem_read(slots+n*0x1c0+0x111,1)[0] for n in range(8)]
    expected=[0]*8
    if member_id in (11,22):expected[0 if member_id==11 else 3]=1
    assert flags==expected
    return {'packet_hex':(b'\x37'+struct.pack('<I',member_id)).hex(),'slot_flags':flags}


if __name__=='__main__':
    result={'method':__doc__,'exe_sha256':EXE_SHA,'silver_sha256':EXPECTED_SHA,
            'completion':[completed(state,pending) for state,pending in ((2,0),(3,1),(3,0),(4,0))]
                         +[completed(2,pending,True) for pending in (0,1)],
            'members':[member_loaded(n) for n in (11,22,33,99)]}
    (ROOT/'evidence/battle_loaded_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Native battle loading:6 completion gates (including41) +4 member lookups PASS')
