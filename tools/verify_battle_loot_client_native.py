"""Execute original transfer predicate with the release hook and catalog checks."""
from verify_auth_native import *
from deploy.client_battle_loot import patch,HOOK,RVA


def run(*,client_patch=patch,own_exchange=False):
    final=client_patch(BINARY.read_bytes());assert client_patch(final)==final
    pe=pefile.PE(data=final);mapped=pe.get_memory_mapped_image();cases=[]
    for battle in (0,1):
        for mode in (0,1,2):
            for marked in (0,1):
                for name,durability,weapon,body in (('ammo',0,0,0),('uzi',300,4,0),('armor',100,0,1)):
                    u=emulator();u.mem_map(0x400000+RVA,0x1000);u.mem_write(0x400000,mapped)
                    item=DATA+0x1000;meta=DATA+0x4000
                    for pointer,target,value in ((0xac64a0,DATA+0x100,battle),(0xac5f18,DATA+0x104,mode)):
                        put32(u,pointer,target);put32(u,target,value)
                    put32(u,0xac637c,DATA+0x108);put32(u,DATA+0x108,meta)
                    put32(u,item+8,304 if name=='uzi' else 202)
                    u.mem_write(item+0x48,struct.pack('<H',durability));u.mem_write(item+0x58,bytes((marked,)))
                    u.mem_write(meta+0x3a5d,b'\1');u.mem_write(meta+0x12c,bytes((weapon,body)))
                    def hook(uc,addr,size,user):
                        if addr==0xa7b030:uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
                    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,item)
                    u.emu_start(HOOK,STOP,count=3000)
                    assert u.reg_read(UC_X86_REG_EIP)==STOP
                    allowed=bool(u.reg_read(UC_X86_REG_EAX)&255)
                    expected=name=='ammo' or (battle==1 and mode==0 and not marked) or (own_exchange and battle==1 and mode==1)
                    assert allowed==expected,(name,battle,mode,marked,allowed)
                    cases.append(dict(item=name,battle=battle,mode=mode,marked=marked,allowed=allowed))
    return dict(sha256=hashlib.sha256(final).hexdigest(),cases=cases,
                limitation='Native predicate and hook executed; graphics and live mouse input not exercised.')


if __name__=='__main__':
    result=run()
    (ROOT/'reports/ui-four-regressions/client-native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Release ground transfer predicate:',len(result['cases']),'cases PASS')
