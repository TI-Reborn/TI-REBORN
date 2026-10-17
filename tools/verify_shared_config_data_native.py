"""Original B9/03 dispatcher and reads/copy, stopped before filesystem operations."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_ESI, UC_X86_REG_EBX
from tio.protocol.shared_config import SharedConfigData, encode_shared_config_data


def run(size):
    blob = bytes(i % 251 for i in range(size))
    packet = encode_shared_config_data(SharedConfigData(b'items', 123456, blob))
    u = emulator()
    # Native handler reserves ~50 KB below ESP; put stack above that frame.
    u.reg_write(UC_X86_REG_ESP, STACK+0xf000); put32(u, STACK+0xf000, STOP)
    u.mem_write(DATA, packet)
    names = []; result = {}
    def hook(uc, addr, length, user):
        if addr == 0x9cfa38:
            return_from_stub(uc)
        elif addr == 0x605f1c:
            a = uc.reg_read(UC_X86_REG_EAX); d = uc.reg_read(UC_X86_REG_EDX)
            pos = get32(uc, a); raw = bytearray()
            while bytes(uc.mem_read(pos, 1)) != b'\0':
                raw.extend(uc.mem_read(pos, 1)); pos += 1
            names.append(bytes(raw)); put32(uc, a, pos+1); put32(uc, d, 0)
            return_from_stub(uc)
        elif addr == 0x9d04fb:
            bp = uc.reg_read(UC_X86_REG_EBP)
            result.update(consumed=get32(uc, bp-12)-DATA,
                          decompressed_size=uc.reg_read(UC_X86_REG_ESI),
                          compressed_size=uc.reg_read(UC_X86_REG_EBX))
            assert bytes(uc.mem_read(bp-0xc365, size)) == blob
            uc.emu_stop()
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, 0xb9); u.reg_write(UC_X86_REG_EDX, DATA+1)
    u.emu_start(0x9d070c, STOP, count=200000)
    assert names == [b'items']
    assert result == {'consumed': len(packet), 'decompressed_size': 123456, 'compressed_size': size}
    return result


if __name__ == '__main__':
    cases = [run(n) for n in (0, 31, 50000)]
    (ROOT/'evidence/native_shared_config_data_probe.json').write_text(json.dumps({'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases}, indent=2)+'\n', encoding='utf-8')
    print('3 original-x86 SharedConfig data reader/copy cases passed.')
