"""Execute original decrease GUI callbacks and original chat21 serialization.

Only Delphi managed-string allocation/concatenation and transport acquisition/
flush are isolated. GUI index->English skill, mercenary-name selection, UTF16
bytes and original u8/string writers execute from pinned original silver.dll.
No client DLL or published manifest is modified.
"""
from verify_auth_native import *
from tio.protocol.proficiency_decrease import ProficiencyDecrease,encode_proficiency_decrease,decode_proficiency_decrease

SKILLS=('melee','light','heavy','distance','automatic','throwing','mines')


def wide(u,address,text):
    raw=text.encode('utf-16-le');put32(u,address-4,len(raw));u.mem_write(address,raw+b'\0\0')


def read_wide(u,address):
    words=[]
    for index in range(256):
        word=bytes(u.mem_read(address+2*index,2))
        if word==b'\0\0':return b''.join(words).decode('utf-16-le')
        words.append(word)
    raise AssertionError('Native command string lacks terminator')


def ui_case(name,index,*,button=False):
    u=emulator();actor=DATA+0x1000;record=DATA+0x4000
    put32(u,0xac64b4,DATA+0x3000);put32(u,0xac618c,DATA+0x2000);put32(u,DATA+0x2000,actor)
    put32(u,0xad11d0,index+4);wide(u,DATA+0x7000,name);put32(u,actor+0x5ff4,DATA+0x7000)
    put32(u,record+0xc,DATA+0x5000);wide(u,DATA+0x6000,SKILLS[index]);put32(u,DATA+0x5000+0x14,DATA+0x6000)
    captured=[]
    def hook(uc,address,size,user):
        if address==0x40c0d8:  # ShortString -> managed WideString.
            source=uc.reg_read(UC_X86_REG_EDX);length=bytes(uc.mem_read(source,1))[0]
            text=bytes(uc.mem_read(source+1,length)).decode('cp1251')
            wide(uc,DATA+0x8100,text);put32(uc,uc.reg_read(UC_X86_REG_EAX),DATA+0x8100);return_from_stub(uc)
        elif address==0x40c244:
            sp=uc.reg_read(UC_X86_REG_ESP);count=uc.reg_read(UC_X86_REG_EDX)
            parts=[read_wide(uc,get32(uc,sp+4+4*i)) for i in range(count)]
            wide(uc,DATA+0x8200,''.join(reversed(parts)));put32(uc,uc.reg_read(UC_X86_REG_EAX),DATA+0x8200)
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+count*4)
        elif address==0x40c05c:
            put32(uc,uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX));return_from_stub(uc)
        elif address==0x9ff3e4:
            captured.append(read_wide(uc,uc.reg_read(UC_X86_REG_EDX)))
            assert uc.reg_read(UC_X86_REG_EAX)==0 and uc.reg_read(UC_X86_REG_ECX)==0
            return_from_stub(uc)
        elif address in (0x40b09c,0x40b0e4,0x40b0fc):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,record)
    u.emu_start(0x9ab108 if button else 0x9b8554,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=f'/decreaseability {name} {SKILLS[index]}'
    assert captured==[expected],captured
    packet=writer_case(u,expected)
    assert decode_proficiency_decrease(packet)==ProficiencyDecrease(name,SKILLS[index])
    return {'name':name,'skill':SKILLS[index],'entry':hex(0x9ab108 if button else 0x9b8554),'packet_hex':packet.hex()}


def writer_case(u,text):
    obj,handle,vt,flush=DATA+0x9000,DATA+0xb000,DATA+0xb100,DATA+0xb200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush);put32(u,0xac600c,handle)
    wide(u,DATA+0xc000,text)
    frame=STACK+0x7000;put32(u,frame-4,DATA+0xc000);put32(u,frame-8,0);u.mem_write(frame-0x15,b'\0')
    u.reg_write(UC_X86_REG_ESP,STACK+0x6000);u.reg_write(UC_X86_REG_EBP,frame)
    result=[]
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (0x40b1a0,0x40b180,0x40b0e4,0x40b09c):return_from_stub(uc)
        elif address==flush:
            result.append(bytes(uc.mem_read(obj+4,get32(uc,obj+0x1004))));return_from_stub(uc)
    token=u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0x9ff6f8,0x9ff739,count=10000)
    u.hook_del(token)
    expected=b'\x21\0'+text.encode('utf-16-le')+b'\0\0'
    assert result==[expected],result
    return result[0]


if __name__=='__main__':
    cases=[ui_case('Alice Prime',index) for index in range(7)]
    cases.append(ui_case('Иван Петров',0,button=True))
    (ROOT/'evidence/proficiency_decrease_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n',encoding='utf-8')
    print('Original GUI decrease + native chat21:8 cases PASS; name/7skills/Unicode serialized')
