"""Original request builders, empty response writers and wallet wait completion.

UI rendering and clan/mail/mark gameplay are not simulated or certified.
"""
from verify_auth_native import *
from tio.protocol.asset_count import AssetCount,encode_asset_count
from verify_warehouse_native import run as warehouse_writer


def request(entry,expected):
    u=emulator();obj=DATA+0x1000;handle=DATA+0x3000;vt=DATA+0x3100;flush=DATA+0x3200
    put32(u,handle,obj);put32(u,obj,vt);put32(u,vt,flush)
    put32(u,0xac600c,handle);put32(u,0xac55cc,DATA+0x3400)
    def hook(uc,address,size,user):
        if address==0x6748b0:uc.reg_write(UC_X86_REG_EAX,handle);return_from_stub(uc)
        elif address in (flush,0x91759c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(entry,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(obj+4,get32(u,obj+0x1004)))
    assert packet==expected
    return dict(builder=hex(entry),packet=packet.hex())


def empty_writer(entry,expected):
    u=emulator();put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
    u.reg_write(UC_X86_REG_EAX,DATA+0x1000)
    u.emu_start(entry,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
    assert packet==expected
    return dict(writer=hex(entry),packet=packet.hex())


def empty_ranking():
    u=emulator();put32(u,0xac5d2c,DATA+0x1000);seen=[]
    def hook(uc,address,size,user):
        if address==0x40d5a4:
            assert get32(uc,uc.reg_read(UC_X86_REG_ESP)+4)==0
            return_from_stub(uc);uc.reg_write(UC_X86_REG_ESP,uc.reg_read(UC_X86_REG_ESP)+4)
        elif address==0x40b0fc:return_from_stub(uc)
        elif address==0x8a10ec:seen.append(get32(uc,uc.reg_read(UC_X86_REG_EBP)-4)-DATA)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,DATA)
    u.emu_start(0x8a10bc,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP and seen==[4]
    return dict(reader='8a10bc',packet='b80a00000000',consumed=4)


def assets_clear_wait():
    u=emulator();obj=DATA+0x2000;character=DATA+0x4000;warehouse=DATA+0x8000
    packet=encode_asset_count(AssetCount(321,654,spectra_crystals=9))
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x65802c,STOP,count=5000)
    assert get32(u,0xacd0e8)-DATA==len(packet)-2
    put32(u,0xac5b7c,character);put32(u,0xac55cc,DATA+0x6000)
    put32(u,DATA+0x6000,warehouse);put32(u,0xac618c,DATA+0x7000)
    u.mem_write(warehouse+0x3c,b'\x01');put32(u,warehouse+4,12345)
    u.mem_write(0xac4754,b'\0')
    def hook(uc,address,size,user):
        if address==0x7d8acc:uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x91453c,0x914540,0x974730,0x70a78c):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x7d4c28,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,character+0x230)==321 and get32(u,character+0x234)==654
    assert bytes(u.mem_read(warehouse+0x3c,1))==b'\0' and get32(u,warehouse+4)==0
    return dict(reader='65802c',consumer='7d4c28',real_wait_reset='917684',passed=True)


if __name__=='__main__':
    cases=[request(e,bytes.fromhex(p)) for e,p in ((0x8a0f80,'b804'),(0x8a0d9c,'b809'),(0x8a0fb8,'b811'))]
    cases += [empty_writer(0x641740,bytes.fromhex('c82900000000')),
              empty_writer(0x64588c,bytes.fromhex('b77500000000')),empty_ranking(),assets_clear_wait()]
    cases += [warehouse_writer(k,1,0,()) for k in (1,2)]
    (ROOT/'evidence/warehouse_queries_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,
        method=__doc__,cases=cases),indent=2)+'\n')
    print('Original warehouse-related requests/responses: 9 cases PASS')
