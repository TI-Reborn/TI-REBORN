"""Execute original enhancement writer, inventory getters and x87 stat arithmetic."""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI
from tio.enhancement import EnhancementRules
from tio.protocol.enhancement import decode_enhancement_request
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.weapon_proficiency import damage_endpoint


def request_case(target, kit):
    u = emulator(); obj = DATA+0x1000
    put32(u, 0xacd0e0, DATA); put32(u, 0xacd0f0, 0)
    put32(u, obj, target); u.mem_write(obj+4, b'\1')
    if kit is not None:
        put32(u, obj+8, kit); u.mem_write(obj+12, b'\1')
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x6419a8, STOP, count=1000)
    assert u.reg_read(UC_X86_REG_EIP) == STOP
    packet = bytes(u.mem_read(DATA, get32(u, 0xacd0f0)))
    decoded = decode_enhancement_request(packet)
    assert (decoded.instance_id, decoded.kit_id) == (target, kit)
    return packet.hex()


def item_case(level, real_level=None):
    real_level = level if real_level is None else real_level
    item = ItemRecord(1001, 301, bytes(2), 1, 0, 0, (365,)*3,
                      bytes((level, 0, 0, 0)), None, bytes((real_level, 0, 0)))
    packet = encode_item_list(1, (item,))[10:]
    u = emulator(); obj = DATA+0x1000
    u.mem_write(DATA, packet); put32(u, 0xacd0e8, DATA)
    def hook(uc, address, size, user):
        if address == 0x40b09c: return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x63bd38, STOP, count=3000)
    assert get32(u, 0xacd0e8) == DATA+len(packet)
    # Native trimmed level drives +4E, tail real level drives saved enhancement.
    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x63c958, STOP, count=100)
    assert u.reg_read(UC_X86_REG_EAX) == level
    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x63cbc4, STOP, count=100)
    assert u.reg_read(UC_X86_REG_EAX) & 255 == real_level
    return dict(effective=level,real=real_level)


def stats_case(level, skill):
    u = emulator(); frame = STACK+0x7000; obj = DATA+0x1000; out = DATA+0x2000
    settings = DATA+0x3000; table = DATA+0x4000
    put32(u, 0xac5ac0, settings); u.mem_write(settings+5, b'\2')
    u.mem_write(obj+0x4e, bytes((level,))); put32(u, frame-4, obj)
    put32(u, frame+0x10, out+4)
    u.mem_write(out, struct.pack('<ff', 50, 75))
    u.reg_write(UC_X86_REG_EBP, frame); u.reg_write(UC_X86_REG_EDI, out)
    u.emu_start(0xa7a525, 0xa7a576, count=1000)
    rules = EnhancementRules()
    bonus = rules.bonus(level)
    assert struct.unpack('<ff', u.mem_read(out, 8)) == (50+bonus, 75+bonus)
    u.mem_write(frame-0x14, struct.pack('<f', skill))
    u.emu_start(0xa7a826, 0xa7a890, count=1000)
    damage = struct.unpack('<ff', u.mem_read(out, 8))
    assert damage == (damage_endpoint(50+bonus, skill), damage_endpoint(75+bonus, skill))
    put32(u, 0xac637c, DATA+0xf000); put32(u, DATA+0xf000, table)
    put32(u, table+0x690, 80); put32(u, frame-8, 0xffffffff)
    u.reg_write(UC_X86_REG_EDI, 0)
    u.emu_start(0xa7ae8c, 0xa7aed6, count=1000)
    armor = u.reg_read(UC_X86_REG_EAX)
    assert armor == 80+rules.bonus(level, armor=True)
    return dict(level=level, skill=skill, damage=damage, armor=armor)


def policy_cases():
    u = emulator(); frame = STACK+0x7000; settings = DATA+0x3000; table = DATA+0x4000
    put32(u, 0xac5ac0, settings); u.mem_write(settings+5, b'\2\x3f\x3f')
    put32(u, 0xac637c, DATA+0xf000); put32(u, DATA+0xf000, table)
    def hook(uc, address, size, user):
        if address == 0xa7b030:
            uc.reg_write(UC_X86_REG_EAX, 0); return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EBP, frame)
    cases = []
    for armor in (False, True):
        u.mem_write(table+0x12d, bytes((int(armor),)))
        for level in (0, 1, 2, 24):
            u.mem_write(frame-0x24a, bytes((level,))); put32(u, frame-0x248, level)
            u.mem_write(frame-0x299, b'\0')
            u.emu_start(0x7c4218, 0x7c42d6, count=1000)
            chance = get32(u, frame-0x2a8)
            assert chance == (100 if level < 2 else 63)
            cases.append(dict(armor=armor, level=level, chance=chance))
    # Run the actual XML default store and maximum-level getter.
    u.reg_write(UC_X86_REG_EAX, 0); u.reg_write(UC_X86_REG_EDX, table)
    u.emu_start(0xa712fd, 0xa71305, count=10)
    u.reg_write(UC_X86_REG_EAX, DATA)
    u.emu_start(0xa7be80, STOP, count=1000)
    assert u.reg_read(UC_X86_REG_EAX) == 25
    return dict(maximum=25, chance_display=cases)


if __name__ == '__main__':
    report = dict(sha256=EXPECTED_SHA, method=__doc__,
        policy=policy_cases(),
        requests=[request_case(1001, k) for k in (None, 1002, 0xffffffff)],
        items=[item_case(l) for l in (0, 1, 2, 3, 25)]+[item_case(e,r) for e,r in ((3,20),(10,25),(15,20))],
        stats=[stats_case(l, s) for l in (0, 1, 2, 3, 5, 10, 15, 20, 25) for s in (35, 100)])
    (ROOT/'evidence/enhancement_native.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Enhancement original x86: max25, 8 chance displays, 3 requests, 8 effective/real item pairs, 18 stat cases PASS')
