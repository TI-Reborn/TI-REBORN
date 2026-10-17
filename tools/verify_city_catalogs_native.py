"""Execute TI city dispatch/readers; stub allocation, string conversion and UI only."""
from verify_auth_native import *
from tio.protocol.city_catalogs import *


def run_case(kind, packet):
    u = emulator()
    u.mem_write(DATA, packet)
    captured = []
    heap = DATA + 0x3000
    cursor = None
    def alloc(size):
        nonlocal heap
        result = heap
        heap += (size + 31) & ~15
        return result
    def hook(uc, addr, size, user):
        nonlocal cursor
        eax = uc.reg_read(UC_X86_REG_EAX)
        edx = uc.reg_read(UC_X86_REG_EDX)
        ebp = uc.reg_read(UC_X86_REG_EBP)
        if addr == 0x40ce98:
            uc.reg_write(UC_X86_REG_EAX, alloc(eax)); return_from_stub(uc)
        elif addr == 0x605f1c:
            # Delphi managed-string conversion is isolated from numeric decoding.
            ptr = get32(uc, eax)
            raw = bytes(uc.mem_read(ptr, 256)).split(b'\0', 1)[0]
            put32(uc, eax, ptr + len(raw) + 1)
            text = alloc(260)
            uc.mem_write(text, bytes([len(raw)]) + raw)
            put32(uc, edx, text)
            return_from_stub(uc)
        elif addr == 0x40c06c:
            length = bytes(uc.mem_read(edx, 1))[0]
            uc.mem_write(eax, bytes(uc.mem_read(edx, length + 1)))
            return_from_stub(uc)
        elif addr == 0x40d5a4:
            sp = uc.reg_read(UC_X86_REG_ESP)
            count = get32(uc, sp + 4)
            buf = alloc(4 + count * 24) + 4
            put32(uc, buf - 4, count); put32(uc, eax, buf)
            return_from_stub(uc)
        elif addr == 0x8aab9c:
            captured.append(bytes(uc.mem_read(eax, 0x1a4)).hex()); return_from_stub(uc)
        elif addr == 0x9226cc:
            captured.append(bytes(uc.mem_read(edx, 0x58)).hex()); return_from_stub(uc)
        elif addr == 0x84accc:
            captured.append(bytes(uc.mem_read(edx, 12)).hex())
            ptr = get32(uc, edx + 8)
            captured.append(bytes(uc.mem_read(ptr, get32(uc, ptr - 4) * 24)).hex())
            return_from_stub(uc)
        elif addr == 0xa7a13c:
            put32(uc, eax + 4, 0xffffffff); return_from_stub(uc)
        elif addr == 0xa7b030:
            uc.reg_write(UC_X86_REG_EAX, 0); return_from_stub(uc)
        elif addr in (0x8c407e, 0x991d12, 0x84e413):
            cursor = get32(uc, ebp - 4) - DATA
        elif addr in (0x9cfa38, 0x8aa774, 0x40b09c, 0x84775c, 0x8477ec,
                      0x9799e0, 0x920040, 0x979f40, 0x97d340, 0x9767fc):
            return_from_stub(uc)
    if kind == 'items':
        for address in (0xac6004, 0xac5c30, 0xac5b98, 0xac637c, 0xac64b4, 0xac618c):
            ptr = alloc(0x10)
            put32(u, address, ptr)
            if address in (0xac5b98, 0xac637c):
                put32(u, ptr, alloc(0x800))
        entry = 0x9929f4
    elif kind == 'pets':
        entry = 0x8c7edc
    else:
        put32(u, 0xac655c, alloc(16))
        entry = 0x84e420
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, packet[0])
    u.reg_write(UC_X86_REG_EDX, DATA + 1)
    u.reg_write(UC_X86_REG_ECX, len(packet))
    u.emu_start(entry, STOP, count=30000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert cursor == len(packet), (kind, cursor, len(packet))
    assert u.reg_read(UC_X86_REG_EAX) & 255 == 1
    return {'kind': kind, 'packet_hex': packet.hex(), 'consumed': cursor, 'records': captured}


def main():
    pet = HireCandidate(11, 22, b'Recruit', 1, bytes(range(6)),
                        tuple(0x3f800000+i*0x10000 for i in range(16)), 31, 2, 3, 41, 51, 61)
    cases = [run_case('pets', encode_pet_shop((pet,))),
             run_case('pets', encode_pet_shop(())),
             run_case('items', encode_item_shop(0, (ShopItem(11, 22, 301, 33, 300, 1),))),
             run_case('services', encode_service_shop((ServiceOffer(12, 3, (ServiceOption(1, 0x123456789abcdef0, 500),)),)))]
    raw = bytes.fromhex(cases[0]['records'][0])
    assert raw[:8] == b'\7Recruit'
    assert struct.unpack_from('<II', raw, 0x100) == (11, 22)
    for i, bits in enumerate(pet.stat_float_bits):
        offset = 0x10c + (i//2)*4 + (0x48 if i%2 else 0)
        assert struct.unpack_from('<I', raw, offset)[0] == bits
    raw = bytes.fromhex(cases[2]['records'][0])
    for offset, value in [(0x30, 11), (0x24, 22), (0x10, 301), (0x40, 33)]:
        assert struct.unpack_from('<I', raw, offset)[0] == value
    assert struct.unpack_from('<H', raw, 0x50)[0] == 300
    raw = bytes.fromhex(cases[3]['records'][1])
    assert struct.unpack_from('<Q', raw, 8)[0] == 0x123456789abcdef0
    assert struct.unpack_from('<I', raw, 16)[0] == 500
    (ROOT/'evidence/native_city_catalogs.json').write_text(json.dumps({'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases}, indent=2)+'\n')
    print('Original city readers:4 cases PASS; records and full packet consumption verified')

if __name__ == '__main__':
    main()
