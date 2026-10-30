"""Original C1 quotation readers and request builders; UI/list/transport stubs only.

Readers run through the original dispatcher 0x6fff04 and are checked against
the globals and list records they fill. Builders run unchanged and their bytes
must decode with tio.protocol.securities.
"""
from verify_auth_native import *
from tio.protocol import securities as wire

DISPATCH = 0x6fff04
BOND = 0xacdc08
PYRAMID = 0xacdc38
# Window lookup, admin window, log and history-list helpers return without UI.
UI_STUBS = {0x9cfa38, 0xa69d68, 0xa69cd0, 0x6fa354, 0x6fa4c8, 0x6f95b0, 0x6ef194,
            0x6fb644, 0x6fb7b0, 0x6fa878, 0x6ef144}
BOND_APPEND, PYRAMID_APPEND = 0x6f9a90, 0x6fad64


def read(packet):
    u = emulator(); u.mem_write(DATA, packet[1:])
    put32(u, 0xacd930, DATA+0x5000); put32(u, 0xacd934, DATA+0x6000)
    records = []

    def hook(uc, address, size, unused):
        if address in (BOND_APPEND, PYRAMID_APPEND):
            length = 16 if address == BOND_APPEND else 40
            records.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX), length)))
            return_from_stub(uc)
        elif address in UI_STUBS:
            uc.reg_write(UC_X86_REG_EAX, 0); return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, packet[0]); u.reg_write(UC_X86_REG_EDX, DATA)
    u.emu_start(DISPATCH, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP and u.reg_read(UC_X86_REG_EAX) & 0xff == 1
    return u, records


def bond_config():
    config = wire.BondConfig(1759276800, 1761004799, 1761350400, 1761436799, 155, 150)
    u, _ = read(wire.encode_bond_config(config))
    fields = struct.unpack('<B7xqqqqII', u.mem_read(BOND, 0x30))
    assert fields == (1, config.sale_from, config.sale_until, config.redemption_from, config.redemption_until,
                      config.redemption_credits, config.price_credits)
    return dict(packet=wire.encode_bond_config(config).hex(), fields=list(fields))


def pyramid_config():
    config = wire.PyramidConfig(pyramid_id=104, selling_price=104, buying_price=104)
    u, _ = read(wire.encode_pyramid_config(config))
    fields = struct.unpack('<B3x6I', u.mem_read(PYRAMID, 0x1c))
    assert fields == (1, 0, 104, 104, 0, 104, 0)
    return dict(packet=wire.encode_pyramid_config(config).hex(), fields=list(fields))


def histories():
    bonds = ((1759276800, 150), (1761955200, 155))
    _, records = read(wire.encode_bond_history(bonds))
    assert [struct.unpack('<qI4x', r) for r in records] == list(bonds)
    pyramid = (wire.PyramidPoint(1759276800, (100, 101, -1, 2**31-1)),)
    _, records = read(wire.encode_pyramid_history(pyramid))
    assert [struct.unpack('<q4q', r) for r in records] == [(1759276800, 100, 101, -1, 2**31-1)]
    return dict(bonds=len(bonds), pyramid=len(pyramid))


def build(function, *, eax=0, edx=0, quote=0):
    # Same transport isolation as verify_ability_requests_native: the original
    # writers fill obj+4 and the length at obj+0x1004; only the flush returns.
    u = emulator(); obj = DATA+0x1000; handle = DATA+0x3000; vt = DATA+0x3100; flush = DATA+0x3200
    put32(u, handle, obj); put32(u, obj, vt); put32(u, vt, flush); put32(u, 0xac600c, handle)
    put32(u, 0xacdc40, quote)

    def hook(uc, address, size, unused):
        if address == 0x6748b0:
            uc.reg_write(UC_X86_REG_EAX, handle); return_from_stub(uc)
        elif address == flush:
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, eax); u.reg_write(UC_X86_REG_EDX, edx)
    u.emu_start(function, STOP, count=5000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    return bytes(u.mem_read(obj+4, get32(u, obj+0x1004)))


def builders():
    cases = ((0x6ff728, {}, wire.Request(wire.Action.BOND_CONFIG)),
             (0x6ff75c, {}, wire.Request(wire.Action.PYRAMID_CONFIG)),
             (0x6ff8d4, {}, wire.Request(wire.Action.BOND_HISTORY)),
             (0x6ff900, {}, wire.Request(wire.Action.PYRAMID_HISTORY)),
             (0x6ff92c, dict(eax=4), wire.Request(wire.Action.BOND_PURCHASE, count=4)),
             (0x6ff7cc, dict(eax=0, edx=2), wire.Request(wire.Action.BOND_REDEMPTION, count=2)),
             (0x6ff964, dict(eax=3, quote=104), wire.Request(wire.Action.STOCK_PURCHASE, count=3, reference=104)),
             (0x6ff9a8, dict(eax=1, quote=104), wire.Request(wire.Action.STOCK_SALE, count=1, reference=104)))
    result = []
    for function, registers, expected in cases:
        packet = build(function, **registers)
        assert wire.decode_request(packet) == expected, (hex(function), packet.hex())
        result.append(dict(builder=hex(function), packet=packet.hex()))
    return result


if __name__ == '__main__':
    result = dict(sha256=EXPECTED_SHA, bond_config=bond_config(), pyramid_config=pyramid_config(),
                  histories=histories(), builders=builders())
    (ROOT/'evidence/securities_native.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Original C1 readers: 4 packet types PASS; original C1 builders: 8 requests PASS')
