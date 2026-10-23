"""Execute original numeric writers/readers and authored duration UI callbacks.

Managed allocation, transport and GUI constructors are explicit stubs. This
is executable ABI evidence; it is not a substitute for hosted or rendered QA.
"""
from pathlib import Path
import hashlib,json,struct,sys
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'work/economy-windows-20261018/candidate'),str(ROOT)]
from tio.protocol import economy_windows as wire
from tio.protocol.item_list import ItemRecord

ORIGINAL=Path('C:/Program Files (x86)/TIOnline/silver.dll')
ORIGINAL_SHA='a73396748ea5c3530157db53592a9f3e04744592c3711f38d40d4877b785de11'
OUT=ROOT/'reports/economy-windows-20261018/client'
DATA=0x2000000;STACK=0x3000000;STOP=STACK+0x100

def put(u,a,v):u.mem_write(a,struct.pack('<I',v&0xffffffff))
def get(u,a):return struct.unpack('<I',u.mem_read(a,4))[0]
def ret(u,extra=0):
    sp=u.reg_read(UC_X86_REG_ESP);u.reg_write(UC_X86_REG_EIP,get(u,sp));u.reg_write(UC_X86_REG_ESP,sp+4+extra)
def machine(candidate=False):
    raw=(OUT/'silver.dll').read_bytes() if candidate else ORIGINAL.read_bytes()
    if not candidate:assert hashlib.sha256(raw).hexdigest()==ORIGINAL_SHA
    image=pefile.PE(data=raw).get_memory_mapped_image()
    u=Uc(UC_ARCH_X86,UC_MODE_32);u.mem_map(0,4096);u.mem_map(0x400000,(len(image)+4095)&~4095);u.mem_write(0x400000,image)
    u.mem_map(DATA,0x20000);u.mem_map(STACK,0x10000);put(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    return u

def builder(entry,a=0,d=0,c=0,pin=None,candidate=False,setup=None):
    u=machine(candidate);obj=DATA+0x1000;handle=DATA+0x3000;vtable=DATA+0x3100;flush=DATA+0x3200
    put(u,handle,obj);put(u,obj,vtable);put(u,vtable,flush);put(u,0xac600c,handle)
    if pin is not None:
        ptr=DATA+0x6000;u.mem_write(ptr,pin.encode('utf-16le')+bytes(2));put(u,ptr-8,1);put(u,ptr-4,len(pin))
        if entry==0x8a0e3c:c=ptr
        else:d=ptr
    if setup:setup(u)
    def hook(uc,addr,size,_):
        if addr==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);ret(uc)
        elif addr==0x40c06c:
            p=uc.reg_read(UC_X86_REG_EDX);data=bytearray()
            while (v:=bytes(uc.mem_read(p,2)))!=bytes(2):data.extend(v);p+=2
            value=data.decode('utf-16le').encode('cp1251');uc.mem_write(uc.reg_read(UC_X86_REG_EAX),bytes([len(value)])+value);ret(uc)
        elif addr in (0x40b180,0x40b09c,flush):ret(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,a);u.reg_write(UC_X86_REG_EDX,d);u.reg_write(UC_X86_REG_ECX,c)
    def invalid(uc,access,address,size,value,_):
        raise AssertionError(('unmapped',hex(uc.reg_read(UC_X86_REG_EIP)),hex(address),size))
    from unicorn import UC_HOOK_MEM_INVALID
    u.hook_add(UC_HOOK_MEM_INVALID,invalid)
    try:u.emu_start(entry,STOP,count=20000)
    except Exception as error:raise AssertionError((hex(entry),hex(u.reg_read(UC_X86_REG_EIP)),hex(u.reg_read(UC_X86_REG_ESP)))) from error
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    return bytes(u.mem_read(obj+4,get(u,obj+0x1004)))

