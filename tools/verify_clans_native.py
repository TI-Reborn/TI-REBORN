"""Execute original clan builders/readers with explicit string/allocation/UI stubs.

Numeric readers and writers execute. Currency-source copying runs918390; this
does not certify rendered screens or user actions in a graphical game client.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from tio.protocol.clans import encode_info,encode_members,encode_invitation
from tio.protocol.warehouse import WarehouseItem
from verify_warehouse_native import run as warehouse_writer
from tio.protocol.asset_count import AssetCount,encode_asset_count


def builder(entry,a=0,d=0,c=0,string=b'Bob'):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address==0x674aac:
            eax=uc.reg_read(UC_X86_REG_EAX);n=get32(uc,eax+0x1004)
            uc.mem_write(eax+4+n,string+b'\0');put32(uc,eax+0x1004,n+len(string)+1)
            put32(uc,DATA+0x400,eax);uc.reg_write(UC_X86_REG_EAX,DATA+0x400);return_from_stub(uc)
        elif address in (flush,0x40b180,0x40b09c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    for reg,value in ((UC_X86_REG_EAX,a),(UC_X86_REG_EDX,d),(UC_X86_REG_ECX,c)):u.reg_write(reg,value)
    u.emu_start(entry,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))


def reader(packet,entry):
    u=emulator();u.mem_write(DATA,packet[1:]);character=DATA+0x4000;heap=DATA+0x8000;seen=[];consumed=[]
    put32(u,0xac5b7c,character);u.mem_write(character+0x24,b'\x05Alice')
    put32(u,0xac55cc,DATA+0x6000);put32(u,DATA+0x6000,DATA+0x6100)
    put32(u,0xac56dc,DATA+0x6300)
    def hook(uc,address,size,user):
        nonlocal heap
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX);ebp=uc.reg_read(UC_X86_REG_EBP)
        if address==0x605f1c:
            ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
            put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap)
            uc.mem_write(heap,bytes([len(raw)])+raw);heap+=0x100;return_from_stub(uc)
        elif address==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
        elif address==0x40b6f8:
            n=uc.reg_read(UC_X86_REG_ECX)
            equal=bytes(uc.mem_read(eax,n))==bytes(uc.mem_read(edx,n))
            flags=uc.reg_read(UC_X86_REG_EFLAGS)
            uc.reg_write(UC_X86_REG_EFLAGS,(flags|0x40) if equal else (flags&~0x40));return_from_stub(uc)
        elif address==0x914550:
            uc.reg_write(UC_X86_REG_EAX,DATA+0x6500);uc.mem_write(DATA+0x6509,b'\1');return_from_stub(uc)
        elif address==0xa017c8:
            seen.append(dict(id=get32(uc,edx+4),rights=get32(uc,edx+0x198)))
            return_from_stub(uc)
        elif address==0x837228:
            seen.append(dict(inviter=eax));return_from_stub(uc)
        elif address in (0x6e6ad4,0x6e6d04,0x6e6e4f):
            ptr={0x6e6ad4:-4,0x6e6d04:-0x1c4,0x6e6e4f:-0xc}[address]
            consumed.append(get32(uc,ebp+ptr)-DATA)
        elif address in (0x40b0fc,0x40c8cc,0x40c9a4,0x40c0d8,0x67bf80,0x40d6c8,
                         0x836e94,0x68a094,0x836b44,0x83649c,0x6061b0):
            uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(entry,STOP,count=15000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==[len(packet)-1],consumed
    return u,seen


def money_sources():
    u=emulator();array=DATA+0x2000;pet=DATA+0x4000;closure=DATA+0x5000;seen=[]
    put32(u,pet+0x6c,array);put32(u,closure+0xc,DATA+0x6000)
    for index,(identity,template,amount) in enumerate(((0xffff0001,1,500),(0xffff0002,2,100))):
        base=array+index*656;put32(u,base+0x28,identity);put32(u,base+8,template);put32(u,base+0x1c,amount)
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x40d70c:put32(uc,eax,array);return_from_stub(uc)
        elif address==0x40cc38:uc.mem_write(eax,bytes(uc.mem_read(edx,656)));return_from_stub(uc)
        elif address==0x40d380:uc.reg_write(UC_X86_REG_EAX,2);return_from_stub(uc)
        elif address==0x917690:
            seen.append((uc.reg_read(UC_X86_REG_ECX)&255,get32(uc,edx+0x28),get32(uc,edx+8),get32(uc,edx+0x1c)))
            return_from_stub(uc)
        elif address in (0x40c8cc,0x40d6c8,0x40c9f4):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,closure);u.reg_write(UC_X86_REG_EDX,pet)
    u.emu_start(0x918390,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert seen==[(5,0xffff0001,1,500),(5,0xffff0002,2,100)],seen
    return seen


def treasury_fields():
    u=emulator();obj=DATA+0x2000;character=DATA+0x4000;warehouse=DATA+0x8000
    packet=encode_asset_count(AssetCount(1000,2000,unknown_u32_08=500,unknown_u32_09=100))
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x65802c,STOP,count=5000)
    assert get32(u,0xacd0e8)-DATA==len(packet)-2
    put32(u,0xac5b7c,character);put32(u,0xac55cc,DATA+0x6000);put32(u,DATA+0x6000,warehouse)
    put32(u,0xac618c,DATA+0x7000);u.mem_write(0xac4754,b'\0')
    def hook(uc,address,size,user):
        if address==0x7d8acc:uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x974730,0x70a78c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x7d4c28,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert (get32(u,warehouse+0x34),get32(u,warehouse+0x38))==(500,100)
    return dict(reader='65802c',consumer='7d4c28',credits=500,gold=100)


def main():
    cases=[]
    for entry,a,d,c,expected in ((0x6e6690,0,0,0,b'\x52Bob\0'),(0x6e66f4,17,0,0,b'\x53'+struct.pack('<I',17)),
        (0x6e6724,19,24,2,b'\x98'+struct.pack('<IIB',19,24,2)),(0x6e676c,0,0,0,b'\x99Bob\0'),
        (0x6e67d0,0,0,0,b'\x5bBob\0'),(0x6e6834,1,0,0,b'\x5d\1'),(0x6e6864,0,0,0,b'\x5fBob\0'),
        (0x6e68c8,0,0,0,b'\x60'),(0x6e7120,1,0,0,b'\x31\1')):
        packet=builder(entry,a,d,c);assert packet==expected,(hex(entry),packet.hex())
        cases.append(dict(builder=hex(entry),packet=packet.hex()))
    clan=dict(id=17,name=b'Alpha',leader_name=b'Alice',level=1,capacity=32,influence=5000)
    u,_=reader(encode_info(clan),0x6e69f8)
    assert get32(u,DATA+0x4000+0x280)==17 and get32(u,DATA+0x4000+0x494)==5000
    m=dict(id=9,name=b'Alice',level=4,online=True,leader=True,permissions=24,title=2,contribution=37)
    u,seen=reader(encode_members((m,)),0x6e6afc)
    assert get32(u,DATA+0x4000+0x498)==24 and seen==[dict(id=9,rights=24)],seen
    _,seen=reader(encode_invitation(9,b'Alice',b'Alpha'),0x6e6de8);assert seen==[dict(inviter=9)]
    cases.extend([dict(kind='info/member/invitation readers',passed=True),dict(kind='native personal money cache copying',records=money_sources())])
    cases.append(warehouse_writer(2,1,0,(WarehouseItem(0xffff0001,1,500,0,0,0),WarehouseItem(0xffff0002,2,100,0,0,0))))
    cases.append(treasury_fields())
    folder=ROOT/'reports/clans';folder.mkdir(parents=True,exist_ok=True)
    (folder/'native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,method=__doc__,cases=cases),indent=2)+'\n')
    print('Native clan builders/readers and money cache: PASS')


if __name__=='__main__':main()
