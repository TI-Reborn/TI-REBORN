"""Read-only original Silver/ti.exe crest transport and cache proof.

Original scalar readers/writers, callback wrappers, queue deduplication and tick
execute. Delphi managed strings/arrays, filesystem, streams, renderer and wire
send are explicit stubs; no files in the installed game are modified, no sockets.
"""
import hashlib,json,struct,sys
from pathlib import Path
import pefile
from unicorn import Uc,UC_ARCH_X86,UC_MODE_32,UC_HOOK_CODE
from unicorn.x86_const import *
from verify_auth_native import ROOT,BINARY,EXPECTED_SHA,DATA,STACK,STOP,emulator,put32,get32,return_from_stub
from tio.protocol.clans import encode_info

TI=BINARY.parent/'ti.exe'
TI_SHA='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'


def ret(u,extra=0):
    return_from_stub(u)
    if extra:u.reg_write(UC_X86_REG_ESP,u.reg_read(UC_X86_REG_ESP)+extra)


def crest_bmp(color=7):
    return b'BM'+struct.pack('<III',822,0,54)+struct.pack('<IiiHHIIiiII',40,16,16,1,24,0,768,0,0,0,0)+bytes([color])*768


def silver_info(identity):
    clan=dict(id=17,name=b'Alpha',leader_name=b'Alice',level=1,capacity=32,influence=5000)
    packet=bytearray(encode_info(clan));offset=1+4+len(clan['name'])+1+len(clan['leader_name'])+1+1
    struct.pack_into('<I',packet,offset,identity)
    u=emulator();u.mem_write(DATA,bytes(packet[1:]));character=DATA+0x4000;heap=DATA+0x8000;seen=[];consumed=[]
    put32(u,0xac5b7c,character);put32(u,0xac55cc,DATA+0x6000);put32(u,DATA+0x6000,DATA+0x6100)
    callback=DATA+0xf000;u.mem_write(callback,b'\xc3')
    # Execute the exported callback registration with its original stdcall ABI.
    put32(u,STACK+0x8004,callback);u.emu_start(0x4f2414,STOP,count=100)
    assert get32(u,0xacc474)==callback
    put32(u,STACK+0x8000,STOP);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    def hook(uc,address,size,user):
        nonlocal heap
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX);ebp=uc.reg_read(UC_X86_REG_EBP)
        if address==0x605f1c:
            ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0];put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap);uc.mem_write(heap,bytes([len(raw)])+raw);heap+=0x100;ret(uc)
        elif address==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));ret(uc)
        elif address==callback:
            sp=uc.reg_read(UC_X86_REG_ESP);seen.append(dict(id=get32(uc,sp+4),kind=get32(uc,sp+8)&255));ret(uc,8)
        elif address==0x6e6ad4:consumed.append(get32(uc,ebp-4)-DATA)
        elif address in (0x40b0fc,0x836b44,0x83649c):ret(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA);u.emu_start(0x6e69f8,STOP,count=15000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and consumed==[len(packet)-1]
    assert get32(u,character+0x48c)==identity and seen==[dict(id=identity,kind=0)]
    return dict(opcode='54',wire_offset=offset,field='character+0x48c',id=identity,callback=seen,consumed_payload=consumed[0])


class TiProbe:
    def __init__(self):
        raw=TI.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=TI_SHA:raise ValueError('Unrecognized pinned ti.exe')
        image=pefile.PE(data=raw).get_memory_mapped_image();self.u=Uc(UC_ARCH_X86,UC_MODE_32)
        self.u.mem_map(0,0x1000);self.u.mem_map(0x400000,(len(image)+4095)&~4095);self.u.mem_write(0x400000,image)
        self.u.mem_map(DATA,0x10000);self.u.mem_map(STACK,0x10000);self.heap=DATA+0x9000;self.strings={0:''}
        self.sent=[];self.checked=[];self.loaded=[];self.saved=[];self.consumed=[];self.array=DATA+0x4000
        self.stream=DATA+0x5000;self.virtual=DATA+0x5100;self.read_stub=DATA+0xf000;self.u.mem_write(self.read_stub,b'\xc3')
        put32(self.u,self.stream,self.virtual);put32(self.u,self.virtual+0x10,self.read_stub)
        put32(self.u,0x76e494,DATA+0x1000);put32(self.u,DATA+0x1000,DATA+0x2000)
        put32(self.u,0x76e0f0,DATA+0x3000);put32(self.u,DATA+0x3000,self.save_string('C:\\TI\\data\\'))
        put32(self.u,0x76e314,DATA+0x3400);put32(self.u,DATA+0x3400,10000);put32(self.u,0x76da88,0)
        self.u.hook_add(UC_HOOK_CODE,self.hook)

    def save_string(self,s):
        pointer=self.heap;self.heap+=0x100;self.strings[pointer]=s
        raw=s.encode('utf-16le');put32(self.u,pointer-4,len(raw)//2);self.u.mem_write(pointer,raw+b'\0\0');return pointer

    def string(self,p):
        if p in self.strings:return self.strings[p]
        n=get32(self.u,p-4);assert n<1024
        return bytes(self.u.mem_read(p,n*2)).decode('utf-16le')

    def hook(self,u,address,size,user):
        eax=u.reg_read(UC_X86_REG_EAX);edx=u.reg_read(UC_X86_REG_EDX);ecx=u.reg_read(UC_X86_REG_ECX);sp=u.reg_read(UC_X86_REG_ESP)
        if address==0x423c64:
            value=get32(u,sp+4)|(get32(u,sp+8)<<32);put32(u,eax,self.save_string(str(value)));ret(u,8)
        elif address==0x40c084:
            text=''.join(self.string(get32(u,sp+4+i*4)) for i in reversed(range(edx)));put32(u,eax,self.save_string(text));ret(u,edx*4)
        elif address==0x40bffc:
            put32(u,eax,self.save_string(self.string(edx)+self.string(ecx)));ret(u)
        elif address==0x40d378:
            count=get32(u,sp+4);assert count<200;put32(u,self.array-4,count);put32(u,eax,self.array if count else 0);ret(u,4)
        elif address==0x4246b8:
            self.checked.append(self.string(eax));u.reg_write(UC_X86_REG_EAX,0);ret(u)
        elif address==0x60fc44:u.reg_write(UC_X86_REG_EAX,0xffffffff);ret(u)
        elif address==0x718e28:self.sent.append(bytes(u.mem_read(eax,edx&65535)));ret(u)
        elif address==0x406cdc:u.mem_write(edx,bytes(u.mem_read(eax,ecx)));ret(u)
        elif address==0x4091e4:u.reg_write(UC_X86_REG_EAX,self.stream);ret(u)
        elif address==self.read_stub:
            self.loaded.append(bytes(u.mem_read(edx,ecx)));u.reg_write(UC_X86_REG_EAX,ecx);ret(u)
        elif address==0x4b66cc:ret(u,8)
        elif address==0x610110:
            assert edx==self.stream;assert self.string(ecx).isdigit();u.reg_write(UC_X86_REG_EAX,DATA+0x6000);ret(u,8)
        elif address==0x424750:u.reg_write(UC_X86_REG_EAX,1);ret(u)
        elif address==0x4b8fb0:self.saved.append(self.string(edx));ret(u)
        elif address==0x71982d:self.consumed.append(get32(u,u.reg_read(UC_X86_REG_EBP)-4)-DATA)
        elif address in (0x40af54,0x40afb4,0x409214):ret(u)

    def call(self,entry,a=0,d=0,c=0,args=()):
        put32(self.u,STACK+0x8000,STOP)
        for i,value in enumerate(args):put32(self.u,STACK+0x8004+i*4,value)
        for reg,value in ((UC_X86_REG_ESP,STACK+0x8000),(UC_X86_REG_EAX,a),(UC_X86_REG_EDX,d),(UC_X86_REG_ECX,c)):self.u.reg_write(reg,value)
        self.u.emu_start(entry,STOP,count=100000)
        assert self.u.reg_read(UC_X86_REG_EIP)==STOP,hex(self.u.reg_read(UC_X86_REG_EIP))

    def queue(self,identity,kind=0):self.call(0x71c314,args=(identity,kind))

    def records(self):
        return [dict(kind=bytes(self.u.mem_read(self.array+i*12,1))[0],id=get32(self.u,self.array+i*12+4),requested=bytes(self.u.mem_read(self.array+i*12+8,1))[0],complete=bytes(self.u.mem_read(self.array+i*12+9,1))[0]) for i in range(get32(self.u,self.array-4))] if get32(self.u,0x7865a0) else []


def cache_cycle():
    p=TiProbe();p.queue(0);assert p.records()==[]
    p.queue(19);p.queue(19);p.queue(23,1)
    assert p.records()==[dict(kind=0,id=19,requested=0,complete=0),dict(kind=1,id=23,requested=0,complete=0)]
    assert p.checked==['C:\\TI\\data\\..\\icons\\ic19.bmp','C:\\TI\\data\\..\\icons\\ic23.bmp'],p.checked
    p.call(0x719d94)
    assert p.sent==[b'\x59'+struct.pack('<I',19),b'\xaf\x06'+struct.pack('<I',23)],p.sent
    p.call(0x719d94);assert len(p.sent)==2
    for op,identity in ((b'\x5a',19),(b'\xaf\x07',23)):
        packet=op+struct.pack('<IH',identity,822)+crest_bmp();p.u.mem_write(DATA,packet)
        p.call(0x719904,a=packet[0],d=DATA+1,c=len(packet));assert p.u.reg_read(UC_X86_REG_EAX)&255==1
        assert p.loaded[-1]==crest_bmp() and p.consumed[-1]==len(packet)
    assert all(r['requested'] and r['complete'] for r in p.records())
    for op in (0x58,0x59):p.call(0x719904,a=op,d=DATA+1,c=1);assert p.u.reg_read(UC_X86_REG_EAX)&255==0
    return dict(queue=p.records(),cache_miss_checked=p.checked,c2s=[v.hex() for v in p.sent],s2c_consumed=p.consumed,
                bitmap_lengths=[len(v) for v in p.loaded],bitmap_sha256=hashlib.sha256(crest_bmp()).hexdigest(),saved_names=p.saved)


def top_down_not_loaded():
    p=TiProbe();p.queue(19);p.call(0x719d94)
    raw=bytearray(crest_bmp());struct.pack_into('<i',raw,22,-16)
    packet=b'\x5a'+struct.pack('<IH',19,len(raw))+raw;p.u.mem_write(DATA,bytes(packet))
    p.call(0x719904,a=0x5a,d=DATA+1,c=len(packet))
    assert p.u.reg_read(UC_X86_REG_EAX)&255 and p.consumed==[len(packet)] and not p.loaded and not p.saved
    return dict(height=-16,handled=True,consumed=len(packet),stream_image_loader_called=False,
                policy='Canonical crest APIs require bottom-up height+16; original negative-size gate skips image load')


def main():
    result=dict(passed=True,silver_sha256=EXPECTED_SHA,ti_sha256=TI_SHA,method=__doc__,silver=[silver_info(n) for n in (0,19,0xffffffff)],cache=cache_cycle(),top_down_rejection=top_down_not_loaded(),
        contract=dict(clan_request='59 id:u32',clan_reply='5A id:u32 bmp_length:u16 bmp:bytes',alliance_request='AF06 id:u32',alliance_reply='AF07 id:u32 bmp_length:u16 bmp:bytes',native_buffer_max=1024,server_validated_max=824,transport='game binary packets; no crest HTTP URL',cache='..\\icons\\ic<ID>.bmp',clan_field_54='u32 immediately after clan level; character+0x48c'))
    (ROOT/'evidence/clan_crest_native.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('Original Silver54 and ti.exe clan59/5A allianceAF06/AF07 cache queue/readers: PASS')


if __name__=='__main__':main()