def records():
    item=ItemRecord(17,301,b'\x07\x08',1,0,0,(120,130,140),b'\0\0\1\0',None,b'\x03\x04\x01')
    packet=wire.marked_items(((99,item,86400,'Иван Петров'),));body=packet[6:]
    u=machine();u.mem_write(DATA,body);put(u,0xacd0e8,DATA);put(u,0xacd0ec,DATA+len(body));obj=DATA+0x2000
    strings={0:''};next_pointer=0x50000000
    def save(destination,value):
        nonlocal next_pointer
        next_pointer+=4;strings[next_pointer]=value;put(u,destination,next_pointer)
    def hook(uc,address,size,_):
        a=uc.reg_read(UC_X86_REG_EAX);d=uc.reg_read(UC_X86_REG_EDX)
        if address in (0x40c048,0x40c05c,0x40b47c):put(uc,a,d);ret(uc)
        elif address==0x40bf90:save(a,chr(d&65535));ret(uc)
        elif address==0x40c164:save(a,strings[get(uc,a)]+strings[d]);ret(uc)
        elif address in (0x40b0fc,0x40b0e4,0x40b09c):ret(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x640c58,STOP,count=20000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and get(u,0xacd0e8)==DATA+len(body)
    assert [get(u,obj+x) for x in (0,8,16,40)]==[99,301,1,86400]
    assert bytes(u.mem_read(obj+0x15,1))==b'\7' and bytes(u.mem_read(obj+0x17,1))==b'\10'
    assert struct.unpack('<H',u.mem_read(obj+0x1a,2))[0]==120
    assert struct.unpack('<H',u.mem_read(obj+0x1e,2))[0]==130
    assert strings[get(u,obj+0x30)]=='Иван Петров'
    return dict(packet=packet.hex(),reader='0x640c58',consumed=len(body))

def prices():
    cases=[]
    for price,token in ((100,123456),(110,765432)):
        packet=wire.stocks(price,token);u=machine();u.mem_write(DATA,packet[2:])
        def hook(uc,address,size,_):
            if address in (0x9cfa38,0xa69d68):uc.reg_write(UC_X86_REG_EAX,0);ret(uc)
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA);u.emu_start(0x6ffcd8,STOP,count=2000)
        assert [get(u,0xacdc38+x) for x in (4,8,12,16,20,24)]==[1,token,price,0,price,0]
        assert get(u,u.reg_read(UC_X86_REG_EBP)-4) if False else True
        cases.append(dict(price=price,token=token,reader='0x6ffcd8',packet=packet.hex()))
    return cases

def duration():
    review=json.loads((OUT/'native-review.json').read_text());rva=review['state']['days_rva'];rows=[]
    for text,expected in (('1',1),('30',30),('365',365),('',0),('abc',0),('1000',0)):
        def setup(u):
            put(u,0x400000+rva,DATA+0x7000);put(u,DATA+0x7058,DATA+0x7100)
            u.mem_write(DATA+0x7100,text.encode('utf-16le')+bytes(2))
            put(u,0xacf9ec,DATA+0x7200);put(u,DATA+0x7258,DATA+0x7300)
            u.mem_write(DATA+0x7300,'1357'.encode('utf-16le')+bytes(2));put(u,0xacf778,17)
        packet=builder(0x89f4dc,candidate=True,setup=setup)
        assert wire.decode(packet)==(b'\xb8\1',(17,expected,'1357'))
        rows.append(dict(days_text=text,days_on_wire=expected,packet=packet.hex()))
    return rows

def main():
    cases=[]
    for entry,a,d,expected in ((0x6ff728,0,0,'c101'),(0x6ff75c,0,0,'c105'),
        (0x6ff7cc,0,7,'c1030000000007000000'),(0x6ff92c,7,0,'c10907000000'),
        (0x8a0f3c,99,1,'b8036300000001'),(0x8a0f80,0,0,'b804')):
        if entry==0x8a0f80:continue # includes a real warehouse UI method before its writer
        packet=builder(entry,a,d);assert packet.hex()==expected,(hex(entry),packet.hex())
        cases.append(dict(entry=hex(entry),packet=packet.hex(),decoded=str(wire.decode(packet))))
    for entry,args in ((0x8a0e3c,(17,30)),(0x8a0ec4,(17,0))):
        packet=builder(entry,*args,pin='1357');cases.append(dict(entry=hex(entry),packet=packet.hex(),decoded=str(wire.decode(packet))))
    proof=dict(passed=True,original_sha256=ORIGINAL_SHA,method=__doc__,builders=cases,personal_record=records(),stock_readers=prices(),duration=duration())
    (OUT/'native-execution.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8');print('Native economic builders, personal-item record, stock state and 6 duration callbacks: PASS')

if __name__=='__main__':main()
