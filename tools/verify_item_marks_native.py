"""Execute original ItemRecord reader and owner/TTL getters in pinned silver.dll.

Only Delphi managed-string allocation/assignment/cleanup is isolated. Actual
reader63bd38, UTF16-NUL reader629860, primitive field readers, getters and
remaining-seconds timestamp setter execute original x86. No DLL is modified.
This proves outgoing ItemList30 metadata ABI, not a graphical mark command.
"""
from verify_auth_native import *
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.protocol.warehouse import WarehouseItem,encode_warehouse_list
from tio.protocol.item_marks import project, metadata


def read_wide(u, pointer):
    if not pointer:return ''
    result=bytearray()
    for i in range(256):
        word=bytes(u.mem_read(pointer+2*i,2))
        if word==b'\0\0':return result.decode('utf-16-le')
        result.extend(word)
    raise AssertionError('Managed string lacks terminator')


def native_case(name, seconds, *, warehouse=False):
    item=ItemRecord(17,301,bytes(2),1,0,0,(300,300,300),b'\0\0\x01\0',None,bytes(3))
    packet=encode_warehouse_list(0,1,0,(WarehouseItem(17,301,1,300,300,300,marked=True),)) if warehouse else encode_item_list(9,(item,))
    projected=project(packet,{17:(name,seconds)})
    assert metadata(projected)=={17:(name,seconds)}
    entry=0x63e978 if warehouse else 0x63bd38
    body=projected[13 if warehouse else 10:];u=emulator();obj=DATA+0x1000
    u.mem_write(DATA,body);put32(u,0xacd0e8,DATA);put32(u,0xacd0ec,DATA+len(body))
    pool=DATA+0x6000;called=set()
    def allocate(text):
        nonlocal pool
        encoded=text.encode('utf-16-le');address=pool+4
        put32(u,pool,len(text));u.mem_write(address,encoded+b'\0\0');pool=(address+len(encoded)+9)&~3
        assert pool<DATA+0xf000
        return address
    def hook(uc,address,size,user):
        if address in (entry,0x629860):called.add(hex(address))
        if address in (0x40c048,0x40c05c,0x40b47c):
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif address==0x40bf90:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),allocate(chr(uc.reg_read(UC_X86_REG_EDX)&0xffff)));return_from_stub(uc)
        elif address==0x40c164:
            target=uc.reg_read(UC_X86_REG_EAX)
            text=read_wide(uc,get32(uc,target))+read_wide(uc,uc.reg_read(UC_X86_REG_EDX))
            put32(uc,target,allocate(text));return_from_stub(uc)
        elif address in (0x40b0fc,0x40b0e4,0x40b09c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(entry,STOP,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP,'Native record reader did not return'
    assert get32(u,0xacd0e8)==DATA+len(body),'Native reader did not consume entire record'
    if warehouse:
        assert read_wide(u,get32(u,obj+0x2c))==name and bytes(u.mem_read(obj+0x30,1))==b'\x01'
        assert get32(u,obj+0x34)==seconds and bytes(u.mem_read(obj+0x38,1))==b'\x01'
        assert bytes(u.mem_read(obj+0x27,1))==b'\x01' and bytes(u.mem_read(obj+0x29,1))==b'\0'
        return dict(owner=name,seconds=seconds,packet_hex=projected.hex(),native_called=sorted(called),consumed_record_bytes=len(body),warehouse=True)
    assert read_wide(u,get32(u,obj+0x38))==name and bytes(u.mem_read(obj+0x3c,1))==b'\x01'
    assert get32(u,obj+0x40)==seconds and bytes(u.mem_read(obj+0x44,1))==b'\x01'
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_EAX,obj);u.reg_write(UC_X86_REG_EDX,DATA+0x5000)
    u.emu_start(0x63caec,STOP,count=1000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and read_wide(u,get32(u,DATA+0x5000))==name
    getters={}
    for entry,label,expected in ((0x63ca18,'marked',1),(0x63ca78,'rented',0),(0x63cb60,'remaining_seconds',seconds)):
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_EAX,obj)
        u.emu_start(entry,STOP,count=1000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        value=u.reg_read(UC_X86_REG_EAX);assert value==expected,(label,value,expected);getters[label]=value
    put32(u,0xac5fe4,DATA+0x3000);put32(u,DATA+0x3000,1234567)
    ts_item=DATA+0x4000;u.reg_write(UC_X86_REG_ESP,STACK+0x8000);put32(u,STACK+0x8000,STOP)
    u.reg_write(UC_X86_REG_EAX,ts_item);u.reg_write(UC_X86_REG_EDX,seconds);u.emu_start(0xa7be60,STOP,count=100)
    assert get32(u,ts_item)==seconds and get32(u,ts_item+0x25c)==1234
    return dict(owner=name,seconds=seconds,packet_hex=projected.hex(),native_called=sorted(called),owner_getter='0x63caec',consumed_record_bytes=len(body),getters=getters,timestamp_seconds=1234)


if __name__=='__main__':
    cases=[native_case(name,seconds,warehouse=w) for w in (False,True) for name,seconds in (('Alice Prime',86400),('Иван Петров',172800),('Alice',0),('Max',0xffffffff))]
    proof=dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases,
        fields={'0x31':'fmarked','0x33':'frent','0x38':'markerOwnerName','0x40':'markTimeLeft seconds'},
        limitations=['Mark action request and graphical interaction are not verified; this is the existing outgoing ItemList30/WarehouseList6A metadata ABI only.'])
    (ROOT/'evidence/item_marks_native.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Original ItemRecord/WarehouseItem/UTF16 readers + marked/rented/TTL getters:8 cases PASS')
