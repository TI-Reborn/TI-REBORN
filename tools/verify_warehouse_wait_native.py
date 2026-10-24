"""Reproduce dropped warehouse requests in the original, unmodified client.

Runs the real 2F/6B builders, empty 30 decoder, 30 consumer and wait setter.
GUI rendering, managed strings and actor lookup use explicit synthetic stubs.
This is a native protocol probe, not a graphical or hosted gameplay test.
"""
import json
import struct

from verify_auth_native import (
    DATA, STACK, STOP, EXPECTED_SHA, emulator, get32, put32, return_from_stub,
    UC_HOOK_CODE, UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX,
    UC_X86_REG_ESP, UC_X86_REG_EIP,
)
from tio.city_inventory import city_inventory_replies
from tio.protocol.item_list import encode_item_list


def run() -> dict[str, object]:
    native = emulator()
    transport, handle = DATA + 0x1000, DATA + 0x3000
    vtable, flush = DATA + 0x3100, DATA + 0x3200
    actor, stock = DATA + 0xb000, DATA + 0xc000
    reply_object = DATA + 0x9000
    put32(native, handle, transport)
    put32(native, transport, vtable)
    put32(native, vtable, flush)
    put32(native, 0xac600c, handle)
    # Keep the original ac5940 -> ac4c58 alias; this is the global wait flag.
    assert get32(native, 0xac5940) == 0xac4c58
    put32(native, 0xac5dec, DATA + 0x3400)
    native.mem_write(DATA + 0x3400, b'\x01')
    put32(native, 0xac55cc, DATA + 0x3500)
    put32(native, DATA + 0x3500, stock)
    put32(native, 0xac618c, actor)
    put32(native, DATA + 0x4000 - 4, 1)
    put32(native, DATA + 0x4000 + 0x28, 1001)
    put32(native, DATA + 0x4000 + 0x1c, 1)
    packets = []

    def hook(cpu, address, size, user):
        if address == 0x6748b0:
            cpu.reg_write(UC_X86_REG_EAX, handle)
            return_from_stub(cpu)
        elif address == flush:
            packets.append(bytes(cpu.mem_read(
                transport + 4, get32(cpu, transport + 0x1004))))
            put32(cpu, transport + 0x1004, 0)
            return_from_stub(cpu)
        elif address == 0xa93f70:
            # The city knows primary actor1, not the stale actor22.
            owner = cpu.reg_read(UC_X86_REG_EAX)
            cpu.reg_write(UC_X86_REG_EAX, 0 if owner == 1 else 0xffffffff)
            return_from_stub(cpu)
        elif address == 0x40d5a4:
            put32(cpu, cpu.reg_read(UC_X86_REG_EAX), 0)
            return_from_stub(cpu)
            cpu.reg_write(UC_X86_REG_ESP, cpu.reg_read(UC_X86_REG_ESP) + 4)
        elif address in (0x424520, 0x40c1bc, 0x43b31c, 0x9cfca0,
                         0x40b0fc, 0x435664, 0x40d748, 0x40d6c8,
                         0x40c8cc, 0x40c9a4, 0x40c9f4, 0x98f720, 0x98fc48,
                         0x8bb1e8, 0x920054):
            return_from_stub(cpu)

    native.hook_add(UC_HOOK_CODE, hook)

    def call(entry: int, eax: int = 0, edx: int = 0, ecx: int = 0) -> None:
        put32(native, STACK + 0x8000, STOP)
        put32(native, STACK + 0x8004, 0)
        native.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        native.reg_write(UC_X86_REG_EAX, eax)
        native.reg_write(UC_X86_REG_EDX, edx)
        native.reg_write(UC_X86_REG_ECX, ecx)
        native.emu_start(entry, STOP, count=20000)
        assert native.reg_read(UC_X86_REG_EIP) == STOP

    call(0x98ffc4, 22)
    assert packets == [b'\x2f' + struct.pack('<HI', 1, 22)]
    assert bytes(native.mem_read(0xac4c58, 1)) == b'\x01'
    for _ in range(10):
        call(0x992294, 0, 1, DATA + 0x4000)
    assert len(packets) == 1, 'Waiting must suppress every 6B before transport'

    replies = city_inventory_replies((22,), {1: encode_item_list(1, ())}.get)
    assert len(replies) == 1, 'Stale request left native global waiting unresolved'
    native.mem_write(DATA + 0x8000, replies[0][1:])
    put32(native, 0xacd0e8, DATA + 0x8000)
    call(0x63ce00, reply_object)
    call(0x990638, reply_object)
    assert bytes(native.mem_read(0xac4c58, 1)) == b'\x00'
    call(0x992294, 0, 1, DATA + 0x4000)
    expected = b'\x6b\x00' + struct.pack('<I H I I H', 1, 1, 1001, 1, 0)
    assert packets[-1] == expected
    assert len(packets) == 2
    return dict(binary_sha256=EXPECTED_SHA, blocked_transfers=10,
                completion_owner=1, first_transfer_after_completion=True,
                graphical_client_verified=False, hosted_verified=False)


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
