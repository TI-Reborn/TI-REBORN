"""Execute real selector-close and C6/23 builder; stub transport and UI only."""
from pathlib import Path
import hashlib
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import verify_auth_native as n
from unicorn import UC_HOOK_CODE

OUT = ROOT / 'reports/ranked-cancel-20261018'
n.BINARY = OUT / 'silver.dll'
n.EXPECTED_SHA = hashlib.sha256(n.BINARY.read_bytes()).hexdigest()


def close(search_ui):
    u = n.emulator()
    obj, handle, vtable, flush = [n.DATA + x for x in (0x1000, 0x3000, 0x4000, 0x5000)]
    for ptr, value in ((handle, obj), (obj, vtable), (vtable, flush),
                       (0xac600c, handle), (0xac5b7c, n.DATA + 0x6000),
                       (0xac6370, n.DATA + 0x6100), (0xac62f8, n.DATA + 0x6200)):
        n.put32(u, ptr, value)
    u.mem_write(0xac4aa0, bytes([search_ui]))
    packets = []
    def hook(uc, va, size, _):
        if va == 0x6748b0:
            uc.reg_write(n.UC_X86_REG_EAX, handle)
            n.return_from_stub(uc)
        elif va == flush:
            packets.append(bytes(uc.mem_read(obj + 4, n.get32(uc, obj + 0x1004))).hex())
            n.return_from_stub(uc)
        elif va in (0x9560a0, 0x7f5d80, 0x9e58a8):
            n.return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(0x94e440, n.STOP, count=5000)
    assert u.reg_read(n.UC_X86_REG_EIP) == n.STOP
    assert u.reg_read(n.UC_X86_REG_ESP) == n.STACK + 0x8004
    assert packets == ['c623'], packets
    return dict(native_search_ui_flag=search_ui, packets=packets, returned=True)


def main():
    result = dict(passed=True, client_sha256=n.EXPECTED_SHA,
                  cases=[close(0), close(1)], ui_and_transport_stubbed=True)
    (OUT / 'native-execution.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
