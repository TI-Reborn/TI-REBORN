"""Original TUnitStatus.DrawEquipStatus sprite/color selection; rendering stubbed."""
from verify_auth_native import *

if __name__ == '__main__':
    cases=[]
    for equip in range(6):
        for injury in (0,1,255):
            u=emulator();unit=DATA+0x2000;calls=[]
            u.mem_write(unit,bytes((1,equip,injury)))
            def hook(uc,address,size,user):
                if address==0x4f27fc:
                    sp=uc.reg_read(UC_X86_REG_ESP)
                    calls.append({'sprite':get32(uc,sp+8),'color':hex(get32(uc,sp+12))})
                    return_from_stub(uc)
                    uc.reg_write(UC_X86_REG_ESP,sp+16)
            u.hook_add(UC_HOOK_CODE,hook)
            u.reg_write(UC_X86_REG_EAX,unit)
            u.emu_start(0xa0fc6c,STOP,count=1000)
            assert u.reg_read(UC_X86_REG_EIP)==STOP
            assert calls==[{'sprite':equip+3 if equip in (1,2,3,4) else 4,
                           'color':'0xffff7777' if injury else '0xffffffff'}]
            cases.append({'equip':equip,'injury':injury,**calls[0]})
    (ROOT/'evidence/unit_status_native.json').write_text(json.dumps({'sha256':EXPECTED_SHA,'method':__doc__,'cases':cases},indent=2)+'\n')
    print('Original unit status: 18 sprite/injury color cases PASS')
