"""Execute BattleSettings numeric reader; isolate managed values/strings/UI.
Stop after all packet fields, before follow-up UI. Does not emulate transport callback.
"""
from verify_auth_native import *

if __name__=='__main__':
    cases=[]
    for mode in (0,1,4,16,21):
        u=emulator();settings=DATA+0x3000;heap=DATA+0x4000;result={}
        put32(u,0xac6008,settings)
        for i,addr in enumerate((0xac5f20,0xac5af0,0xac5b7c,0xac63b4,0xac638c,0xac6294)):
            put32(u,addr,DATA+0x5000+i*0x300)
        body=struct.pack('<IBBHB',123,2,mode,301,4)+b'Owner\0'+bytes([5,6,7,8,9])+struct.pack('<IB',456,1)
        if mode==16:body+=bytes([1,0,1,0])+struct.pack('<HH',100,200)
        u.mem_write(DATA,body)
        def hook(uc,addr,size,user):
            eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
            if addr==0x605f1c:
                ptr=get32(uc,eax);raw=bytes(uc.mem_read(ptr,256)).split(b'\0',1)[0]
                put32(uc,eax,ptr+len(raw)+1);put32(uc,edx,heap);return_from_stub(uc)
            elif addr==0x40b47c:put32(uc,eax,edx);return_from_stub(uc)
            elif addr in (0x43afc0,0x94ca14,0x43b1dc,0xa88a78,0x40c0d8,0x40c354):return_from_stub(uc)
            elif addr==0xa0aa6e:
                result['consumed']=get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA;uc.emu_stop()
        u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
        u.emu_start(0xa0a834,STOP,count=5000)
        assert result['consumed']==len(body),result
        assert get32(u,settings+0x40)==123 and get32(u,settings+0x2c)==456
        assert bytes(u.mem_read(settings+0x19,1))[0]==mode
        assert bytes(u.mem_read(settings+0x1d,2))==bytes([5,6])
        if mode==16:
            assert get32(u,settings+0x38)==100 and get32(u,settings+0x3c)==200
        result.update(mode=mode,body_hex=body.hex(),settings_hex=bytes(u.mem_read(settings,0x44)).hex())
        cases.append(result)
    (ROOT/'evidence/battle_settings_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('BattleSettings original numeric reader:5 modes PASS')
