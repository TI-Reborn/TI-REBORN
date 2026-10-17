"""Execute legacy list decoding, level projection, colours and join in x86.

Runs the production Silver at preferred and relocated bases, with allocation,
managed-string storage, collection access and GUI/transport calls isolated.
The numeric reader/getters, level-range projection, roster scan, patched
eligibility predicate, native colour blend and join packet writers execute.
This is offline native-code verification, not a graphical-client test.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX,
                               UC_X86_REG_EBP, UC_X86_REG_ESP, UC_X86_REG_EIP)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_team_lobby_availability as patcher
from tio.protocol.wagers import WagerRoomRecord, encode_room_list

DATA = 0x2000000
ACTORS = 0x2100000
STACK = 0x3000000
STOP = STACK + 0x100
DEFAULT_SOURCE = ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/client/source/silver.dll'


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def ret(u, extra=0):
    sp = u.reg_read(UC_X86_REG_ESP)
    u.reg_write(UC_X86_REG_EIP, get(u, sp))
    u.reg_write(UC_X86_REG_ESP, sp + 4 + extra)


@lru_cache(maxsize=2)
def mapped_image(raw, base):
    p = pefile.PE(data=raw)
    try:
        if base != patcher.IMAGE_BASE:
            p.relocate_image(base)
        image = p.get_memory_mapped_image()
    finally:
        p.close()
    return image


def emulator(raw, base):
    image = mapped_image(raw, base)
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x1000)
    u.mem_map(base, (len(image) + 0xfff) & ~0xfff)
    u.mem_write(base, image)
    u.mem_map(DATA, 0x10000)
    u.mem_map(ACTORS, 0x100000)
    u.mem_map(STACK, 0x10000)
    restart(u)
    return u


def restart(u):
    put(u, STACK + 0x8000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)


def run(u, entry, base, count=100000):
    restart(u)
    u.emu_start(entry + base - patcher.IMAGE_BASE, STOP, count=count)
    assert u.reg_read(UC_X86_REG_EIP) == STOP, hex(u.reg_read(UC_X86_REG_EIP))
    assert u.reg_read(UC_X86_REG_ESP) == STACK + 0x8004, 'Native stack ABI changed'


def read_and_project(raw, base, record):
    """Original 647450 packet reader plus original A08DE0 row projection."""
    u = emulator(raw, base); delta = base - patcher.IMAGE_BASE
    packet = encode_room_list((record,))
    u.mem_write(DATA, packet[6:]); put(u, 0xacd0e8 + delta, DATA)
    item = DATA + 0x4000; row = DATA + 0x7000; name = DATA + 0x6000
    captured = {}

    def hook(uc, address, size, unused):
        original = address - delta
        a, d, c = (uc.reg_read(reg) for reg in
                   (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
        if original == 0x6297ac:
            cursor = get(uc, 0xacd0e8 + delta)
            length = int.from_bytes(uc.mem_read(cursor, 2), 'little')
            value = bytes(uc.mem_read(cursor + 2, length))
            assert value == record.creator_name
            put(uc, 0xacd0e8 + delta, cursor + 2 + length)
            wide = value.decode('cp1251').encode('utf-16-le')
            put(uc, name - 4, len(wide) // 2); uc.mem_write(name, wide + b'\0\0')
            put(uc, d, name); captured['creator_text'] = value.decode('cp1251'); ret(uc)
        elif original in (0x40b47c, 0x40b4c4, 0x40b4f0, 0x40c048, 0x40c05c):
            put(uc, a, d); ret(uc)
        elif original in (0x40b09c, 0x40b0fc, 0x40b0e4, 0x40c8cc, 0x40c9a4):
            ret(uc)
        elif original == 0x648214:
            uc.reg_write(UC_X86_REG_EAX, 1); ret(uc)
        elif original == 0x6480f0:
            uc.mem_write(c, bytes(uc.mem_read(item, 0x50))); ret(uc)
        elif original == 0x4244b4:
            put(uc, d, name); ret(uc)
        elif original == 0x40c244:
            put(uc, a, name); ret(uc, d * 4)
        elif original == 0x66754c:
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x872f7c:
            uc.mem_write(row, bytes(uc.mem_read(a, 0x30)))
            captured['projected'] = True; ret(uc)

    token = u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, item); run(u, 0x647450, base)
    assert get(u, 0xacd0e8 + delta) - DATA == len(packet) - 6
    u.reg_write(UC_X86_REG_EAX, DATA + 0x8000); run(u, 0xa08de0, base)
    u.hook_del(token)
    assert captured.get('projected'), 'Typed main list failed to produce a row'
    fields = {'identity': get(u, row), 'mode': u.mem_read(row + 0x10, 1)[0],
              'min_level': u.mem_read(row + 0x1a, 1)[0],
              'max_level': u.mem_read(row + 0x1b, 1)[0],
              'capacity': u.mem_read(row + 0x1c, 1)[0],
              'members': u.mem_read(row + 0x1d, 1)[0],
              'status': u.mem_read(row + 0x1e, 1)[0]}
    minimum = max(1, record.creator_level-record.level_delta)
    maximum = min(20, record.creator_level+record.level_delta)
    if record.mode in (1, 4) and record.stake == 0 and (minimum, maximum) == (6, 10):
        minimum = 7
    assert fields == dict(identity=record.identity, mode=record.mode,
                          min_level=minimum,
                          max_level=maximum,
                          capacity=record.capacity, members=record.members, status=record.status)
    return u, row, dict(packet_hex=packet.hex(), **captured, **fields)


def colour_case(raw, base, record, roster, *, expected_eligible, followup_ordinary=False):
    u, row, proof = read_and_project(raw, base, record)
    delta = base - patcher.IMAGE_BASE
    flags = DATA + 0x1300; listing = DATA + 0x1500; selected_party = DATA + 0x1700
    slots = DATA + 0x2000
    for global_address, ptr in ((0xac5900, flags), (0xacf394, listing),
                                (0xac5d58, selected_party), (0xac618c, slots)):
        put(u, global_address + delta, ptr)
    put(u, flags, 0x3c)  # Team/Wall/ordinary mode filters enabled; running filter off.
    put(u, listing + 8, 0); put(u, selected_party, 0)
    if followup_ordinary:
        u.mem_write(row + 0x100, bytes(u.mem_read(row, 0x30)))
        u.mem_write(row + 0x110, b'\0')
    before = []
    for index, fighter in enumerate(roster):
        if fighter is None:
            continue
        level, selected, populated = fighter
        actor = ACTORS + index * 0x7000
        put(u, slots + index * 4, actor)
        u.mem_write(actor + 0x41, bytes((int(populated),)))
        u.mem_write(actor + 0x5ff1, bytes((selected,)))
        put(u, actor + 0x5ffc, level)
        before.append((actor, bytes(u.mem_read(actor, 0x6100))))
    tick = 0

    def hook(uc, address, size, unused):
        nonlocal tick
        original = address - delta
        if original == 0x87b43c:
            uc.reg_write(UC_X86_REG_EAX, 0); ret(uc)
        elif original == 0x87b450:
            uc.reg_write(UC_X86_REG_EAX, row + (0x100 if tick == 2 else 0)); ret(uc)
        elif original == 0x87b4c0:
            uc.reg_write(UC_X86_REG_EAX, int(tick < (2 if followup_ordinary else 1)))
            tick += 1; ret(uc)

    u.hook_add(UC_HOOK_CODE, hook); run(u, 0x872bf4, base)
    actual_eligible = u.mem_read(row + 0x28, 1)[0] == 0
    colour = get(u, row + 0x24); visible = bool(u.mem_read(row + 0x21, 1)[0])
    assert actual_eligible == expected_eligible, (record, roster, actual_eligible)
    assert visible == (record.status != 1), (record.status, visible)
    if record.status == 1:
        assert colour == 0xffa7a7a7
    elif not expected_eligible:
        assert colour == 0xff6060ff, hex(colour)
    else:
        assert colour != 0xff6060ff, hex(colour)
        if record.mode in (1, 4) and record.stake == 0:
            assert colour == 0xffb1efdb, hex(colour)
    for actor, value in before:
        assert bytes(u.mem_read(actor, 0x6100)) == value, 'List rendering changed owned fighters'
    if followup_ordinary:
        assert u.mem_read(row + 0x128, 1)[0] == 1
        assert get(u, row + 0x124) == 0xff6060ff, 'Following ordinary row inherited Team/Wall qualifying level'
    return dict(base=hex(base), roster=roster, eligible=actual_eligible, visible=visible,
                colour_hex=f'{colour:08x}', followup_ordinary=followup_ordinary, **proof)


def join_case(raw, base, identity):
    """Actual main-list click873794 and join builderA089F0; UI mutex/TX isolated."""
    u = emulator(raw, base); delta = base - patcher.IMAGE_BASE
    listing, row = DATA + 0x100, DATA + 0x400
    put(u, 0xacf394 + delta, listing); put(u, listing + 8, 1)
    put(u, 0xac48a8 + delta, row); put(u, row, identity)
    obj, handle, vtable, flush = DATA + 0x1000, DATA + 0x3000, DATA + 0x3100, DATA + 0x3200
    put(u, handle, obj); put(u, obj, vtable); put(u, vtable, flush)
    put(u, 0xac600c + delta, handle); put(u, 0xac5fa0 + delta, DATA + 0x3300)

    def hook(uc, address, size, unused):
        original = address - delta
        if original == 0x6748b0:
            uc.reg_write(UC_X86_REG_EAX, handle); ret(uc)
        elif original in (0x87251c, 0x8725d8) or address == flush:
            ret(uc)

    u.hook_add(UC_HOOK_CODE, hook); run(u, 0x873794, base)
    packet = bytes(u.mem_read(obj + 4, get(u, obj + 0x1004)))
    assert packet == b'\x29' + struct.pack('<I', identity), packet.hex()
    return dict(base=hex(base), identity=identity, packet_hex=packet.hex())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'reports/gameplay-completion/legacy-lobbies-20261011/native-proof.json')
    args = parser.parse_args()
    source = args.source.read_bytes()
    raw = args.candidate.read_bytes() if args.candidate else patcher.patch(source)
    cases, joins = [], []
    rosters = [([], False), ([(4, 1, True)], False), ([(1, 1, True)], True),
               ([(1, 1, True), (4, 2, True)], True),
               ([(4, 1, True), (1, 0, True)], True),
               ([(3, 0, True)], True), ([(0, 1, True)], False),
               ([(21, 1, True)], False), ([(1, 1, False)], False),
               ([None] * 30 + [(2, 0, True)], True)]
    for base in (0x400000, 0x10400000):
        for mode, capacity in ((1, 2), (4, 4)):
            for status, members in ((0, 1), (2, capacity)):
                for roster, eligible in rosters:
                    record = WagerRoomRecord(100 + mode, 'Капитан · свободно'.encode('cp1251'),
                                             2, mode, capacity, members, status, 1, 2, 1, 0, 0)
                    cases.append(colour_case(raw, base, record, roster, expected_eligible=eligible))
            record = WagerRoomRecord(100 + mode, b'Running', 2, mode, capacity, 1, 1, 1, 2, 1, 0, 0)
            cases.append(colour_case(raw, base, record, [(1, 0, True)], expected_eligible=True))
            record = WagerRoomRecord(100 + mode, b'Team before ordinary', 2, mode, capacity, 1, 0, 1, 2, 1, 0, 0)
            cases.append(colour_case(raw, base, record, [(1, 1, True), (4, 2, True)],
                                     expected_eligible=True, followup_ordinary=True))
        # The original survival predicate continues to use selected maximum.
        for roster, eligible in (([(1, 1, True), (4, 2, True)], False),
                                  ([(1, 1, True)], True), ([], True)):
            record = WagerRoomRecord(900, b'Survival', 2, 0, 2, 1, 0, 1, 2, 1, 0, 0)
            cases.append(colour_case(raw, base, record, roster, expected_eligible=eligible))
        for identity in (101, 104, 0xfedcba98):
            joins.append(join_case(raw, base, identity))
        for mode in (1, 4):
            record = WagerRoomRecord(100+mode, b'Level7-10', 8, mode, 2, 1, 0, 1, 2, 2, 0, 0)
            for level in (6, 7, 10, 11):
                cases.append(colour_case(raw, base, record, [(level, 0, True)],
                                         expected_eligible=level in (7, 10)))
            record = WagerRoomRecord(200+mode, b'Existing wager', 8, mode, 2, 1, 0, 1, 2, 2, 0, 100)
            cases.append(colour_case(raw, base, record, [(6, 1, True), (11, 0, True)],
                                     expected_eligible=True))
            cases.append(colour_case(raw, base, record, [(11, 1, True), (7, 0, True)],
                                     expected_eligible=False))
    report = dict(status='PASS', scope=__doc__, source_sha256=hashlib.sha256(source).hexdigest(),
                  candidate_sha256=hashlib.sha256(raw).hexdigest(), cases=len(cases), details=cases,
                  join_cases=joins, metadata=patcher.metadata(),
                  stubs=['managed string storage/cleanup', 'typed collection accessor',
                         'GUI row insertion/list iterators', 'GUI mutex and transport flush'],
                  real_graphical_clients=False)
    if not args.candidate:
        report['native_review'] = patcher.review(source, raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {len(cases)} native decode/projection/availability cases, {len(joins)} native join-click cases')


if __name__ == '__main__':
    main()
