"""Local-only original Silver wire proof. No processes, sockets or callbacks.

Numeric readers/writers and opcode dispatch execute unchanged x86 instructions.
Explicit stubs isolate Delphi managed strings/array allocation and UI side effects.
This validates ABI, not rendered GUI behavior or hosted gameplay.
"""
from functools import lru_cache
import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

from verify_auth_native import (
    BINARY, EXPECTED_SHA, ROOT, DATA, STACK, STOP, put32, get32, return_from_stub,
    UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP,
    UC_X86_REG_EBP, UC_X86_REG_EIP,
)
import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
import verify_clans_native as old_clans
from tio.protocol import alliances, assault, clan_ratings


@lru_cache(maxsize=1)
def image():
    raw = BINARY.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA:
        raise RuntimeError('Unrecognized original Silver build')
    return pefile.PE(data=raw).get_memory_mapped_image()


def emulator(mapped=None):
    if mapped is None:
        mapped = image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x1000)
    u.mem_map(0x400000, (len(mapped)+0xfff)&~0xfff)
    u.mem_write(0x400000, mapped)
    u.mem_map(DATA, 0x200000)
    u.mem_map(STACK, 0x10000)
    put32(u, STACK+0x8000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    return u


class ReaderProbe:
    def __init__(self, body):
        self.u = emulator()
        self.body = body
        self.u.mem_write(DATA, body)
        put32(self.u, 0xacd0e8, DATA)
        put32(self.u, 0xacd0e0, DATA+0x10000)
        put32(self.u, 0xacd0f0, 0)
        self.heap = DATA+0x20000
        self.strings = {}
        self.extra_noops = set()
        self.stop_at = None
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def allocate(self, count=1):
        if not 0 <= count <= 64:
            raise AssertionError('Bounded synthetic array allocation violated')
        ptr = self.heap+16
        self.heap += max(1, count)*1024+32
        if self.heap > DATA+0x1f0000:
            raise AssertionError('Bounded synthetic heap exhausted')
        put32(self.u, ptr-4, count)
        return ptr

    def hook(self, u, address, size, unused):
        a = u.reg_read(UC_X86_REG_EAX)
        d = u.reg_read(UC_X86_REG_EDX)
        if address == self.stop_at:
            u.emu_stop()
        elif address == 0x40d5a4:
            count = get32(u, u.reg_read(UC_X86_REG_ESP)+4)
            put32(u, a, self.allocate(count))
            return_from_stub(u)
        elif address in (0x6297ac, 0x605f1c):
            ptr = get32(u, 0xacd0e8) if address == 0x6297ac else get32(u, a)
            raw = bytes(u.mem_read(ptr, 256)).split(b'\0', 1)[0]
            if len(raw) == 256:
                raise AssertionError('Bounded synthetic string violated')
            if address == 0x6297ac:
                put32(u, 0xacd0e8, ptr+len(raw)+1)
            else:
                put32(u, a, ptr+len(raw)+1)
            value = self.allocate()
            u.mem_write(value, bytes([len(raw)])+raw)
            self.strings[value] = raw
            put32(u, d, value)
            return_from_stub(u)
        elif address == 0x629abc:
            raw = self.strings[d]+b'\0'
            count = get32(u, 0xacd0f0)
            u.mem_write(DATA+0x10000+count, raw)
            put32(u, 0xacd0f0, count+len(raw))
            return_from_stub(u)
        elif address == 0x40ce98:
            u.reg_write(UC_X86_REG_EAX,self.allocate())
            return_from_stub(u)
        elif address in (0x40b47c,0x40b4c4):
            put32(u, a, d)
            return_from_stub(u)
        elif address == 0x40c06c:
            n = bytes(u.mem_read(d, 1))[0]
            u.mem_write(a, bytes(u.mem_read(d, n+1)))
            return_from_stub(u)
        elif address in self.extra_noops or address in (
            0x40b09c, 0x40b0fc, 0x40d6c8, 0x40c8cc, 0x40c9a4,
            0x68a094, 0x838274, 0x6d769c,
        ):
            return_from_stub(u)

    def run(self, entry, a=DATA+0x2000, d=0, c=0):
        put32(self.u, STACK+0x8000, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
        for reg, value in ((UC_X86_REG_EAX,a), (UC_X86_REG_EDX,d), (UC_X86_REG_ECX,c)):
            self.u.reg_write(reg, value)
        self.u.emu_start(entry, STOP, count=30000)
        if self.stop_at is None:
            assert self.u.reg_read(UC_X86_REG_EIP) == STOP

    def roundtrip(self, reader, writer, packet):
        self.run(reader)
        assert get32(self.u, 0xacd0e8)-DATA == len(packet)-2
        self.run(writer)
        result = bytes(self.u.mem_read(DATA+0x10000, get32(self.u, 0xacd0f0)))
        assert result == packet, (hex(reader), len(result), len(packet))
        return dict(reader=hex(reader), writer=hex(writer), consumed=len(packet)-2,
                    packet_hex=packet.hex())


def dispatch_cases():
    # Copy only the exact enum assignments from the original unit initializer.
    assignments = re.findall(rb'\xc7\x05(.{4})(.{4})', image()[0xab749c-0x400000:0xab78a2-0x400000], re.S)
    u = emulator()
    for address, value in assignments:
        put32(u, struct.unpack('<I',address)[0], struct.unpack('<I',value)[0])
    def hook(uc, address, size, unused):
        if address == 0x629904:
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    rows = []
    for sub, expected in ((0x24,0x28),(0x25,0x29),(0x26,0x2a),(0x27,0x2b),
                          (0x28,0x2c),(0x2d,0x3c),(0x2e,0x3d),(0x2f,0x3e),
                          (0x31,0x40),(0x32,0x42),(0x34,0x44),(0x36,0x46),(0x38,0x55)):
        u.mem_write(DATA, bytes([0xc8,sub]))
        put32(u,0xacd0e8,DATA)
        put32(u,STACK+0x8000,STOP)
        u.reg_write(UC_X86_REG_ESP,STACK+0x8000)
        u.reg_write(UC_X86_REG_ECX,2)
        u.emu_start(0x65d034,STOP,count=300)
        assert u.reg_read(UC_X86_REG_EIP)==STOP
        result=u.reg_read(UC_X86_REG_EAX)
        assert result==expected,(sub,result)
        rows.append(dict(packet=f'C8/{sub:02X}', internal_type=result))
    return rows


def assault_battle_cases():
    cases = []
    for packet, reader, fields in (
        (assault.encode_flag_status(18.,22.,2),0x64ba14,((0,18.),(8,22.),(0x14,2))),
        (assault.encode_flag_increment(18.,22.,7,2),0x64c118,
         ((0,18.),(8,22.),(0x14,7),(0x1c,2))),
        (assault.encode_battle_count(8,3),0x657da0,((0,8),(8,3))),
    ):
        p=ReaderProbe(packet[2:]);p.run(reader)
        assert get32(p.u,0xacd0e8)-DATA==len(packet)-2
        for offset,expected in fields:
            actual=struct.unpack('<f',p.u.mem_read(DATA+0x2000+offset,4))[0] if isinstance(expected,float) else get32(p.u,DATA+0x2000+offset)
            assert actual==expected,(hex(reader),offset,actual,expected)
        cases.append(dict(reader=hex(reader),packet_hex=packet.hex(),consumed=len(packet)-2))
    packet=assault.encode_flag_points((assault.FlagPoints(1,101,7),assault.FlagPoints(2,83,3)))
    cases.append(ReaderProbe(packet[2:]).roundtrip(0x64be30,0x64be7c,packet))
    win=assault.TeamResult(1,101,12.5,
        (assault.PlayerResult(b'Alice',3,1,12.5),),
        (assault.ClanResult(b'Clan A',17,29,12.5),))
    lose=assault.TeamResult(2,83,4.25,
        (assault.PlayerResult(b'Bob',1,3,4.25),),
        (assault.ClanResult(b'Clan B',31,0,4.25),))
    packet=assault.encode_battle_over(6,win,lose)
    cases.append(ReaderProbe(packet[2:]).roundtrip(0x64fb88,0x64fbbc,packet))
    for zone in (
        assault.ZoneInfo(0,100,None,200,4,6,7,9,3),
        assault.ZoneInfo(2,100,90,200,4,6,7,9,3,300,assault.ClanOwner(17,b'Clan A',b'Alice',29)),
    ):
        body=assault.encode_zone_body(zone);p=ReaderProbe(body);p.run(0x649a44)
        assert get32(p.u,0xacd0e8)-DATA==len(body)
        p.run(0x649b34)
        output=bytes(p.u.mem_read(DATA+0x10000,get32(p.u,0xacd0f0)))
        assert output==body
        cases.append(dict(reader='0x649a44',writer='0x649b34',body_hex=body.hex(),consumed=len(body)))
    for mode in (0,19,20,21,22):
        p=ReaderProbe(b'');put32(p.u,0xac6008,DATA+0x2000)
        p.u.mem_write(DATA+0x2019,bytes((mode,)))
        calls=[]
        def observe(uc,address,size,unused):
            if address==0x78d404:calls.append(address)
        p.u.hook_add(UC_HOOK_CODE,observe)
        p.extra_noops.add(0x78d404);p.stop_at=0x957b4f
        p.run(0x957b3f)
        assert bool(calls)==(mode==assault.BATTLE_MODE)
        cases.append(dict(original_branch='0x957b3f',mode=mode,assault4_hud=bool(calls),
                          hud='0x78d404',namespace='game_Assault_v4'))
    return cases


def clan_projection_cases():
    cases=[]
    for kind in (0,1,2):
        for selector in (0,1):
            row=clan_ratings.ClanRating(17,b'Clan A',b'Alice',3,10,1,901,
                crest_id=29,alliance_crest_id=31,unknown_u32_3=41,unknown_u32_4=43)
            packet=clan_ratings.encode_ratings(kind,selector,(row,));p=ReaderProbe(packet[1:])
            arrays=(0xac6580,0xac54e0,0xac6060,0xac63c8,0xac6474,0xac5eac)
            for index,global_ptr in enumerate(arrays):put32(p.u,global_ptr,DATA+0x18000+index*16)
            p.stop_at=0x6e70b2;p.run(0x6e6ef0,a=DATA)
            assert get32(p.u,p.u.reg_read(UC_X86_REG_EBP)-4)-DATA==len(packet)-1
            ptr=get32(p.u,DATA+0x18000+(selector*3+kind)*16)
            assert (get32(p.u,ptr),get32(p.u,ptr+0x20c),get32(p.u,ptr+0x214),
                    get32(p.u,ptr+0x210),get32(p.u,ptr+0x220),get32(p.u,ptr+0x224))==(17,29,901,31,41,43)
            cases.append(dict(reader='0x6e6ef0',kind=kind,selector=selector,
                              clan_crest=29,influence=901,alliance_crest=31,consumed=len(packet)-1))
    member=alliances.AllianceMember(b'Alice',1,4,73)
    clan=alliances.AllianceClan(17,b'Clan A',1,901,b'Alice',(member,),29,0)
    info=alliances.AllianceInfo(123,b'Alliance A',1,17,901,0,(clan,),0,1)
    packet=alliances.encode_info(info);p=ReaderProbe(packet[2:])
    char=DATA+0x4000;put32(p.u,0xac5b7c,char);put32(p.u,char+0x4e0,DATA+0x8000)
    put32(p.u,0xac62dc,DATA+0x9000);put32(p.u,DATA+0x9000,DATA+0xa000)
    put32(p.u,DATA+0xa000+0x2a0,DATA+0xb000)
    p.extra_noops.update((0xa10b14,0xa4a2c8,0xa88908,0x4244dc,0x40c244,
                         0xa49b7c,0xa10324,0x6d4e48))
    rows=[]
    def observe(uc,address,size,unused):
        if address==0xa10324:
            base=uc.reg_read(UC_X86_REG_EDX)
            rows.append((get32(uc,base+0xc),get32(uc,base+8),get32(uc,base+0x14)))
    p.u.hook_add(UC_HOOK_CODE,observe);p.stop_at=0x6e18a5;p.run(0x6e1414,a=DATA)
    assert get32(p.u,p.u.reg_read(UC_X86_REG_EBP)-0x1c8)-DATA==len(packet)-2
    assert (get32(p.u,char+0x4b0),get32(p.u,char+0x4c4),get32(p.u,char+0x4d0))==(17,0,901)
    assert rows==[(17,29,901)],rows
    assert p.strings[get32(p.u,char+0x4bc)]==b'Alice'
    cases.append(dict(reader='0x6e1414',consumed=len(packet)-2,leading_clan=17,
                      independent_storage_id=123,alliance_crest=0,clan_crest=29,influence=901))
    packet=alliances.encode_ratings((info,));p=ReaderProbe(packet[2:])
    put32(p.u,0xac5f70,DATA+0x18000);p.run(0x6e1a58,a=DATA)
    ptr=get32(p.u,DATA+0x18000)
    assert (get32(p.u,ptr),get32(p.u,ptr+0x14),get32(p.u,ptr+0x20))==(17,0,901)
    assert struct.unpack('<H',p.u.mem_read(ptr+0x24,2))[0]==1
    assert p.strings[get32(p.u,ptr+0x28)]==b'Clan A'
    cases.append(dict(reader='0x6e1a58',leading_clan=17,clan_count=1,leading_clan_name='Clan A'))
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/stage6/native-wire.json')
    args=parser.parse_args()
    # Use one parsed immutable image, rather than reparsing Silver per case.
    old_clans.emulator=emulator
    cases=[]
    for entry,a,d,expected in (
        (0x6e70e0,2,1,b'\x82\x02\x01'),
        (0x6e110c,0,0,b'\xaf\x01Bob\0'),
        (0x6e1208,0,0,b'\xaf\x02Bob\0'),
        (0x6e1178,1,0,b'\xaf\x04\1'),
        (0x6e11dc,0,0,b'\xaf\x08'),
        (0x6e107c,0x10203040,0,b'\xaf\x09'+struct.pack('<I',0x10203040)),
        (0x6e10e0,0,0,b'\xaf\x0a'),
        (0x6e1274,0x10203040,0,b'\xaf\x0b'+struct.pack('<I',0x10203040)),
        (0x6e11b0,0,0,b'\xaf\x0c'),
        (0x6e10b4,0,0,b'\xaf\x0e'),
    ):
        packet=old_clans.builder(entry,a,d)
        assert packet==expected
        cases.append(dict(builder=hex(entry),packet_hex=packet.hex()))
    for operation,entry,value in (
        (0x1d,0x63916c,None),(0x1e,0x639198,0x12345678),
        (0x1f,0x639220,None),(0x20,0x63924c,0x12345678),
        (0x21,0x6392d8,1),(0x22,0x639360,None),(0x23,0x639384,None),
    ):
        p=ReaderProbe(b'')
        if value is not None:
            put32(p.u,DATA+0x2000,value)
            p.u.mem_write(DATA+0x2000+(1 if operation==0x21 else 4),b'\1')
        p.run(entry)
        packet=bytes(p.u.mem_read(DATA+0x10000,get32(p.u,0xacd0f0)))
        assert packet==assault.encode_request(operation,value)
        cases.append(dict(builder=hex(entry),packet_hex=packet.hex()))
    pet=assault.RoomPet(4,17,3,b'Merc',115,7,2,1,0)
    cells=(assault.RoomCell(101,b'Alice',4,17,1,(pet,),1),
           assault.RoomCell(202,b'Bob',4,0,0,(pet,),0))
    packet=assault.encode_room_info(19,cells,0)
    cases.append(ReaderProbe(packet[2:]).roundtrip(0x63a494,0x63a500,packet))
    for clan_crest,alliance_crest in ((None,None),(17,None),(17,29)):
        item=assault.RoomListItem(19,b'Alice',clan_crest,alliance_crest,4,2,1)
        packet=assault.encode_room_list((item,))
        # Verify the element decoder; list prefixes are original writer63b080.
        p=ReaderProbe(packet[6:]);p.run(0x63aa10)
        assert get32(p.u,0xacd0e8)-DATA==len(packet)-6
        assert get32(p.u,DATA+0x2000)==19
        assert bytes(p.u.mem_read(DATA+0x2000+0x1d,1))==b'\4'
        assert bytes(p.u.mem_read(DATA+0x2000+0x1f,1))==b'\2'
        cases.append(dict(reader='0x63aa10',consumed=len(packet)-6,packet_hex=packet.hex()))
    cases.extend(assault_battle_cases())
    cases.extend(clan_projection_cases())
    dispatch=dispatch_cases()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(passed=True,sha256=EXPECTED_SHA,
        method=__doc__,cases=cases,dispatch=dispatch,
        limitations=['Explicit managed strings, allocation and UI stubs',
                     'No rendered GUI or hosted gameplay validation']),indent=2)+'\n',encoding='utf8')
    print(f'Original clan/alliances/Assault4 ABI: {len(cases)} cases + {len(dispatch)} dispatcher cases PASS')


if __name__=='__main__':
    main()
