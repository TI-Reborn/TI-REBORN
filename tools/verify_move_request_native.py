"""Original ti.exe6dc460 C2S3C writer; transport/critical sections isolated."""
from verify_battle_loaded_native import *
from tio.protocol.battle_move import BattleMove, encode_move_request


def run(path, disabled=False):
    u=exe_emulator();sent=[]
    put32(u,0x76e224,DATA+0x1000)
    u.mem_write(DATA+0x1000,bytes((int(disabled),)))
    for n,(x,y) in enumerate(path):
        put32(u,DATA+n*8,x);put32(u,DATA+n*8+4,y)
    def hook(uc,a,size,user):
        if a in (0x41389c,0x413b18):
            sp=uc.reg_read(UC_X86_REG_ESP);return_from_stub(uc)
            uc.reg_write(UC_X86_REG_ESP,sp+8)
        elif a in (0x71944c,0x718e68):
            sent.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)&65535)))
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_EAX,17);u.reg_write(UC_X86_REG_EDX,DATA)
    u.reg_write(UC_X86_REG_ECX,len(path)-1)
    u.emu_start(0x6dc460,STOP,count=3000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    expected=encode_move_request(BattleMove(17,tuple(path)))
    assert sent==([] if disabled else [expected,expected]),sent
    return dict(path=path,disabled=disabled,packets_hex=[p.hex() for p in sent])


if __name__=='__main__':
    cases=[run([(3,2)]),run([(3,2),(4,2),(4,3)]),run([(0,255)]),run([(3,2)],True)]
    (ROOT/'evidence/move_request_native.json').write_text(json.dumps(
        dict(sha256=EXE_SHA,method=__doc__,cases=cases,
             abi='EAX actor, EDX array of int32 coordinate pairs, ECX high index (count-1)'),
        indent=2)+'\n',encoding='utf-8')
    print('Original movement request3C:4 cases PASS')
