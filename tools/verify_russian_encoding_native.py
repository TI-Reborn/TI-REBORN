"""Execute the original/patched Delphi codepage initialization in Unicorn.

The original GetACP import is stubbed to simulate host ACP1252/65001/1251.
Patched MOV and the original global-store instruction run unchanged.
This verifies initialization, not live tooltip rendering.
"""
from verify_auth_native import *
from deploy.client_russian_encoding import PATCHED


def run(host,patched):
    u=emulator()
    if patched:u.mem_write(0xab6090,PATCHED)
    def hook(uc,address,size,user):
        if address==0x404c4c:
            uc.reg_write(UC_X86_REG_EAX,host);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.emu_start(0xab6090,0xab609a,count=30)
    value=get32(u,0xac7900)
    assert value==(1251 if patched else host)
    return {'host':host,'patched':patched,'runtime_codepage':value}


if __name__=='__main__':
    cases=[run(host,patched) for host in (1252,65001,1251) for patched in (False,True)]
    result={'source_sha256':EXPECTED_SHA,'method':__doc__,'cases':cases,'status':'PASS'}
    (ROOT/'evidence/russian_encoding_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Native Delphi initialization: 6 codepage cases PASS')
