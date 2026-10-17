"""Original buy-button writer and subscription-status consumer; UI/transport stubs only."""
from verify_auth_native import *
from tio.premium import OFFERS,encode_purchase
from tio.protocol.asset_count import AssetCount,encode_asset_count


def buy(offer,cost):
    u=emulator();put32(u,0xacd0e0,DATA);put32(u,0xacd0f0,0)
    put32(u,0xacdd08,DATA+0x2000)
    u.mem_write(DATA+0x2280,bytes([int(offer%2==0)]))
    u.mem_write(0xac46ad,bytes([1 if offer<=2 else 3]));put32(u,0xacdd14,cost)
    def hook(uc,address,size,unused):
        if address in (0x629764,0x629938,0x9e58a8):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.emu_start(0x70d520,STOP,count=2000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    packet=bytes(u.mem_read(DATA,get32(u,0xacd0f0)))
    assert packet==encode_purchase(offer,cost)
    return dict(offer=offer,gold=cost,packet=packet.hex())


def status(kind,seconds):
    u=emulator();obj=DATA+0x2000;character=DATA+0x4000
    packet=encode_asset_count(AssetCount(123,456,optional_raw=(seconds,kind) if kind else None))
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x65802c,STOP,count=5000)
    assert get32(u,0xacd0e8)-DATA==len(packet)-2
    for pointer,value in [(0xac5b7c,character),(0xac55cc,DATA+0x6000),(0xac618c,DATA+0x7000),
                          (0xac5b38,DATA+0x8000),(0xac5d10,DATA+0x8100),(0xac55f8,DATA+0x8200),(0xac5794,0xac467c)]:put32(u,pointer,value)
    u.mem_write(DATA+0x8100,struct.pack('<Q',1000));u.mem_write(0xac467c,b'\x03')
    u.mem_write(0xac4754,b'\0')
    def hook(uc,address,size,unused):
        if address==0x7d8acc:uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x91453c,0x914540,0x974730,0x917684):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook)
    u.reg_write(UC_X86_REG_ESP,STACK+0x8000);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x7d4c28,STOP,count=5000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert bytes(u.mem_read(0xac467c,1))==bytes([1 if kind in (1,2) else 3 if kind else 0])
    if kind:assert struct.unpack('<Q',u.mem_read(DATA+0x8200,8))[0]==1000+seconds
    assert get32(u,character+0x234)==456
    return dict(kind=kind,seconds=seconds,packet=packet.hex())


if __name__=='__main__':
    result=dict(sha256=EXPECTED_SHA,purchases=[buy(i,cost) for i,(hours,cost) in OFFERS.items()],
                statuses=[status(k,s) for k,s in [(0,0),(1,86400),(2,2592000),(3,1),(4,2592000)]])
    (ROOT/'evidence/premium_native.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Original premium buy button: 4 cases PASS; status/expiry: 5 cases PASS')
