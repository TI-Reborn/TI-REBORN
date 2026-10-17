"""Original item count parser, stack metadata write and quantity-dialog gates.

The XML boolean lookup is stubbed with the actual generated catalog value.
Rendering/dialog creation is not emulated; original gates select their paths.
"""
from verify_auth_native import *
from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_EDI
import xml.etree.ElementTree as ET
from tio.protocol.item_list import ItemRecord, encode_item_list
from tio.protocol.warehouse import warehouse_item_from_inventory
from verify_warehouse_native import run as warehouse_wire


def check(template, count, stackable):
    u = emulator()
    indirect, table, closure, obj = DATA+0x1000, DATA+0x2000, DATA+0x3000, DATA+0x4000
    put32(u, 0xac637c, indirect); put32(u, indirect, table)
    put32(u, closure+0xc, 0)
    def hook(uc, address, size, user):
        if address == 0x680860:
            assert uc.reg_read(UC_X86_REG_EDX) == 0xa75688  # XML key "stackable"
            uc.reg_write(UC_X86_REG_EAX, stackable); return_from_stub(uc)
        elif address == 0x40b09c:
            return_from_stub(uc)
    u.hook_add(UC_HOOK_CODE, hook)
    u.reg_write(UC_X86_REG_EBX, closure); u.reg_write(UC_X86_REG_EDI, 0)
    u.emu_start(0xa733b3, 0xa733d7, count=100)
    assert bytes(u.mem_read(table+0x68b, 1)) == bytes((stackable,))
    record = ItemRecord(1001, template, bytes(2), count, 0, 0, (1, 1, 1), bytes(4), None, bytes(3))
    body = encode_item_list(1, (record,))[10:]
    u.mem_write(DATA, body); put32(u, 0xacd0e8, DATA)
    u.reg_write(UC_X86_REG_EAX, obj)
    u.emu_start(0x63bd38, STOP, count=5000)
    assert get32(u, obj+0x14) == count
    assert get32(u, 0xacd0e8)-DATA == len(body)
    # Original city quantity-dialog gates; runtime item count lives at+1C.
    put32(u, obj+0x1c, count)
    decisions = []
    for start, yes, no in ((0x998161, 0x99817f, 0x9981a6), (0x99718a, 0x9971ab, 0x9971e6)):
        reached = []
        def stop(uc, address, size, user):
            if address in (yes, no): reached.append(address == yes); uc.emu_stop()
        handle = u.hook_add(UC_HOOK_CODE, stop)
        u.reg_write(UC_X86_REG_EAX, 0); u.reg_write(UC_X86_REG_EBX, obj)
        put32(u, 0xad0da4, count)
        u.emu_start(start, STOP, count=50); u.hook_del(handle)
        assert reached == [bool(stackable and count > 1)], reached
        decisions.extend(reached)
    wire = warehouse_wire(0, 1, 0, (warehouse_item_from_inventory(record),))
    return dict(template=template, count=count, stackable=stackable,
                quantity_dialog_gates=decisions, warehouse=wire)


def main():
    catalog = {int(n.get('id')): {v.get('key'): v.get('val') for v in n.findall('value')}
               for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()}
    cases = [check(template, count, int(catalog[template].get('stackable', '0')))
             for template, count in ((5, 152), (37, 90), (9, 12), (34, 6), (9, 1), (8, 2), (10, 2), (317, 2))]
    (ROOT/'evidence/item_stacking_native.json').write_text(json.dumps(dict(
        sha256=EXPECTED_SHA, method=__doc__, cases=cases, status='PASS'), indent=2)+'\n')
    print('Original stacking metadata/counts/quantity gates/warehouse wire: 8 cases PASS')


if __name__ == '__main__': main()
