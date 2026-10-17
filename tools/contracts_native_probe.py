"""Bounded, offline x86 proofs for Contracts client research.

Executes the original archive Silver code. Transport and GUI calls are explicitly
stubbed; this is not a graphical client or end-to-end gameplay acceptance.
"""
from __future__ import annotations

import json
import struct
from functools import lru_cache

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP,
    UC_X86_REG_EIP, UC_X86_REG_EBX, UC_X86_REG_EDI,
)

from contracts_native_research import NativeImage, EXPECTED_SHA, REPORT_DIR

DATA = 0x02000000
STACK = 0x03000000
STOP = STACK + 0x100


def put32(u, address, value):
    u.mem_write(address, struct.pack("<I", value))


def get32(u, address):
    return struct.unpack("<I", u.mem_read(address, 4))[0]


def return_from_stub(u):
    sp = u.reg_read(UC_X86_REG_ESP)
    u.reg_write(UC_X86_REG_EIP, get32(u, sp))
    u.reg_write(UC_X86_REG_ESP, sp + 4)


@lru_cache(maxsize=1)
def native_image():
    return NativeImage()


def emulator():
    image = native_image()
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(0, 0x1000)
    u.mem_map(image.base, (len(image.data) + 0xfff) & ~0xfff)
    u.mem_write(image.base, image.data)
    u.mem_map(DATA, 0x20000)
    u.mem_map(STACK, 0x10000)
    put32(u, STACK + 0x8000, STOP)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
    return u


def run(u, start, end=STOP, *, budget=20000):
    u.emu_start(start, end, count=budget)
    if u.reg_read(UC_X86_REG_EIP) != end:
        raise AssertionError("Native fragment did not finish within instruction budget")


def party_writer(entry: int, *, owner=0, slots=0, nonce=0, accepted=0) -> bytes:
    """Numeric native builders: leave, member slots, cancel and invite answer."""
    if entry not in (0x7f6f40, 0x7f6efc, 0x7f6f6c, 0x7f71cc):
        raise ValueError("Unsupported bounded native writer")
    u = emulator()
    obj, handle, vt, flush = (DATA + n for n in (0x1000, 0x3000, 0x3100, 0x3200))
    put32(u, obj, vt)
    put32(u, vt, flush)
    put32(u, handle, obj)
    put32(u, 0xac600c, handle)
    # A mismatch avoids the original pending-invitation clear side effect.
    put32(u, 0xac47c0, 0xdeadbeef)
    put32(u, 0xac47c4, 0xdeadbeef)
    stack = STACK + 0x8000
    put32(u, stack + 4, nonce & 0xffffffff)
    put32(u, stack + 8, nonce >> 32)

    def hook(uc, address, size, unused):
        if address == 0x6748b0:
            uc.reg_write(UC_X86_REG_EAX, handle)
            return_from_stub(uc)
        elif address == flush or address in (0x40b09c, 0xa69d68):
            if address == 0xa69d68:
                uc.reg_write(UC_X86_REG_EAX, 0)
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, accepted if entry == 0x7f71cc else owner)
    u.reg_write(UC_X86_REG_EDX, slots)
    run(u, entry)
    return bytes(u.mem_read(obj + 4, get32(u, obj + 0x1004)))


def party_states(own_id: int, members: tuple[tuple[int, int, int, tuple[int, ...]], ...]) -> dict:
    """Original TPartyList.UpdatePartyStates over owner IDs and nested mercenaries.

    Each member is (character_id, status, reserved_slots, mercenary_npc_ids).
    Numeric 2 is the original ready status; its UI caption is recorded separately.
    """
    if len(members) > 4 or any(len(m[3]) > 4 for m in members):
        raise ValueError("Original party layout supports four players/four nested chars")
    u = emulator()
    obj, own = DATA + 0x1000, DATA + 0x3000
    put32(u, 0xac5a98, own)
    put32(u, own, own_id)
    for index, (character_id, status, slots, mercenaries) in enumerate(members):
        record = obj + 0x290 + index * 100
        u.mem_write(record, b"\x01")
        put32(u, record + 4, character_id)
        u.mem_write(record + 12, bytes((slots, len(mercenaries))))
        u.mem_write(record + 96, bytes((status,)))
        for mercenary, npc in enumerate(mercenaries):
            put32(u, record + 16 + mercenary * 20, npc)
    u.reg_write(UC_X86_REG_EAX, obj)
    run(u, 0x7f6e04)
    values = bytes(u.mem_read(obj + 0x28c, 4))
    return dict(i_am_ready=bool(values[0]), we_all_ready=bool(values[1]),
                my_slots=values[2], have_freak=bool(values[3]))


