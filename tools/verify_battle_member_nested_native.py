"""Original BattleMemberList25 numeric reader, records with both nested arrays and group2 word children.
Dynamic allocation and strings isolated. a09b78 conversion also executes for
one member with four entries per group; UI/events and managed copies isolated.
"""
from verify_auth_native import *

def verify_conversion(u, records):
    """Original a09b78 through return; isolate strings, events and managed copy."""
    slots, own, state, dummy = (DATA + n for n in (0xa000, 0xb000, 0xb100, 0xb200))
    parent = STACK + 0xf000
    for address, value in ((0xac62a4, slots), (0xac5a98, own),
                           (0xac5498, state), (0xac5538, dummy)):
        put32(u, address, value)
    put32(u, own, 101)
    u.mem_write(parent - 0x134, bytes(u.mem_read(records, 0x134)))
    put32(u, parent - 0x138, 101)

    def conversion_hook(uc, address, size, user):
        eax, edx = uc.reg_read(UC_X86_REG_EAX), uc.reg_read(UC_X86_REG_EDX)
        if address in (0x40c8cc, 0x40c9a4, 0x40c9f4, 0x40c0d8,
                       0x43afc0, 0xa88a78, 0xa09ab0, 0x8d3920,
                       0x68a094, 0xa017c8):
            return_from_stub(uc)
        elif address == 0x40b768:
            n = bytes(uc.mem_read(edx, 1))[0]
            uc.mem_write(eax, bytes(uc.mem_read(edx, n + 1)))
            return_from_stub(uc)
        elif address == 0x67bf80:
            uc.reg_write(UC_X86_REG_EAX, 0)
            return_from_stub(uc)
        elif address == 0x64e4e0:  # managed group2 copy; numeric getters execute
            target = uc.reg_read(UC_X86_REG_ECX)
            source = get32(uc, eax + 0x128) + edx * 0x13c
            uc.mem_write(target, bytes(uc.mem_read(source, 0x13c)))
            return_from_stub(uc)

    handle = u.hook_add(UC_HOOK_CODE, conversion_hook)
    results = []
    for mode in (0, 6, 7, 21):
        u.mem_write(slots, bytes(8 * 0x1c0))
        u.mem_write(parent - 0x139, bytes((mode,)))
        u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        put32(u, STACK + 0x8000, STOP)
        put32(u, STACK + 0x8004, parent)
        u.reg_write(UC_X86_REG_EAX, 0)
        u.emu_start(0xa09b78, STOP, count=20000)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        assert get32(u, slots + 4) == 101
        assert bytes(u.mem_read(slots + 0x111, 1)) == b'\x01'
        assert get32(u, state) == 4
        values = [get32(u, slots + 0x120 + j * 0x28 + 8) for j in range(3)]
        assert values == ([0xffffffff] * 3 if mode == 21 else
                          [21] * 3 if mode in (6, 7) else [11] * 3)
        results.append({'mode': mode, 'own_flag': 1, 'nested_u32_at_128': values})
    u.hook_del(handle)
    return results

if __name__=='__main__':
    cases=[]
    for count in (0,1,2):
        u=emulator();root=DATA+0x2000;records=DATA+0x3000;flags=DATA+0x5000;scratch=DATA+0x6000
        heap=[DATA+0x7000]
        group1=struct.pack('<BIB5I',1,0x12345678,2,0x23456789,11,12,13,14)
        group2=b'Nested\0'+struct.pack('<BHH7I',3,200,300,0x12345678,0x23456789,21,22,23,24,2)+struct.pack('<HH',400,500)
        nested_count = 4 if count == 1 else 2
        member=struct.pack('<I',101)+b'Player\0'+struct.pack('<I6BI',202,1,2,3,4,5,6,nested_count)+group1*nested_count+struct.pack('<I',nested_count)+group2*nested_count
        body=struct.pack('<BBI',7,8,count)+member*count
        u.mem_write(DATA,body);put32(u,0xacd0e8,DATA)
        def hook(uc,addr,size,user):
            eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
            if addr==0x64ea6c:
                put32(uc,eax+4,records);put32(uc,eax+8,edx);put32(uc,eax+12,flags);return_from_stub(uc)
            elif addr in (0x64e3e0,0x64e5b0,0x64d6e4):
                ptr_off,count_off,flags_off,stride={0x64e3e0:(0x11c,0x120,0x124,0x28),0x64e5b0:(0x128,0x12c,0x130,0x13c),0x64d6e4:(0x130,0x134,0x138,4)}[addr]
                put32(uc,eax+ptr_off,heap[0]);heap[0]+=edx*stride+16
                put32(uc,eax+count_off,edx);put32(uc,eax+flags_off,heap[0]);heap[0]+=edx+16;return_from_stub(uc)
            elif addr==0x6297e0:
                ptr=get32(uc,0xacd0e8);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
                put32(uc,0xacd0e8,ptr+len(raw)+1);put32(uc,edx,scratch);uc.mem_write(scratch,bytes([len(raw)])+raw);return_from_stub(uc)
            elif addr==0x40c06c:
                n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
            elif addr==0x40b09c:return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,root)
        u.emu_start(0x64e6b4,STOP,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP and get32(u,0xacd0e8)-DATA==len(body)
        for i in range(count):
            r=records+i*0x134
            assert get32(u,r)==101 and get32(u,r+0x108)==202
            assert [bytes(u.mem_read(r+j,1))[0] for j in (0x10d,0x10f,0x111,0x113,0x115,0x117)]==[1,2,3,4,5,6]
            first=get32(u,r+0x11c);second=get32(u,r+0x128)
            for j in range(nested_count):
                assert bytes(u.mem_read(first+j*0x28+2,1))==b'\x78'
                assert get32(u,first+j*0x28+0x20)==14
                assert get32(u,second+j*0x13c+0x128)==24
                words=get32(u,second+j*0x13c+0x130)
                assert bytes(u.mem_read(words,2))==struct.pack('<H',400)
                assert bytes(u.mem_read(words+4,2))==struct.pack('<H',500)
        conversion = verify_conversion(u, records) if count == 1 else []
        cases.append({'packet_hex':(b'\x25'+body).hex(),'count':count,'consumed_body':len(body),
                      'conversion': conversion})
    (ROOT/'evidence/battle_member_nested_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('BattleMemberList25 original reader and a09b78 conversion: PASS; modes0/6/7/21, own flag, 3-entry cap')
