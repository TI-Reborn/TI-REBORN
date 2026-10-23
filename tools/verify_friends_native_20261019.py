"""Published native friends list reader and real shared-dialog layout, UI storage isolated."""
import hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.verify_legacy_lobbies_native import *
from unicorn.x86_const import UC_X86_REG_EFLAGS
from tio.protocol.friends import Friend,encode_list
RAW=(ROOT/'work/groza-20261019/gui/game-a/silver.dll').read_bytes()
assert hashlib.sha256(RAW).hexdigest()=='717d89cd25912d593ac9b6cf0f593faac509f42d7572ccf63ba063f41cef9625'

def listing(base):
    u=emulator(RAW,base);a=lambda v:v+base-0x400000
    records=[Friend(17,b'Alice',True,4,25,1,31),Friend(18,b'Bob',False,2)]
    packet=encode_list(records);u.mem_write(DATA,packet[1:]);seen=[];heap=DATA+0x7000
    for offset in (0xac5670,0xac55c8,0xac5914,0xac56bc,0xac622c):put(u,a(offset),DATA+0x1000)
    put(u,DATA+0x1000,DATA+0x2000);u.mem_write(DATA+0x1000,b'\1')
    def hook(uc,address,size,_):
        nonlocal heap
        va=address-base+0x400000;eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if va==0x605f1c:
            ptr=get(uc,eax);s=bytes(uc.mem_read(ptr,64)).split(b'\0',1)[0];put(uc,eax,ptr+len(s)+1)
            put(uc,edx,heap);uc.mem_write(heap,bytes([len(s)])+s);heap+=0x100;ret(uc)
        elif va==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));ret(uc)
        elif va==0x7f4718:
            raw=bytes(uc.mem_read(eax,0x1c0));seen.append(dict(id=struct.unpack_from('<I',raw,4)[0],name=raw[9:9+raw[8]].decode(),online=raw[0x10a],level=raw[0x109],status=raw[0x10b],crest=struct.unpack_from('<I',raw,0x114)[0]));ret(uc)
        elif va==0xa3fca8:uc.reg_write(UC_X86_REG_EAX,0xffffffff);ret(uc)
        elif va in (0x40c8cc,0x40c9a4,0x40b09c,0x68a094,0xa494ac,0x9cfa38):ret(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,0x9f);u.reg_write(UC_X86_REG_EDX,DATA)
    run(u,0x7f4440,base)
    assert seen==[dict(id=p.identity,name=p.name.decode(),online=int(p.online),level=p.level,status=p.status,crest=p.crest) for p in records],seen
    return seen

def dialogue(base):
    u=emulator(RAW,base);a=lambda v:v+base-0x400000
    window=DATA+0x1000;buttons=[DATA+0x2000+i*0x400 for i in range(3)];handle=DATA+0x4000;vtable=DATA+0x4100;visible=DATA+0x4200
    put(u,a(0xac622c),handle);put(u,handle,window);put(u,window+0x38,320)
    for p,name in zip(buttons,('yes','no','noall')):
        put(u,p,vtable);put(u,p+0x38,100);put(u,p+0x68,p+0x350);u.mem_write(p+0x350,name.encode('utf-16le')+b'\0\0');u.mem_write(p+0x49,b'\1')
    put(u,vtable,visible);reset=[];attached=[]
    def wide(ptr):
        raw=bytes(u.mem_read(ptr,100));end=next(i for i in range(0,len(raw),2) if raw[i:i+2]==b'\0\0');return raw[:end].decode('utf-16le')
    def hook(uc,address,size,_):
        va=address-base+0x400000;eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        value=None
        if va==0xa3fca8:value=0
        elif va==0xa3f2a0:value=window
        elif va==0xa424d4:value=3
        elif va==0xa424c4:value=buttons[edx]
        elif va==0x4095ac:value=1
        elif va==0x40c354:
            flags=uc.reg_read(UC_X86_REG_EFLAGS);uc.reg_write(UC_X86_REG_EFLAGS,(flags|0x40) if wide(eax)==wide(edx) else (flags&~0x40));ret(uc);return
        elif address==visible:uc.mem_write(eax+0x49,bytes([edx&255]));ret(uc);return
        elif va==0xa54c5c:reset.append(eax);ret(uc);return
        elif va==0xa55038:ret(uc);return
        elif va==0xa54f40:attached.append((eax,edx));ret(uc);return
        if value is not None:uc.reg_write(UC_X86_REG_EAX,value);ret(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    allocation=DATA+0x8000
    branch=lambda op,source,target:bytes([op])+struct.pack('<i',target-source-5)
    code=bytes.fromhex('50525131c031d231c9');code+=branch(0xe8,allocation+len(code),a(0x688798));code+=bytes.fromhex('595a58');code+=branch(0xe9,allocation+len(code),a(0xa54f40))
    u.mem_write(allocation,code);u.reg_write(UC_X86_REG_EAX,123);u.reg_write(UC_X86_REG_EDX,456)
    run(u,allocation-base+0x400000,base)
    assert attached==[(123,456)] and len(reset)==3
    assert bytes(u.mem_read(buttons[2]+0x49,1))==b'\0'
    assert [get(u,p+0x30) for p in buttons[:2]]==[46,174]
    for site in (0xa04451,0xa047ed):assert bytes(u.mem_read(a(site),5))==branch(0xe8,a(site),a(0xa54f40))
    return dict(extra_button_hidden=True,yes_no_centered=True,captured_callback_preserved=True)

if __name__=='__main__':
    result=dict(passed=True,graphical_clients=False,cases=[dict(base=hex(b),reader=listing(b),dialogue=dialogue(b)) for b in (0x400000,0x1400000)])
    (ROOT/'reports/friends-fix-20261019/native-friends.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
