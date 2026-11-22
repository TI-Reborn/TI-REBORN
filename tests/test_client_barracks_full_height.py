import unittest

from deploy import client_barracks_full_height as height
from deploy import client_warehouse_chat as chat
from tests import test_client_warehouse_chat as native

if native.Uc:
    from unicorn import UC_HOOK_CODE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP


@unittest.skipUnless(native.Uc, 'Unicorn is required for native barracks checks')
class FullHeightBarracksTests(unittest.TestCase):
    def test_extends_real_bag_and_nav_once_and_reflows_on_exit(self):
        f = native.WarehouseChatTests()
        f.setUp()
        left, bag, tabs, model, weight, children = (f.heap+i*0x400 for i in range(9, 15))
        f.write(f.at(height.LEFT), left)
        f.write(f.at(height.BAG), bag)
        f.write(f.at(height.TABS), tabs)
        f.write(left+0x30, 50, 118, 964, 558)
        f.write(left+0x4c, f.page)
        f.write(bag+0x30, 15, 345, 414, 186)
        f.write(bag+0x4c, left)
        f.write(tabs+0x30, 554, 612, 400, 56)
        f.write(model+0x30, 501, 0, 297, 448)
        f.write(left+0x2c, children)
        f.write(children+4, children+0x20, 27)
        f.write(children+0x20+2*4, model)
        f.write(children+0x20+26*4, weight)
        layout_restored = []

        def resize(uc, address, _size, _data):
            if address == f.at(height.ITEMS_VIEW):
                self.assertEqual(uc.reg_read(UC_X86_REG_EAX), bag)
                f.write(bag+0x3c, uc.reg_read(UC_X86_REG_EDX))
            else:
                layout_restored.append(f.read(f.page+0x3c))
            sp = uc.reg_read(UC_X86_REG_ESP)
            uc.reg_write(UC_X86_REG_EIP, f.read(sp))
            uc.reg_write(UC_X86_REG_ESP, sp+4)

        for site in (height.ITEMS_VIEW, height.LAYOUT):
            f.uc.hook_add(UC_HOOK_CODE, resize, begin=f.at(site), end=f.at(site))
        f.uc.mem_write(f.at(chat.FRAME), chat.frame_code(layout=height.REFLOW, restore=height.LAYOUT))
        f.uc.mem_write(f.at(height.REFLOW), height.reflow_code())
        for _ in range(2):
            f.frame()
            self.assertEqual(f.read(left+0x3c), 838)
            self.assertEqual(f.read(bag+0x3c), 434)
            self.assertEqual(f.read(weight+0x34), 786)
            self.assertEqual(f.read(tabs+0x34), 892)
            self.assertEqual(f.read(model+0x38), 445)
        f.uc.mem_write(f.table+0x49, b'\x00')
        f.frame()
        self.assertEqual(layout_restored, [768])
