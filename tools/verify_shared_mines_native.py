"""Bounded original x86 mining/currency ABI proof; no network or native UI actions."""
import argparse
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'),str(ROOT)]
from verify_auth_native import *
from verify_clans_native import builder
from verify_mining_native import run
from verify_warehouse_native import run as warehouse_writer
from tio.protocol.warehouse import WarehouseItem
from tio.protocol.asset_count import AssetCount, encode_asset_count


def mining_values():
    def setup(u):
        put32(u,0xac5f58,DATA+0x2000)
        put32(u,0xac5fe4,DATA+0x3000)
        put32(u,DATA+0x3000,123000)
    output=[]
    for opcode,body,entry,stop,offsets,expected in (
        (0x26,struct.pack('<II',7,3),0x834c5c,0x834c8a,(0x18,0x1c),(7,3)),
        (0x27,struct.pack('<II',6,4),0x834c90,0x834cbe,(0x20,0x24),(6,4)),
        (0x2b,struct.pack('<I',3600),0x8350dc,0x835102,(0x28,),(3723000,)),
    ):
        packet=bytes((0xb0,opcode))+body
        u=run(packet,entry,stop,setup,(0x814b18,))
        values=tuple(get32(u,DATA+0x2000+i) for i in offsets)
        assert values==expected,values
        output.append(dict(opcode=hex(opcode),payload_bytes=len(body),reader=hex(entry),values=values))
    return output


def crystal_sources():
    """Execute918390 with three currency records including template51."""
    u=emulator();array=DATA+0x2000;pet=DATA+0x4000;closure=DATA+0x5000;seen=[]
    put32(u,pet+0x6c,array);put32(u,closure+0xc,DATA+0x6000)
    records=((0xffff0001,1,500),(0xffff0002,2,100),(0xffff0033,51,77))
    for index,(identity,template,amount) in enumerate(records):
        base=array+index*656
        put32(u,base+0x28,identity);put32(u,base+8,template);put32(u,base+0x1c,amount)
    def hook(uc,address,size,user):
        eax=uc.reg_read(UC_X86_REG_EAX);edx=uc.reg_read(UC_X86_REG_EDX)
        if address==0x40d70c:put32(uc,eax,array);return_from_stub(uc)
        elif address==0x40cc38:uc.mem_write(eax,bytes(uc.mem_read(edx,656)));return_from_stub(uc)
        elif address==0x40d380:uc.reg_write(UC_X86_REG_EAX,3);return_from_stub(uc)
        elif address==0x917690:
            seen.append((uc.reg_read(UC_X86_REG_ECX)&255,get32(uc,edx+0x28),get32(uc,edx+8),get32(uc,edx+0x1c)))
            return_from_stub(uc)
        elif address in (0x40c8cc,0x40d6c8,0x40c9f4):return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_EAX,closure);u.reg_write(UC_X86_REG_EDX,pet)
    u.emu_start(0x918390,STOP,count=10000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert seen==[(5,*r) for r in records],seen
    return dict(entry='918390',records=seen,allocation_and_UI_stubs=True)


def mining_battle_flags():
    output=[]
    for value in (0,1):
        def setup(u):
            put32(u,0xac5834,DATA+0x1000);put32(u,0xac6590,DATA+0x2000)
        u=run(bytes((0xb2,0x0a,value)),0x9622c8,0x9622e9,setup)
        assert bytes(u.mem_read(DATA+0x2000,1))==bytes((value,))
        output.append(dict(opcode='b20a',reader='9622c8',payload_bytes=1,saved=value))
        def exit_setup(u):
            put32(u,0xac5dc0,DATA+0x1000);put32(u,DATA+0x1000,0xffffffff)
        run(bytes((0xb2,0x16,value)),0x95e3a0,0x95e49e,exit_setup,(0x43afc0,0x43b1dc,0xa88a78))
        output.append(dict(opcode='b216',reader='95e3a0',payload_bytes=1,consumed=True,
                           native_UI_event_stubs=True))
    return output


def crystal_wallet_sync():
    """Real65802C/7D4C28 sync template51 from personal AssetCount field5."""
    u=emulator();obj=DATA+0x2000;character=DATA+0x4000;pet=DATA+0x7000;array=DATA+0x9000
    packet=encode_asset_count(AssetCount(500,100,spectra_crystals=77))
    u.mem_write(DATA,packet[2:]);put32(u,0xacd0e8,DATA)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x65802c,STOP,count=5000)
    put32(u,0xac5b7c,character);put32(u,0xac55cc,DATA+0x6000)
    put32(u,DATA+0x6000,DATA+0x8000);put32(u,0xac618c,DATA+0x6500)
    put32(u,DATA+0x6500,pet);u.mem_write(pet+0x43,b'\1');put32(u,pet+0x6c,array)
    put32(u,array-4,1);put32(u,array+8,51);put32(u,array+0x1c,999)
    u.mem_write(0xac4754,b'\0')
    def hook(uc,address,size,user):
        if address==0x7d8acc:uc.reg_write(UC_X86_REG_EAX,0xffffffff);return_from_stub(uc)
        elif address in (0x91453c,0x914540,0x974730,0x70a78c):return_from_stub(uc)
        elif address in (0xa7b3f0,0xa7b8c0):uc.reg_write(UC_X86_REG_EAX,0);return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX,obj);u.emu_start(0x7d4c28,STOP,count=7000)
    assert u.reg_read(UC_X86_REG_EIP)==STOP
    assert get32(u,array+0x1c)==get32(u,character+0x240)==77
    return dict(reader='65802c',consumer='7d4c28',crystal_branch='7d4e58',template=51,count=77)


def verify():
    item=ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot().find("item[@id='51']")
    assert item is not None and item.attrib['name']=='Crystals'
    requests=[]
    for role in (1,2,3):
        packet=builder(0x834660,a=0xaabbcc00|role)
        assert packet==bytes((0xb0,0x28,role))
        requests.append(dict(builder='834660',role=role,packet=packet.hex(),upper_argument_bytes_ignored=True))
    return dict(passed=True,sha256=EXPECTED_SHA,kind=__doc__,mining_rating_requests=requests,
        mining_readers=mining_values(),mining_battle_flags=mining_battle_flags(),
        crystal_sources=crystal_sources(),wallet_sync=crystal_wallet_sync(),
        safe_writer=warehouse_writer(2,1,0,(WarehouseItem(0xffff0033,51,77,0,0,0),)),
        limits=['Original writers/readers and numeric cache execute; allocation/UI callbacks are stubbed.',
                'No rendered clan-safe screen or graphical-user action is asserted.',
                'B0/28 role rating request is not checkpoint ownership or claim.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/shared-mines/native-abi.json')
    args=parser.parse_args();target=args.output.resolve()
    if target.parent!=ROOT/'reports/shared-mines' or target.exists():raise ValueError('Fresh shared-mines report required')
    result=verify();target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as out:out.write(json.dumps(result,indent=2)+'\n')
    print('Original mining readers and template51 clan-safe serializer/cache: PASS')


if __name__=='__main__':main()
