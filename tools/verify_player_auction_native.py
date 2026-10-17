"""Original auction readers with managed allocation/string stubs only."""
from verify_auth_native import *
from tio.protocol.player_auction import write_lot
from tio.protocol.binary import Writer
from tio.protocol.item_list import ItemRecord


def settings_reader():
    from tio.protocol.player_auction import encode_settings
    packet=encode_settings(1800000000,5)
    u=emulator();u.mem_write(DATA,packet);put32(u,0xacd0e8,DATA+2)
    obj=DATA+0x2000
    def hook(uc,addr,size,user):
        if addr in (0x6530b0,0x653254,0x6539f0):
            assert uc.reg_read(UC_X86_REG_EDX)==0
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x651fec,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,0xacd0e8)-DATA==len(packet)
    assert get32(u,obj+0x88)==1800000000
    assert bytes(u.mem_read(obj+0x9d,1))==b'\x01'
    assert get32(u,obj+0xa0)==5
    from tio.battle_recovery import CREDITS_PER_HP
    tariff=struct.unpack('<f',u.mem_read(obj,4))[0]
    assert tariff==CREDITS_PER_HP
    return {'bytes':len(packet),'heal_price':tariff,'auction_enabled':True,'pledge_percent':5,'utc':1800000000}


def lot_reader(row, items):
    w=Writer();write_lot(w,row,items);packet=w.build()
    u=emulator();u.mem_write(DATA,packet);put32(u,0xacd0e8,DATA)
    obj=DATA+0x2000
    heap=DATA+0x4000
    def allocate(n):
        nonlocal heap
        p=heap;heap+=(n+31)&~15
        if heap>=DATA+0xf000:raise RuntimeError('Probe heap exhausted')
        return p
    def hook(uc,addr,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if addr==0x62b224:
            put32(uc,eax+0x138,allocate(edx*28));put32(uc,eax+0x13c,edx)
            put32(uc,eax+0x140,allocate(edx));return_from_stub(uc)
        elif addr in (0x6297e0,0x629860):
            cursor=get32(uc,0xacd0e8); unit=1 if addr==0x6297e0 else 2
            raw=bytearray()
            while True:
                part=bytes(uc.mem_read(cursor,unit));cursor+=unit
                if part==bytes(unit):break
                raw.extend(part)
            p=allocate(len(raw)+8)
            if unit==1:uc.mem_write(p,bytes([len(raw)])+bytes(raw))
            else:uc.mem_write(p,bytes(raw)+bytes(2))
            put32(uc,edx,p);put32(uc,0xacd0e8,cursor);return_from_stub(uc)
        elif addr==0x40c06c:
            n=bytes(uc.mem_read(edx,1))[0];uc.mem_write(eax,bytes(uc.mem_read(edx,n+1)));return_from_stub(uc)
        elif addr==0x40b47c:
            put32(uc,eax,edx);return_from_stub(uc)
        elif addr==0x40b0fc:
            return_from_stub(uc)
        elif addr in (0x40a718,0x42ad7c):
            raise AssertionError(f'Original reader raised at {addr:x}')
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,obj)
    u.emu_start(0x62a79c,STOP,count=40000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,0xacd0e8)-DATA==len(packet),(get32(u,0xacd0e8)-DATA,len(packet))
    assert get32(u,obj)==row['id']
    assert get32(u,obj+0x13c)==len(items)
    p=get32(u,obj+0x138)
    for n,item in enumerate(items):
        assert get32(u,p+n*28)==item.template_id
        assert get32(u,p+n*28+8)==item.count
    if row['bidder']:
        assert get32(u,obj+0x144+0x104)==row['bid']
        assert get32(u,obj+0x144+0x10c)==row['bid_index']
    assert bytes(u.mem_read(obj+0x259,1))[0]==(1 if row['state']=='active' else 2 if row['state']=='cancelled' else 3)
    return {'bytes':len(packet),'items':len(items),'bid':row['bidder'] is not None,'state':row['state']}


if __name__=='__main__':
    row=dict(id=77,ends=1800000000,starts=1799956800,seller_name='Продавец',description='Броня +2',
             price=1000,step=100,buyout=5000,bidder=None,bidder_name=None,bid=0,bid_index=0,state='active')
    item=ItemRecord(1,21,bytes(2),2,0,0,(20,30,40),bytes(4),None,bytes((2,3,1)))
    results=[lot_reader(row,(item,))]
    for state in ('active','sold','cancelled'):
        results.append(lot_reader(dict(row,bidder='buyer',bidder_name='Покупатель',bid=1100,bid_index=1,state=state),(item,item)))
    result={'dll_sha256':EXPECTED_SHA,'settings':settings_reader(),'lot_reader':results,'scope':'Native numerical and optional branches; managed strings/allocation stubbed; no GUI validation'}
    (ROOT/'evidence/player_auction_native.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
