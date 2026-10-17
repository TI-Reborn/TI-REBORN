"""Original SC numeric readers/writers and catalog consumer; allocator/UI isolated."""
from verify_auth_native import *
from tio.protocol.sc_shop import SCOffer, encode_sc_catalog, encode_sc_basket


def catalog_case(offers):
    packet = encode_sc_catalog(offers)
    u = emulator()
    u.mem_write(DATA, packet)
    obj, rows, flags = DATA+0x1000, DATA+0x1100, DATA+0x4000
    put32(u, 0xacd0e8, DATA+2)
    def read_hook(uc, addr, size, user):
        if addr == 0x655e04:
            count = uc.reg_read(UC_X86_REG_EDX)
            assert count == len(offers)
            put32(uc, obj, rows); put32(uc, obj+4, count); put32(uc, obj+8, flags)
            return_from_stub(uc)
    handle = u.hook_add(UC_HOOK_CODE, read_hook)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x655bd0, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert get32(u, 0xacd0e8) == DATA+len(packet)
    u.hook_del(handle)
    # Feed decoded object through the actual SC consumer and getters.
    for global_addr, pointer, target in ((0xac5ca4, DATA+0x4100, DATA+0x4200),
                                          (0xac6078, DATA+0x4600, DATA+0x4700),
                                          (0xac637c, DATA+0x4b00, DATA+0x4c00)):
        put32(u, global_addr, pointer); put32(u, pointer, target)
    put32(u, DATA+0x4200+0x2ac, DATA+0x5800)
    put32(u, DATA+0x4700+0x2c4, DATA+0x5900)
    put32(u, DATA+0x4200+0x2b0, 1)
    captured = []
    def consume_hook(uc, addr, size, user):
        eax = uc.reg_read(UC_X86_REG_EAX)
        if addr == 0x40ce98:
            uc.reg_write(UC_X86_REG_EAX, DATA+0x6000); return_from_stub(uc)
        elif addr == 0xa7b030:
            uc.reg_write(UC_X86_REG_EAX, 0); return_from_stub(uc)
        elif addr == 0x8f3730:
            captured.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX), 0x2a0)))
            return_from_stub(uc)
        elif addr in (0x8f15fc, 0xa7a13c, 0x8ef4dc, 0x8ee720, 0x8f2c5c, 0x8eb6a4):
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, consume_hook)
    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    put32(u, STACK+0x8000, STOP)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x8eba9c, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert len(captured) == len(offers)
    assert bytes(u.mem_read(DATA+0x4200+0x2b0, 1)) == b'\0'
    for raw, o in zip(captured, offers):
        for offset, value in ((0x290, o.lot_id), (8, o.item_id), (0x298, o.available),
                              (0x38, o.credits), (0x3c, o.gold)):
            assert struct.unpack_from('<I', raw, offset)[0] == value
        assert raw[0x4e] == o.enhancement
        assert raw[0x294] == (o.discount if o.available else 0)
        assert struct.unpack_from('<H', raw, 0x48)[0] == o.durability
    return {'offers': len(offers), 'bytes_consumed': len(packet), 'loading_cleared': True}


def basket_case(rows):
    packet = encode_sc_basket(rows)
    u = emulator(); u.mem_write(DATA, packet)
    pointer, obj, listing = DATA+0x1000, DATA+0x1100, DATA+0x1500
    put32(u, 0xac6078, pointer); put32(u, pointer, obj); put32(u, obj+0x2c4, listing)
    put32(u, obj+0x280, 0xffffffff)  # No selected UI row.
    captured=[]
    def hook(uc, addr, size, user):
        if addr == 0x40ce98:
            uc.reg_write(UC_X86_REG_EAX, DATA+0x2000); return_from_stub(uc)
        elif addr == 0x8dd20c:
            captured.append(bytes(uc.mem_read(uc.reg_read(UC_X86_REG_EDX), 0x2a0)))
            return_from_stub(uc)
        elif addr == 0x8eba94:
            assert get32(uc, uc.reg_read(UC_X86_REG_EBP)-4) == DATA+len(packet)
        elif addr in (0x8ee0ec, 0x8dbec0, 0x8ee164, 0x8dad94, 0x8ee41c, 0x8eb548, 0x9797e0):
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, DATA+2)
    u.emu_start(0x8eb8d0, STOP, count=20000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP and len(captured) == len(rows)
    for raw, (offer, n) in zip(captured, rows):
        assert get32(u, obj+0x2d8) == sum(o.gold*q for o,q in rows)
        assert struct.unpack_from('<H', raw, 0x29a)[0] == n
        assert struct.unpack_from('<I', raw, 0x290)[0] == offer.lot_id
    return {'rows': len(rows), 'bytes_consumed': len(packet)}


def request_case(entry, action, fields):
    u = emulator(); obj = DATA+0x1000
    put32(u, 0xacd0e0, DATA); put32(u, 0xacd0f0, 0)
    for index, value in enumerate(fields):
        put32(u, obj+index*8, value); u.mem_write(obj+index*8+4, b'\1')
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(entry, STOP, count=1000)
    packet = bytes(u.mem_read(DATA, get32(u, 0xacd0f0)))
    expected = bytes((0xb4, action)) + b''.join(struct.pack('<I', x) for x in fields)
    assert packet == expected and u.reg_read(UC_X86_REG_EIP) == STOP
    return packet.hex()


def main():
    offers = (SCOffer(100314, 314, 0, 1000, 111, 222, 0, 100, 0, 300),
              SCOffer(100251, 251, 5, 17, 333, 444, 555, 666, 20, 250))
    from tio.sc_shop import ROOT
    rows = json.loads((ROOT/'config/sc_catalog.json').read_text())['offers']
    configured = tuple(SCOffer(o['lot_id'], o['item_id'], 0, o['stock_per_account'],
                              0, o['gold'], 0, o['gold'], 0, o['durability']) for o in rows)
    results = {'catalog': [catalog_case(()), catalog_case(offers), catalog_case(configured)],
               'basket': [basket_case(()), basket_case(((offers[0], 2), (offers[1], 3)))],
               'requests': [request_case(a, b, c) for a,b,c in (
                   (0x656204, 4, ()), (0x6560bc, 6, (100314, 7, 2)),
                   (0x655e68, 7, ()), (0x655e94, 9, (100314,)),
                   (0x65601c, 10, (100314,)), (0x655f2c, 11, (7, 2)))]}
    (ROOT/'evidence/sc_shop_native.json').write_text(json.dumps(
        dict(sha256=EXPECTED_SHA, method=__doc__, results=results), indent=2)+'\n')
    print('SC original x86: 3 catalog, 2 basket, 6 request cases PASS')


if __name__ == '__main__':
    main()
