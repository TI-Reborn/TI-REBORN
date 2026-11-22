"""Run published x86 service readers and level lookup with isolated UI stubs.

XML/file loading and rendering are not exercised. The lookup table is a fixture
in the original 24-byte record layout, not a claim of a graphical purchase.
"""
import hashlib
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
import verify_auth_native as native
from verify_city_catalogs_native import run_case
from verify_services_native import paid
from tio import services
from tio.protocol.city_catalogs import decode_service_shop
from tio.wallets import WalletStore

PUBLISHED = ROOT / 'reports/warehouse-expansion-20261101/client/silver-before.dll'
if not PUBLISHED.is_file():
    PUBLISHED = Path('C:/Users/jundu/AppData/Local/TIO-Online/silver.dll')
PUBLISHED_SHA = '87d54db3ae2d20d2065b0ecee9fe728c294f170b2cd6f11ba818c01d655bc5ed'


def lookup(rows: tuple[tuple[int, int, int], ...], level: int) -> int:
    machine = native.emulator()
    table = native.DATA + 0x5004
    native.put32(machine, table - 4, len(rows))
    for index, (service, tier, power) in enumerate(rows):
        machine.mem_write(table + index * 24,
                          struct.pack('<6I', service, tier, power, 0, 0, 0))
    native.put32(machine, 0xacefb0, table)
    machine.reg_write(native.UC_X86_REG_EAX, 1)
    machine.reg_write(native.UC_X86_REG_EDX, level)
    machine.emu_start(0x842808, native.STOP, count=10000)
    assert machine.reg_read(native.UC_X86_REG_EIP) == native.STOP
    return machine.reg_read(native.UC_X86_REG_EAX)


def main() -> None:
    original = native.BINARY.read_bytes()
    published = PUBLISHED.read_bytes()
    assert hashlib.sha256(original).hexdigest() == native.EXPECTED_SHA
    assert hashlib.sha256(published).hexdigest() == PUBLISHED_SHA
    spans = ((0x842808, 96), (0x842ac8, 742), (0x84e280, 688))
    with pefile.PE(data=original) as before, pefile.PE(data=published) as after:
        for address, size in spans:
            assert before.get_data(address - 0x400000, size) == after.get_data(
                address - 0x400000, size), hex(address)
    native.BINARY, native.EXPECTED_SHA = PUBLISHED, PUBLISHED_SHA
    rows = tuple((1, tier, power) for tier, (power, _) in
                 enumerate(services.OFFERS[1], 1))
    cases = []
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'state.sqlite3'
        WalletStore(path).ensure('alice')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('UPDATE wallets SET credits=1000000 WHERE account=?', ('alice',))
        for tier, (power, price) in enumerate(services.OFFERS[1], 1):
            packet = services.catalog(path, 'alice')
            offer = next(o for o in decode_service_shop(packet) if o.unknown_u32 == 1)
            assert offer.options[0].unknown_u8 == tier
            assert lookup(rows, tier) == power
            parsed = run_case('services', packet)
            option = bytes.fromhex(parsed['records'][1])
            assert option[0] == tier and struct.unpack_from('<I', option, 16)[0] == price
            request = bytes.fromhex('b10400') + struct.pack('<IBI', 1, tier, 1)
            services.purchase(path, 'alice', request)
            cases.append(dict(**paid(1, tier), power=power, price=price,
                              catalog_consumed=parsed['consumed']))
        assert lookup(rows, len(rows) + 1) == 0
        assert all(o.unknown_u32 != 1 for o in decode_service_shop(services.catalog(path, 'alice')))
    output = dict(passed=True, dll_sha256=PUBLISHED_SHA, unchanged_original_spans=spans,
                  cases=cases, scope=__doc__)
    target = ROOT / 'reports/warehouse-expansion-20261101/native.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps(output))


if __name__ == '__main__':
    main()
