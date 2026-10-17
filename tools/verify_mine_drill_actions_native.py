"""Execute native drill click, quantity-dialog arguments and both wire writers.

The current battle mode, selected actor and deposit record are fixtures. Original
8143F4 and 8143C4 execute through original 33/B015 serializers; only collection
selection policy, metadata lookup, UI allocation/text and transport flushing are
stubbed. This proves command generation, not rendered native-client play.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX, UC_X86_REG_ESP, UC_X86_REG_EIP

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tio.protocol.item_action import decode_item_action, ItemAction
from tio.protocol.mining import decode_pickup

SOURCE = ROOT/'reports/client-ui-incident-20261010/client/silver.dll'
SOURCE_SHA = 'c8849a2997909c9ad6e09c674e67a641de7604aec2ddb829e4ee4187b87a972c'
BODIES = (
    (0x8143C4, 47, 'b990ab51283f03b269ed2e6ff45793b74df41dbc7d3c224674d58dc640bef61e'),
    (0x8143F4, 440, '919ed178963ebaefb26842a3958c99211f30431f1121302eb93be4a295da4c65'),
    (0x834764, 96, '526d4078d71a358b3944ded95543cc3f5753703390a4871c93e4b7168f494bca'),
    (0x9903A4, 492, '475cd7ce07e68ddecefaafde62d8b5a80916d2acb4e848e004161baced5a0e68'),
)
DATA, STACK = 0x2000000, 0x3000000
STOP = STACK+0x100


def put(u, address, value):
    u.mem_write(address, struct.pack('<I', value & 0xffffffff))


def get(u, address):
    return struct.unpack('<I', u.mem_read(address, 4))[0]


def ret(u, cleanup=0):
    sp = u.reg_read(UC_X86_REG_ESP)
    u.reg_write(UC_X86_REG_EIP, get(u, sp))
    u.reg_write(UC_X86_REG_ESP, sp+4+cleanup)


class Fixture:
    def __init__(self, raw, *, installed=False, selected=True, has_deposit=True,
                 has_drill=True, mode=7, extracted=300, carried=50, capacity=1000, weight=440):
        pe = pefile.PE(data=raw)
        assert pe.OPTIONAL_HEADER.ImageBase == 0x400000
        mapped = pe.get_memory_mapped_image()
        for va, count, digest in BODIES:
            assert hashlib.sha256(mapped[va-0x400000:va-0x400000+count]).hexdigest() == digest
        self.u = u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 0x1000)
        u.mem_map(0x400000, (len(mapped)+0xfff)&~0xfff)
        u.mem_write(0x400000, mapped)
        u.mem_map(DATA, 0x10000)
        u.mem_map(STACK, 0x10000)
        self.actor, self.items, self.deposit = DATA+0x4000, DATA+0xb000, DATA+0x3000
        self.transport, self.handle, self.flush = DATA+0x1000, DATA+0x2400, DATA+0x2500
        self.dialogs, self.callbacks, self.packets = [], [], []
        self.amount = extracted
        put(u, 0xac618c, DATA+0x100)
        put(u, DATA+0x100, self.actor)
        put(u, self.actor+0x28, 17)
        u.mem_write(self.actor+0x41, bytes((int(selected),)))
        put(u, self.actor+0x6c, self.items if has_drill else 0)
        put(u, self.items-4, 2)
        # The original loop must skip an unrelated item before finding the drill.
        put(u, self.items+8, 183)
        put(u, self.items+656+8, 52)
        put(u, self.items+656+0x28, 0xff001234)
        put(u, self.actor+0x6020, weight)
        put(u, self.actor+0x6024, capacity)
        put(u, 0xac4808, self.deposit if has_deposit else 0)
        u.mem_write(self.deposit+4, bytes((21, 19, int(installed))))
        put(u, self.deposit+0x10, extracted)
        put(u, self.deposit+0x14, carried)
        put(u, 0xac5a30, DATA+0x2600)
        u.mem_write(DATA+0x2600, bytes((mode,)))
        put(u, 0xac637c, DATA+0x2700)
        put(u, DATA+0x2700, DATA+0xc000)
        u.mem_write(DATA+0xc000+0x68d, b'\1')
        put(u, self.handle, self.transport)
        put(u, self.transport, DATA+0x2800)
        put(u, DATA+0x2800, self.flush)
        put(u, 0xac600c, self.handle)
        put(u, 0xac622c, DATA+0x2900)
        put(u, DATA+0x2900, DATA+0x2a00)
        u.hook_add(UC_HOOK_CODE, self.hook)

    def hook(self, u, address, size, user):
        result = {
            0xa842f0: 1,  # External script policy; native active-actor loop still executes.
            0x99f5d8: 0, 0xa7b030: 0, 0x66754c: 1, 0xa93eec: 1,
            0x6748b0: self.handle, 0x6e9318: self.amount,
        }
        if address in result:
            u.reg_write(UC_X86_REG_EAX, result[address]); ret(u)
        elif address == self.flush:
            n = get(u, self.transport+0x1004)
            self.packets.append(bytes(u.mem_read(self.transport+4, n)))
            put(u, self.transport+0x1004, 0)
            ret(u)
        elif address == 0x6e9324:
            self.dialogs.append(tuple(u.reg_read(reg) for reg in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX)))
            ret(u)
        elif address == 0x6e9478:
            self.callbacks.append(u.reg_read(UC_X86_REG_EAX)); ret(u)
        elif address in (0x40cb10, 0x40b09c, 0x40c9a4, 0x40b0fc,
                         0x6675e0, 0x6e9640, 0xa3ebf4):
            ret(u)

    def run(self, entry):
        put(self.u, STACK+0x8000, STOP)
        self.u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
        self.u.emu_start(entry, STOP, count=12000)
        assert self.u.reg_read(UC_X86_REG_EIP) == STOP
        assert self.u.reg_read(UC_X86_REG_ESP) == STACK+0x8004


def verify(raw):
    cases = []
    f = Fixture(raw)
    f.run(0x8143f4)
    assert len(f.packets) == 1 and not f.dialogs
    assert decode_item_action(f.packets[0]) == ItemAction(17, 0xff001234, 255)
    cases.append(dict(case='empty deposit, carried drill', packet=f.packets[0].hex()))
    for name, kw in (
        ('no selected actor', dict(selected=False)),
        ('no hovered deposit', dict(has_deposit=False)),
        ('no drill inventory', dict(has_drill=False)),
        ('other cursor mode', dict(mode=0)),
    ):
        f = Fixture(raw, **kw); f.run(0x8143f4)
        assert not f.packets and not f.dialogs
        cases.append(dict(case=name, packet=None))
    for capacity, weight, extracted, carried, maximum in (
        (1000, 440, 300, 50, 300),
        (640, 440, 300, 50, 100),
        (440, 440, 300, 50, 50),
        (1000, 440, 0, 0, 0),
    ):
        f = Fixture(raw, installed=True, capacity=capacity, weight=weight, extracted=extracted, carried=carried)
        f.run(0x8143f4)
        assert not f.packets and f.dialogs == [(carried, maximum, maximum)]
        assert f.callbacks == [0x8143c4]
        # Original confirmation callback obtains the chosen amount from the
        # dialog and forwards the saved actor/XY to the real B015 serializer.
        f.amount = maximum
        f.run(0x8143c4)
        assert len(f.packets) == 1
        assert decode_pickup(f.packets[0]) == (17, 21, 19, maximum)
        cases.append(dict(case='installed deposit', capacity=capacity, weight=weight,
                          extracted=extracted, carried=carried, dialog=f.dialogs[0],
                          packet=f.packets[0].hex()))
    return dict(passed=True, cases=cases, original_bodies=[dict(va=hex(va), bytes=n, sha256=digest) for va,n,digest in BODIES],
                limitation=__doc__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--source-sha256', default=SOURCE_SHA)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args.source_sha256: raise ValueError('Client SHA256 differs from reviewed source')
    result = dict(source=str(args.source.resolve()), source_sha256=digest, **verify(raw))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as out: out.write(json.dumps(result, indent=2)+'\n')
    print('Native drill click, quantity-dialog bounds and 33/B015 writers: 9 cases PASS')


if __name__ == '__main__': main()
