"""Check original inventory OK, generic OnHide and immediate action33 writes.

Runs the original x86 OK wrapper, window hide and event dispatcher. Only
unrelated GUI collections and managed cleanup are isolated. This establishes
that the built-in OK path emits no protocol confirmation with the constructor's
empty OnHide event. It does not model an external runtime event subscriber.
"""
from verify_auth_native import *
from capstone import Cs, CS_ARCH_X86, CS_MODE_32


def close_inventory(visible=True, listener=False):
    u = emulator()
    record, window, clock = DATA + 0x100, DATA + 0x1000, DATA + 0x2000
    callbacks, subscriber = DATA + 0x3000, DATA + 0x4000
    put32(u, record + 0xc, window)
    put32(u, window, 0xa31a40)  # Original generic window vtable.
    u.mem_write(window + 0x49, bytes((int(visible),)))
    put32(u, 0xac5fe4, clock)
    put32(u, clock, 12345)
    if listener:
        put32(u, callbacks - 4, 1)
        put32(u, callbacks, subscriber)
        put32(u, window + 0x2e8 + 0x10, callbacks)
    events, transport = [], []

    def hook(uc, address, size, user):
        if address in (0xa3ecfc, 0xa3fc0c, 0x40b09c):
            return_from_stub(uc)
        elif address == subscriber:
            events.append('OnHide')
            return_from_stub(uc)
        elif address == 0x6748b0:
            transport.append('get_transport')
            raise AssertionError('Inventory OK unexpectedly obtains a transport')

    u.hook_add(UC_HOOK_CODE, hook)
    # The registered interface+2c wrapper subtracts 2c before calling 9ba078.
    u.reg_write(UC_X86_REG_EAX, record + 0x2c)
    u.emu_start(0x9b90b7, STOP, count=8000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert bytes(u.mem_read(window + 0x49, 1)) == b'\0'
    assert events == (['OnHide'] if visible and listener else [])
    assert transport == []
    return {'visible_before': visible, 'external_listener': listener,
            'visible_after': False, 'event_calls': events, 'transport_calls': transport}


def immediate_writes(actions):
    u = emulator()
    obj, handle, vtable, flush = DATA + 0x1000, DATA + 0x3000, DATA + 0x3100, DATA + 0x3200
    item, metadata = DATA + 0x4000, DATA + 0x5000
    put32(u, handle, obj); put32(u, obj, vtable); put32(u, vtable, flush)
    put32(u, 0xac600c, handle)
    put32(u, 0xac637c, DATA + 0x3300); put32(u, DATA + 0x3300, metadata)
    u.mem_write(metadata + 0x68d, b'\x01')
    packets = []

    def hook(uc, address, size, user):
        values = {0x99f5d8: 0, 0xa7b030: 0, 0x66754c: 1, 0xa93eec: 1, 0x6748b0: handle}
        if address in values:
            uc.reg_write(UC_X86_REG_EAX, values[address]); return_from_stub(uc)
        elif address == flush:
            packets.append(bytes(uc.mem_read(obj + 4, get32(uc, obj + 0x1004))))
            put32(uc, obj + 0x1004, 0)
            return_from_stub(uc)
        elif address in (0x40cb10, 0x40b09c, 0x40c9a4):
            return_from_stub(uc)

    u.hook_add(UC_HOOK_CODE, hook)
    for actor_id, item_id, option in actions:
        sp = STACK + 0x8000
        put32(u, sp, STOP); put32(u, sp + 4, option)
        u.reg_write(UC_X86_REG_ESP, sp)
        u.reg_write(UC_X86_REG_EAX, actor_id)
        u.reg_write(UC_X86_REG_EDX, item_id)
        u.reg_write(UC_X86_REG_ECX, item)
        count_before = len(packets)
        u.emu_start(0x9903a4, STOP, count=4000)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        assert len(packets) == count_before + 1
        assert packets[-1] == b'\x33' + struct.pack('<IIB', actor_id, item_id, option)
    return {'actions': actions, 'flush_count': len(packets),
            'packets_hex': [packet.hex() for packet in packets]}


def static_contract():
    u = emulator()
    assert bytes(u.mem_read(0x9bbcd0, 12 * 2)).decode('utf-16le').startswith('btn_ok')
    assert get32(u, 0xa31a40) == 0xa43a54
    # Inventory constructor binds btn_ok to its interface+2c event.
    assert bytes(u.mem_read(0x9bb309, 3)) == b'\x83\xea\xd4'
    assert bytes(u.mem_read(0x9b90b7, 3)) == b'\x83\xc0\xd4'
    # The entire short OK body has only the standard window-close call.
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    body = tuple(md.disasm(bytes(u.mem_read(0x9ba078, 13)), 0x9ba078))
    assert [(i.mnemonic, i.op_str) for i in body if i.mnemonic == 'call'] == [('call', '0xa4370c')]
    # No OnHide subscriptions are established by the inventory constructor.
    # The seven subscriber arrays are initially empty; generic constructor
    # A43464 initializes OnHide through A54CC8->A54C5C only.
    return {'ok_control': 'window_inventory.btn_ok',
            'binding': '9bb309 interface+2c ->9b90b7 ->9ba078 ->a4370c ->a43a54',
            'on_hide': 'window+2e8 ->a54980; generic constructor a43464 ->a54cc8 ->a54c5c initializes empty arrays',
            'native_request': '33 u32 actor_id u32 instance_id u8 target_option, flushed by99052c immediately',
            'native_batch_confirmation': None,
            'limitation': 'No original inventory OK wire event found. External runtime subscribers and live game clients are outside this emulated proof.'}


if __name__ == '__main__':
    result = {'sha256': EXPECTED_SHA, 'method': __doc__, 'contract': static_contract(),
              'close_cases': [close_inventory(visible=v, listener=l) for v in (False, True) for l in (False, True)],
              'writer_cases': [immediate_writes(((17, 1001, 255), (17, 1002, 3))),
                               immediate_writes(((42, 0x12345678, 0), (42, 9, 255), (42, 9, 255)))]}
    (ROOT / 'evidence/equipment_confirmation_native.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    u = emulator()
    ranges = ((0x9bb2b4, 0x68), (0x9b90b7, 8), (0x9ba078, 13), (0xa4370c, 0x12),
              (0xa43a54, 0x153), (0xa43464, 0x12), (0xa54c5c, 0x6b), (0xa54980, 0x298),
              (0x9904f2, 0x3c))
    lines = ['; original silver.dll SHA256 ' + EXPECTED_SHA]
    for address, length in ranges:
        lines.append('; range ' + hex(address))
        lines.extend(f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in md.disasm(bytes(u.mem_read(address, length)), address))
    (ROOT / 'evidence/equipment_confirmation_native.asm').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('Original inventory OK: 4 native hide/event cases, 2 immediate-writer sequences PASS; no native confirmation wire event established')
