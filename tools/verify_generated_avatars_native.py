"""Native avatar catalog/category/selection and FC checks; GUI/GPU are stubbed."""
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from deploy import client_generated_avatars as patcher
import verify_avatar_types_native as native
from verify_auth_native import emulator, DATA, STACK, STOP, get32, return_from_stub
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ESP, UC_X86_REG_EIP

FOLDER = ROOT/'reports/generated-avatars-20261013'


def categories_and_selection():
    u = emulator()
    ordinary, premium, record = DATA+0x1000, DATA+0x1100, DATA+0x2000
    def put(at, value):
        u.mem_write(at, struct.pack('<I', value))
    put(0xacd7bc, ordinary)
    put(0xacd7c0, premium)
    routed, selected = [], []
    def ret(uc,result=None):
        return_from_stub(uc)
        if result is not None:uc.reg_write(UC_X86_REG_EAX,result)
    def hook(uc, at, size, user):
        if at == 0x406a50:
            ret(uc,record)
        elif at == 0x6b3724:
            routed.append((uc.reg_read(UC_X86_REG_EAX), get32(uc,uc.reg_read(UC_X86_REG_EDX))))
            return_from_stub(uc)
        elif at == 0x6b32e0:
            assert uc.reg_read(UC_X86_REG_EAX) == ordinary
            ret(uc,record)
        elif at == 0x9b8310:
            ret(uc,0)
        elif at == 0x6abdf8:
            selected.append((uc.reg_read(UC_X86_REG_EAX),uc.reg_read(UC_X86_REG_EDX)))
            return_from_stub(uc)
        elif at == STOP:
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE,hook)
    def execute(address):
        sp=STACK+0x8000
        put(sp,STOP)
        u.reg_write(UC_X86_REG_ESP,sp)
        u.emu_start(address,STOP,count=10000)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        assert u.reg_read(UC_X86_REG_ESP)==sp+4
    for category,identity in ((0,10007),(1,10001)):
        u.mem_write(DATA,struct.pack('<IB3xI',identity,category,0))
        u.reg_write(UC_X86_REG_EAX,DATA)
        u.reg_write(UC_X86_REG_EDX,category)
        execute(0x6aff04)
    assert routed==[(ordinary,10007),(premium,10001)],routed
    # Ordinary gallery tab, selected row zero, an owned actor with city ID7.
    tab,widget,slots,actor=DATA+0x3000,DATA+0x3400,DATA+0x3800,DATA+0x4000
    put(0xacd7e0,tab);u.mem_write(tab+0x280,b'\1')
    put(0xacd7d8,widget);put(widget+0x280,0);put(ordinary+8,1)
    u.mem_write(record,struct.pack('<IB3xI',10012,0,0))
    put(0xac618c,slots);put(slots,actor);put(actor+0x28,7)
    execute(0x6b0614)
    assert selected==[(7,10012)],selected
    return dict(passed=True,ordinary_category_routed=True,premium_category_preserved=True,
                ordinary_install_button_selects_generated_avatar=True,graphical_clients_used=False)


def main():
    native.fx=patcher
    kwargs=dict(source_path=FOLDER/'silver-source.dll',max_avatar=patcher.MAX_AVATAR)
    result=native.run(**kwargs)
    native.run(0x1400000,**kwargs)
    result.update(relocated_image_passed=True,original_catalog=native.original_catalog(),
                  category_and_selection=categories_and_selection())
    (FOLDER/'client-native.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
