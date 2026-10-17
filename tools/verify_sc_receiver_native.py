"""Bounded original-client SC receive-route proof, not a reconstructed BD ABI.

All 31 legacy opcode gates, all 13 statically registered interface gates and the
typed packet classifier execute unchanged. Only reference-count lifecycle,
clock and enumerator allocation are isolated. There is no packet-reader stub.
The pinned original DLL rejects BD for every subcode before reading its body.
This proves the installed build cannot populate its dormant SC lot/history
arrays through its exported receive route; it does not describe older builds.
"""
from verify_auth_native import *
import capstone

REGISTRATIONS = (
    (0xab7ca0,0x6f80cc,12),(0xab7d3f,0x7001d4,12),
    (0xab882d,0x7dc418,20),(0xab894d,0x7f13a4,24),
    (0xab8a21,0x7f9cf4,12),(0xab8acd,0x80680c,12),
    (0xab9255,0x8c3b00,12),(0xab9815,0x931424,24),
    (0xab99f6,0x93e85c,12),(0xab9b55,0x954e14,16),
    (0xaba07d,0x9cdb3c,12),(0xaba116,0x9d02ac,12),
    (0xaba209,0x9e1a8c,16),
)


def mapped():
    raw=BINARY.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==EXPECTED_SHA
    return pefile.PE(data=raw).get_memory_mapped_image()


def references(image,value):
    result=[];start=0;needle=struct.pack('<I',value)
    while True:
        found=image.find(needle,start)
        if found<0:return result
        result.append(found+0x400000);start=found+1


def registrations(image):
    def read(address):return struct.unpack_from('<I',image,address-0x400000)[0]
    actual=[]
    for offset in range(len(image)-5):
        if image[offset]==0xe8 and offset+0x400005+struct.unpack_from('<i',image,offset+1)[0]==0x66c808:
            actual.append(offset+0x400000)
    assert actual==[row[0] for row in REGISTRATIONS],actual
    rows=[]
    for call,slot,displacement in REGISTRATIONS:
        vmt=read(slot);table=read(vmt-84)
        entries=[table+4+i*28 for i in range(read(table))]
        entry=next(e for e in entries if read(e+20)==displacement)
        interface_vmt=read(entry+16);gate=read(interface_vmt+12)
        name=read(vmt-56);length=image[name-0x400000]
        name=image[name-0x400000+1:name-0x400000+1+length].decode('ascii')
        rows.append(dict(registration=hex(call),class_slot=hex(slot),class_name=name,
            vmt=vmt,interface_vmt=interface_vmt,displacement=displacement,gate=gate))
    return rows


def receive_probe(rows):
    u=emulator();put32(u,0xac5834,DATA+0x1000)
    registry=DATA+0x2000;listing=DATA+0x2100;enumerator=DATA+0x2400
    put32(u,0xac450c,registry);put32(u,registry+4,listing)
    put32(u,listing+4,DATA+0x3000);put32(u,listing+8,len(rows))
    for index,row in enumerate(rows):
        obj=DATA+0x4000+index*0x100
        put32(u,obj,row['vmt']);put32(u,obj+row['displacement'],row['interface_vmt'])
        put32(u,DATA+0x3000+index*4,obj+row['displacement'])
    trace=[];stubs=[];active=False
    image=mapped();md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_32)
    legacy=[int(i.op_str,16) for i in md.disasm(image[0x9f5548-0x400000:0x9f5786-0x400000],0x9f5548)
        if i.mnemonic=='call' and i.op_str.startswith('0x')]
    assert len(legacy)==31,len(legacy)
    gates=set(legacy)|{r['gate'] for r in rows}|{0x65d034}
    def hook(uc,address,size,user):
        if active and address in gates:trace.append(hex(address))
        if address==0x66f198:
            put32(uc,enumerator,get32(uc,0x669a98))
            put32(uc,enumerator+4,listing);put32(uc,enumerator+8,0xffffffff)
            uc.reg_write(UC_X86_REG_EAX,enumerator);stubs.append(hex(address));return_from_stub(uc)
        elif address==0x40eca8:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX))
            stubs.append(hex(address));return_from_stub(uc)
        elif address==0x40ec90:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),0);stubs.append(hex(address));return_from_stub(uc)
        elif address in (0x4092dc,0x4092cc):
            stubs.append(hex(address));return_from_stub(uc)
        elif address==0x629740:
            uc.reg_write(UC_X86_REG_EAX,1);stubs.append(hex(address));return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    cases=[]
    for subcode in range(256):
        packet=bytes((0xbd,subcode))+bytes(range(64))
        u.mem_write(DATA,packet);sp=STACK+0x8000
        u.mem_write(sp,struct.pack('<5I',STOP,0xbd,DATA,len(packet),0))
        u.reg_write(UC_X86_REG_ESP,sp);trace.clear();active=True
        try:u.emu_start(0x9f5548,STOP,count=20000)
        except Exception as exc:raise AssertionError((subcode,hex(u.reg_read(UC_X86_REG_EIP)),trace)) from exc
        active=False
        assert u.reg_read(UC_X86_REG_EIP)==STOP,hex(u.reg_read(UC_X86_REG_EIP))
        assert u.reg_read(UC_X86_REG_EAX)==0,(subcode,u.reg_read(UC_X86_REG_EAX))
        assert trace==[hex(x) for x in legacy]+[hex(r['gate']) for r in rows]+['0x65d034'],trace
        assert get32(u,0xacd0e8)==DATA+1,'BD body was read by typed classifier'
        assert all(get32(u,address)==0 for address in (0xacf418,0xacf41c,0xacf420))
        cases.append(subcode)
    return dict(subcodes_rejected=cases,legacy_gates=[hex(x) for x in legacy],
        interface_gates=[hex(r['gate']) for r in rows],typed_classifier='0x65d034',
        typed_cursor_bytes=1,stubbed_lifecycle=sorted(set(stubs)),
        sc_lot_and_history_arrays_unchanged=True)


def main():
    image=mapped();rows=registrations(image);probe=receive_probe(rows)
    globals={hex(address):references(image,address) for address in (0xacf414,0xacf418,0xacf41c,0xacf420)}
    assert all(0x88c000<=ref<=0x89e400 for refs in globals.values() for ref in refs)
    report=dict(sha256=EXPECTED_SHA,method=__doc__,status='native BD receive ABI unavailable in pinned build',
        registered_interfaces=rows,receive_probe=probe,sc_global_references=globals,
        next_requirement='A historical client with a working BD receive handler or an explicitly reviewed client extension is required for the original SC window.')
    (ROOT/'evidence/sc_receiver_native.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Original BD receive route: 256 subcodes rejected by 31 legacy + 13 registered gates and typed classifier; PASS')


if __name__=='__main__':main()
