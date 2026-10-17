"""Execute original AssetCount reader and wallet consumer with explicit UI stubs."""
from verify_auth_native import *
from tio.protocol.asset_count import AssetCount, encode_asset_count


def main():
    cases = []
    for value in (AssetCount(10000, 10000), AssetCount(9876, 4321, optional_raw=(123456789, 17)),
                  AssetCount(7777,1234,spectra_crystals=2500)):
        packet = encode_asset_count(value)
        u = emulator()
        obj, character = DATA + 0x2000, DATA + 0x4000
        u.mem_write(DATA, packet[2:])
        put32(u, 0xacd0e8, DATA)
        u.reg_write(UC_X86_REG_EAX, obj)
        u.emu_start(0x65802c, STOP, count=5000)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        assert get32(u, 0xacd0e8) - DATA == len(packet) - 2
        assert get32(u, obj) == value.credits
        assert get32(u, obj + 8) == value.gold
        if value.optional_raw:
            assert bytes(u.mem_read(obj + 0x50, 8)) == struct.pack('<Q', value.optional_raw[0])
            assert get32(u, obj + 0x5c) == value.optional_raw[1]
        # Run the real wallet assignments; roster is empty and UI updates are stubs.
        put32(u, 0xac5b7c, character)
        put32(u, 0xac55cc, DATA + 0x6000)
        put32(u, 0xac618c, DATA + 0x7000)
        u.mem_write(0xac4754, b'\0')
        stubs = {0x91453c, 0x914540, 0x974730, 0x917684, 0x70a78c}
        def hook(uc, address, size, unused):
            if address == 0x7d8acc:
                uc.reg_write(UC_X86_REG_EAX, 0xffffffff)
                return_from_stub(uc)
            elif address in stubs:
                return_from_stub(uc)
        u.hook_add(UC_HOOK_CODE, hook)
        u.reg_write(UC_X86_REG_ESP, STACK + 0x8000)
        u.reg_write(UC_X86_REG_EAX, obj)
        u.emu_start(0x7d4c28, STOP, count=5000)
        assert u.reg_read(UC_X86_REG_EIP) == STOP
        assert get32(u, character + 0x230) == value.credits
        assert get32(u, character + 0x234) == value.gold
        assert get32(u, character + 0x240) == value.spectra_crystals
        cases.append({'packet_hex': packet.hex(), 'body_consumed': len(packet)-2,
                      'credits_saved': value.credits, 'gold_saved': value.gold,
                      'crystals_saved':value.spectra_crystals})
    (ROOT / 'evidence/asset_count_native.json').write_text(json.dumps({
        'sha256': EXPECTED_SHA, 'reader': '65802c', 'consumer': '7d4c28',
        'ui_stubs': [hex(x) for x in sorted(stubs)], 'mode_stub': '7d8acc returns -1',
        'cases': cases}, indent=2) + '\n')
    print('Original AssetCount reader and wallet consumer: 3 cases PASS')


if __name__ == '__main__':
    main()
