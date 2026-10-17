"""Verify Create button interface binding and execute its native callback chain.
Window helpers are recorded/stubbed; this is not a GUI click test.
"""
from verify_auth_native import *
import pefile

p=pefile.PE(str(BINARY))
def read(va,n):return p.get_data(va-0x400000,n)
def word(va):return struct.unpack('<I',read(va,4))[0]
def string(va):
    b=read(va,256);end=next(i for i in range(0,len(b),2) if b[i:i+2]==b'\0\0')
    return b[:end].decode('utf-16le')

if __name__=='__main__':
    assert string(0x876b00)=='mn53'
    assert read(0x87602b,9)==bytes.fromhex('8bd685d2740383eac8')
    table=word(0x874fb0);matches=[]
    for i in range(word(table)):
        entry=table+4+i*28
        if word(entry+20)==0x38:matches.append(word(entry+16))
    assert matches==[0x874bf8]
    assert word(matches[0]+12)==0x874969
    calls=[];u=emulator()
    def hook(uc,addr,size,user):
        if addr in (0x85e488,0xa69ab0,0xa6a2a4,0x85d4c0,0xa6a114):
            calls.append({'helper':hex(addr),'text':string(uc.reg_read(UC_X86_REG_EAX)) if addr in (0xa69ab0,0xa6a2a4,0xa6a114) else None})
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA+0x38)
    u.emu_start(0x874969,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert [x['helper'] for x in calls]==['0x85e488','0xa69ab0','0xa6a2a4','0x85d4c0','0xa6a114']
    result={'sha256':EXPECTED_SHA,'method':__doc__,'label_key':'mn53','binding':'87602b object+38 → interface874bf8 → thunk874969 →87537c →8737f4','calls':calls}
    (ROOT/'evidence/arena_create_ui_binding.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
