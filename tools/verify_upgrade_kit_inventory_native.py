"""Original IsSimpleUpgradeKit and all six HideUpgradeBoxes UI gates.

Run real predicates/branches with synthetic panel and item memory; drawing,
mouse coordinates and native windows themselves are not simulated.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EFLAGS


def main():
    u = emulator(); panel, item = DATA+0x1000, DATA+0x2000
    gates = ((0x9bc62a, 0x9bc640, 0x9bc98b),  # render
             (0x9bcafd, 0x9bcb0f, 0x9bcb2d),  # layout
             (0x9bce56, 0x9bce68, 0x9bcee6),  # hit-test
             (0x9be89d, 0x9be8b3, 0x9bec4a),  # click
             (0x9bee12, 0x9bee28, 0x9beecd),
             (0x9bf063, 0x9bf079, 0x9bf17e))
    cases = []
    for entry, visible, skipped in gates:
        for template in (30, 19, 301):
            for hidden in (0, 1):
                put32(u, item+8, template); u.mem_write(panel+0x2a2, bytes((hidden,)))
                u.reg_write(UC_X86_REG_EAX, item); u.reg_write(UC_X86_REG_EBX, panel)
                u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
                reached = []
                def hook(uc, address, size, user):
                    if address in (visible, skipped):
                        reached.append(address); uc.emu_stop()
                handle = u.hook_add(UC_HOOK_CODE, hook)
                u.emu_start(entry, STOP, count=100)
                u.hook_del(handle)
                expected = skipped if template == 30 and hidden else visible
                assert reached == [expected], (hex(entry), template, hidden, reached)
                cases.append(dict(gate=hex(entry), template=template, hidden=hidden, visible=expected == visible))
    # The compatibility hooks run immediately AFTER each original flag store.
    for store, hook in ((0x9a7f3a, 0x9a7f41), (0x9ba21b, 0x9ba222)):
        u.mem_write(panel+0x2a1, b'\x11\0\x22')
        u.reg_write(UC_X86_REG_EAX, panel)
        u.emu_start(store, hook, count=10)
        assert bytes(u.mem_read(panel+0x2a1, 3)) == b'\x11\1\x22'
        u.mem_write(panel+0x2a2, b'\0')
        assert bytes(u.mem_read(panel+0x2a1, 3)) == b'\x11\0\x22'
    # Original selection policy for itype13 Upgrade Kit enters targeting mode1
    # and saves the physical kit instance. No equip request or use is fabricated.
    closure, table = DATA+0x3000, DATA+0x4000
    put32(u, 0xac637c, DATA+0xf000); put32(u, DATA+0xf000, table)
    u.mem_write(table+0x118, b'\x0d\0')
    put32(u, closure+0x18, 30); put32(u, closure+0x38, 1062)
    from unicorn.x86_const import UC_X86_REG_ESI
    u.reg_write(UC_X86_REG_EBX, closure); u.reg_write(UC_X86_REG_ESI, 0)
    u.emu_start(0xa659a6, 0xa65b58, count=100)
    selection = dict(mode=bytes(u.mem_read(0xac4daf, 1))[0], instance=get32(u, 0xac4db0), template=get32(u, 0xac4db4))
    assert selection == dict(mode=1, instance=1062, template=30)
    warehouse = []
    # Both list-building paths normally overwrite an accepted item with false
    # solely because it is template30. Remove just those two-byte XORs.
    for entry, store, end in ((0x9159ee, 0x9159f7, 0x9159f9),
                              (0x9171a9, 0x9171b2, 0x9171b4)):
        assert bytes(u.mem_read(store, 2)) == b'\x33\xdb'
        for patched in (False, True):
            u.mem_write(store, b'\x90\x90' if patched else b'\x33\xdb')
            # Invalidate translated code after changing original instructions.
            u.ctl_remove_cache(entry, end)
            for template in (30, 19, 301):
                for accepted in (0, 1):
                    put32(u, item+8, template)
                    u.reg_write(UC_X86_REG_EAX, item); u.reg_write(UC_X86_REG_EBX, accepted)
                    u.reg_write(UC_X86_REG_ESP, STACK+0x8000)
                    u.emu_start(entry, end, count=100)
                    actual = u.reg_read(UC_X86_REG_EBX)
                    expected = 0 if template == 30 and not patched else accepted
                    assert actual == expected
                    warehouse.append(dict(entry=hex(entry), patched=patched, template=template,
                                          previous_filter=accepted, result=actual))
        u.mem_write(store, b'\x33\xdb')
    (ROOT/'evidence/upgrade_kit_inventory_native.json').write_text(json.dumps(dict(
        sha256=EXPECTED_SHA, method=__doc__, cases=cases, selection=selection,
        warehouse_filters=warehouse), indent=2)+'\n')
    print('Original kit UI: 36 inventory + 24 warehouse filter cases, 2 panel flag stores, kit targeting PASS')


if __name__ == '__main__': main()