def quest_state(fields: tuple[int, int, int, int, int, int, int, int],
                first=(), second=(), *, now_ms=42000) -> dict:
    """Execute original C0/03 body consumer, with numeric fields kept opaque."""
    quest_id, unused_u64, state, timer1, flag, timer2, unused_u8, unused_u32 = fields
    body = struct.pack("<IQBIBIBI", *fields)
    for collection in (first, second):
        body += struct.pack("<H", len(collection))
        for row in collection:
            body += struct.pack("<IIB", *row)
    u = emulator()
    obj, clock, control, vt, method = (DATA + n for n in (0x1000, 0x3000, 0x3100, 0x3200, 0x3300))
    u.mem_write(DATA, body)
    put32(u, 0xad14dc, obj)
    put32(u, 0xac5fe4, clock)
    put32(u, clock, now_ms)
    put32(u, obj + 0x358, control)
    put32(u, control, vt)
    put32(u, vt, method)
    consumed = []

    def hook(uc, address, size, unused):
        if address == 0x4244b4:
            put32(uc, uc.reg_read(UC_X86_REG_EDX), 0)
            return_from_stub(uc)
        elif address in (0x9cd0c0, 0x9cc698, 0x40b09c, method):
            return_from_stub(uc)
        elif address == 0x9cc4d5:
            # Original ESI contains the packet cursor pointer.
            from unicorn.x86_const import UC_X86_REG_ESI
            consumed.append(get32(uc, uc.reg_read(UC_X86_REG_ESI)) - DATA)

    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA)
    run(u, 0x9cc3b0)
    return dict(consumed=consumed[-1], expected_bytes=len(body),
                state=u.mem_read(obj + 0x348, 1)[0],
                deadline1=get32(u, obj + 0x34c), deadline2=get32(u, obj + 0x350))


def zone_visibility(zone_id: int, enabled: int) -> dict:
    """Native C8/2D assignment, map gate and F0/98 lookup for added slots."""
    from tio.protocol.town_info import TownInfoBase, encode_town_info
    if not 1 <= zone_id <= 20 or enabled not in (0, 1):
        raise ValueError("Bounded synthetic zone table")
    u = emulator()
    obj, table, indirect = DATA + 0x1000, DATA + 0x3000, DATA + 0x2000
    put32(u, 0xac63bc, indirect)
    put32(u, indirect, table)
    put32(u, table - 4, 20)
    for index in range(20):
        record = DATA + 0x4000 + index * 0x400
        put32(u, table + index * 4, record)
        put32(u, record + 8, index + 1)
    put32(u, 0xac5d58, DATA + 0x2100)
    put32(u, DATA + 0x2100, zone_id)
    run(u, 0x7d2ea4, 0x7d2eb7)
    lookup = get32(u, u.reg_read(UC_X86_REG_EAX) + 8)
    info = TownInfoBase(zone_id, 0, (1, 3, 0, 0), (0, 0, 0), (0, 0x3f800000, 0), (0, 0, 0), enabled)
    body = encode_town_info(info)[2:]
    u.mem_write(DATA, body)
    put32(u, 0xacd0e8, DATA)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)

    def hook(uc, address, size, unused):
        if address == 0x40b0fc:
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    run(u, 0x64a3fc)
    u.reg_write(UC_X86_REG_EDI, obj)
    u.reg_write(UC_X86_REG_EBX, zone_id - 1)
    run(u, 0x7cfb41, 0x7cfb59)
    record = get32(u, table + (zone_id - 1) * 4)
    saved = u.mem_read(record + 4, 1)[0]
    u.reg_write(UC_X86_REG_EDI, zone_id - 1)
    run(u, 0x9e8ed6, 0x9e8eef if enabled else 0x9e969b)
    return dict(zone_id=zone_id, lookup=lookup, enabled=saved,
                consumed=get32(u, 0xacd0e8) - DATA, expected_bytes=len(body))


def main():
    writers = [dict(entry=hex(entry), packet_hex=party_writer(entry, owner=17, slots=2,
                   nonce=0x123456789abcdef0, accepted=1).hex())
               for entry in (0x7f6f40, 0x7f6efc, 0x7f6f6c, 0x7f71cc)]
    states = [party_states(17, members) for members in (
        (), ((17, 2, 1, (1,)),), ((17, 2, 2, (1,)), (18, 2, 1, (6,))),
        ((17, 2, 2, (1,)), (18, 1, 1, (6,))))]
    quests = [quest_state((991, 0, state, 60, 1, 90, 0, 0),
                         ((10, 2, 1), (11, 3, 0)), ((12, 4, 1),)) for state in (0, 1, 2, 3)]
    zones = [zone_visibility(zone, enabled) for zone in (18, 19, 20) for enabled in (0, 1)]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = dict(sha256=EXPECTED_SHA, method=__doc__, graphical_clients=0,
                  network_connections=0, writers=writers, party_states=states,
                  quest_states=quests, zones=zones)
    (REPORT_DIR / "probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Original numeric writers, party states, QuestState and added zone gates: PASS")


if __name__ == "__main__":
    main()
