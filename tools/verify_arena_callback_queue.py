"""Execute original ti.exe callback71cc6c through queuing of copied packet bytes.
Allocation/list insertion isolated; original copy runs. Queue execution is not tested.
"""
from verify_auth_native import *

if __name__=='__main__':
    path=BINARY.with_name('ti.exe');raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    assert digest=='e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
    u=emulator();u.mem_write(0x400000,pefile.PE(data=raw).get_memory_mapped_image())
    heap=DATA+0x4000;put32(u,0x76e17c,DATA+0x2000);put32(u,DATA+0x2000,DATA+0x2100)
    body=bytes.fromhex(json.loads((ROOT/'evidence/battle_settings_native.json').read_text())['cases'][0]['body_hex'])
    u.mem_write(DATA,body)
    for i,value in enumerate((0x6c,DATA,len(body),0xa0a834)):put32(u,STACK+0x8004+i*4,value)
    result={}
    def hook(uc,addr,size,user):
        global heap
        if addr==0x406a34:
            n=uc.reg_read(UC_X86_REG_EAX);uc.reg_write(UC_X86_REG_EAX,heap);heap+=(n+31)&~15;return_from_stub(uc)
        elif addr==0x4b1c08:
            record=uc.reg_read(UC_X86_REG_EDX)
            result['record_hex']=bytes(uc.mem_read(record,32)).hex()
            result['callback']=hex(get32(uc,record+12))
            result['copied_body_hex']=bytes(uc.mem_read(get32(uc,record+28),len(body))).hex()
            assert result['callback']=='0xa0a834' and result['copied_body_hex']==body.hex()
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x71cc6c,STOP,count=10000)
    assert result
    (ROOT/'evidence/arena_callback_queue_native.json').write_text(json.dumps({'sha256':digest,'method':__doc__,**result},indent=2)+'\n')
    print('ti.exe callback copies BattleSettings body unchanged and queues original reader:PASS')
