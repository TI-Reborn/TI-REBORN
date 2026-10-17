"""Original B9 dispatcher and manifest readers; strings/list/loading explicitly stubbed."""
from verify_auth_native import *
from tio.protocol.shared_config import SharedConfigEntry, encode_shared_config_set


def run(entries):
    packet = encode_shared_config_set(entries)
    u = emulator(); u.mem_write(DATA, packet)
    names = []; values = []; load_calls = []; consumed = []
    def hook(uc, addr, size, user):
        a = uc.reg_read(UC_X86_REG_EAX); d = uc.reg_read(UC_X86_REG_EDX)
        if addr == 0x605f1c:
            pos = get32(uc, a); raw = bytearray()
            while bytes(uc.mem_read(pos, 1)) != b'\0':
                raw.extend(uc.mem_read(pos, 1)); pos += 1
            names.append(bytes(raw)); put32(uc, a, pos+1); put32(uc, d, 0)
        elif addr == 0x9d2a78: values.append(d)
        elif addr == 0x9d2ba8:
            load_calls.append(addr)
            consumed.append(get32(uc, uc.reg_read(UC_X86_REG_EBP)-8)-DATA)
        elif addr not in (0x9cfa38, 0x40b09c): return
        return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, 0xb9); u.reg_write(UC_X86_REG_EDX, DATA+1)
    u.emu_start(0x9d070c, STOP, count=10000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    assert names == [e.name_bytes for e in entries]
    assert values == [e.comparison_value for e in entries]
    assert consumed == [len(packet)] and len(load_calls) == 1
    return {'packet_hex': packet.hex(), 'names_hex': [n.hex() for n in names], 'values': values, 'consumed': consumed[0]}


if __name__ == '__main__':
    cases = [run(()), run((SharedConfigEntry(b'items', 0x12345678), SharedConfigEntry(b'mobs', 0xffffffff)))]
    (ROOT/'evidence/native_shared_config_probe.json').write_text(json.dumps({'sha256': EXPECTED_SHA, 'method': __doc__, 'cases': cases}, indent=2)+'\n', encoding='utf-8')
    print('2 original-x86 shared config manifest cases passed.')
