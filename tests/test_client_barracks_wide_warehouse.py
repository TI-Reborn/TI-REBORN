import unittest

from deploy import client_barracks_wide_warehouse as wide
from deploy import client_warehouse_chat as chat
from tests import test_client_warehouse_chat as native


@unittest.skipUnless(native.Uc, 'Unicorn is required for native barracks checks')
class WideWarehouseTests(unittest.TestCase):
    def test_toggle_moves_live_viewport_and_restores_preview_visibility(self):
        f = native.WarehouseChatTests()
        f.setUp()
        left, bag, tabs, model, skill, panel, vector, search, footer, owners, filters = (
            f.heap+i*0x400 for i in range(9,20)
        )
        for address, obj in ((wide.LEFT,left),(wide.BAG,bag),(wide.TABS,tabs),(wide.SKILL_TAB,skill),
                             (wide.OWNERS,owners)):
            f.write(f.at(address),obj)
        f.write(left+0x30,50,118,964,558)
        f.write(left+0x4c,f.page)
        f.write(bag+0x38,414)
        f.write(skill+0x4c,panel)
        f.write(panel+0x4c,f.page)
        f.write(left+0x2c,vector)
        f.write(vector+4,vector+0x20,3)
        f.write(vector+0x28,model)
        f.write(f.table+0x2c,footer)
        f.write(footer+4,footer+0x20,16)
        f.write(footer+0x20+6*4,filters)
        f.write(footer+0x20+13*4,search)
        f.write(owners+0x4c,f.page)
        f.write(owners+0x30,1152)
        f.write(filters+0x30,549)
        f.write(search+0x30,508)
        for widget in (model,tabs):
            f.uc.mem_write(widget+0x49,b'\x01')
        f.uc.mem_write(f.at(chat.FRAME),chat.frame_code(layout=wide.WAREHOUSE))
        for addr, code in ((wide.WAREHOUSE,wide.warehouse_code()),(wide.RESIZE,wide.resize_code()),
                           (wide.VISIBILITY,wide.visibility_code())):
            f.uc.mem_write(f.at(addr),code)
        f.write(f.base+wide.REQUESTED,1)
        for _ in range(2):
            f.frame()
            self.assertEqual(f.read(f.table+0x30),504)
            self.assertEqual(f.read(f.table+0x38),1198)
            self.assertEqual(f.read(search+0x30),1032)
            self.assertEqual(f.read(owners+0x30),628)
            self.assertEqual(f.read(filters+0x30),0)
            self.assertEqual([f.read(x+0x49) & 255 for x in (model,panel,tabs)],[0,0,0])
        f.write(f.base+wide.REQUESTED,0)
        f.frame()
        self.assertEqual(f.read(f.table+0x30),1028)
        self.assertEqual(f.read(f.table+0x38),674)
        self.assertEqual(f.read(search+0x30),508)
        self.assertEqual(f.read(owners+0x30),1152)
        self.assertEqual(f.read(filters+0x30),549)
        self.assertEqual([f.read(x+0x49) & 255 for x in (model,panel,tabs)],[1,0,1])
