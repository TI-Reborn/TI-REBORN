"""Original target-armor damage reduction a7aa58 against a Python model.

The weapon damage preview (a7a758, a7a8a2) and the ability preview (8b6052)
call a7aa58 with the selected target's ArmorClass (+0x6010). It runs
unchanged here, including Math.Power 43eddc and Trunc 407438; only the actor
table [0xac618c] is supplied. This is the client's preview, not proof of the
historical server formula.
"""
import math
import random
from verify_auth_native import *

FUNCTION = 0xa7aa58
ACTORS = 0xac618c
ARMOR = 0x6010
NO_TARGET = 0xffffffff


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def model(damage, armor):
    """Single-precision intermediates, as the client stores them in floats."""
    factor = f32(min(armor, 370)**1.2/25)
    reduction = f32(max(damage-10, 4)**0.8*factor/20)
    return max(0, math.trunc(damage-reduction))


def native(low, high, armor, *, target=3):
    u = emulator(); table = DATA+0x100; actor = DATA+0x10000; low_at = DATA+0x40; high_at = DATA+0x44
    u.mem_map(actor, 0x8000)  # the actor record reaches +0x6010
    put32(u, ACTORS, table); put32(u, table+3*4, actor); put32(u, actor+ARMOR, armor)
    u.mem_write(low_at, struct.pack('<ff', low, high))
    sp = u.reg_read(UC_X86_REG_ESP)-4
    u.mem_write(sp, struct.pack('<II', STOP, high_at)); u.reg_write(UC_X86_REG_ESP, sp)
    u.reg_write(UC_X86_REG_EDX, target); u.reg_write(UC_X86_REG_ECX, low_at)
    u.emu_start(FUNCTION, STOP, count=200000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    return struct.unpack('<ff', u.mem_read(low_at, 8))


def cases():
    rng = random.Random(20261029)
    fixed = [(50, 60, 100), (10, 20, 0), (100, 150, 220), (30, 40, 370), (30, 40, 600), (5, 8, 160), (15, 25, 370)]
    return fixed + [(rng.randint(1, 300), rng.randint(1, 400), rng.randint(0, 500)) for _ in range(300)]


if __name__ == '__main__':
    checked = []
    for low, high, armor in cases():
        got = native(low, high, armor)
        assert got == (model(low, armor), model(high, armor)), ((low, high, armor), got)
        checked.append(dict(low=low, high=high, armor=armor, result=list(got)))
    assert native(50, 60, 300, target=NO_TARGET) == (50, 60)
    (ROOT/'evidence/armor_reduction_native.json').write_text(json.dumps(dict(sha256=EXPECTED_SHA,
        method=__doc__, model='trunc(d - max(d-10,4)^0.8 * min(A,370)^1.2 / 500), not below 0',
        cases=checked), indent=2)+'\n')
    print(f'Original a7aa58 matches the model: {len(checked)} cases and no-target PASS')
