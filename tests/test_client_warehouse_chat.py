import struct
import unittest

from deploy import client_warehouse_chat as chat

try:
    from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32
    from unicorn.x86_const import (
        UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP,
        UC_X86_REG_ESI, UC_X86_REG_ESP,
    )
except ImportError:
    Uc = None


@unittest.skipUnless(Uc, 'Unicorn is required for native chat checks')
class WarehouseChatTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x51000000
        self.heap = 0x30000000
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(self.base, 0x900000)
        self.uc.mem_map(self.heap, 0x10000)
        self.manager, self.page, self.table, self.grid, self.window, self.edit = (
            self.heap + n*0x400 for n in range(1, 7)
        )
        self.sp = self.heap+0x8000
        self.stop = self.heap+0x9000
        self.colors = []
        for global_va, widget in ((chat.TABLE, self.table), (chat.GRID, self.grid),
                                  (chat.GUI_MANAGER, self.heap+0x40),
                                  (chat.SCREEN_HEIGHT, self.heap+0x44),
                                  (chat.MOUSE_X, self.heap+0x48), (chat.MOUSE_Y, self.heap+0x4c),
                                  (0xac58dc, self.heap+0x50)):
            self.write(self.at(global_va), widget)
        self.write(self.heap+0x40, self.manager, 1080, 1890, 1060)
        self.write(self.base+chat.STATE, 1)
        self.write(self.page, self.at(0xa31a40))
        self.write(self.page+0x30, 146, 72, 1728, 768)
        self.write(self.table+0x30, 1028, 118, 674, 558)
        self.write(self.grid+0x30, 0, 34, 674, 444)
        self.write(self.window, self.at(chat.CHAT_VMT))
        self.write(self.window+0x30, 0, 824, 1920, 256)
        self.write(self.edit, self.at(0xa2fbd4))
        self.write(self.edit+0x4c, self.window)
        for widget in (self.page, self.window, self.table):
            self.uc.mem_write(widget+0x49, b'\x01')
        self.write(self.table+0x4c, self.page)
        self.write(self.grid+0x4c, self.table)
        self.write(self.manager+0x280, self.heap+0x1e00)
        self.write(self.heap+0x1e04, self.heap+0x1e40, 1)
        self.write(self.heap+0x1e40, self.window)
        for addr, code in (
            (chat.FRAME, chat.frame_code()), (chat.BACKDROP, chat.backdrop_code()),
            (chat.BUTTON, chat.button_code(release_covered_focus=True)),
            (chat.OPEN_DEFAULT, chat.open_default_code()),
            (chat.TAB, chat.tab_code(release_covered_focus=True)),
            (chat.RELEASE_EDIT, chat.release_edit_code()),
            (chat.FOCUS, chat._focused_edit_code()), (chat.CHAT, chat.chat_code()),
            (chat.AUTO_FOCUS, chat.auto_focus_code()),
            (chat.SET_UNREAD, chat.set_unread_code()), (chat.BLINK_UNREAD, chat.blink_unread_code()),
        ):
            self.uc.mem_write(self.at(addr), code)
        for native in (chat.INVENTORY_FOOTER, chat.INVENTORY_VIEW, 0xa45be4, 0xa42a34, 0x4f2888):
            addr = self.at(native)
            self.uc.hook_add(UC_HOOK_CODE, self.native, begin=addr, end=addr)

    def at(self, va):
        return self.base + va-chat.BASE

    def read(self, addr):
        return struct.unpack('<I', self.uc.mem_read(addr, 4))[0]

    def write(self, addr, *values):
        self.uc.mem_write(addr, struct.pack(f'<{len(values)}I', *values))

    def native(self, uc, addr, _size, _data):
        eax = uc.reg_read(UC_X86_REG_EAX)
        if addr in (self.at(chat.INVENTORY_FOOTER), self.at(chat.INVENTORY_VIEW)):
            self.write(eax+0x3c, uc.reg_read(UC_X86_REG_ECX))
        elif addr == self.at(0xa45be4):
            self.assertEqual(eax, self.edit)
            self.write(self.manager+0x298, self.edit if uc.reg_read(UC_X86_REG_EDX) else 0)
        sp = uc.reg_read(UC_X86_REG_ESP)
        if addr == self.at(0x4f2888):
            self.colors.append(self.read(sp+8))
        uc.reg_write(UC_X86_REG_EIP, self.read(sp))
        uc.reg_write(UC_X86_REG_ESP, sp+(20 if addr == self.at(0x4f2888) else 4))

    def run_at(self, entry, end, *, widget=None, edx=0, esi=0):
        self.write(self.sp, self.stop, 1060)
        self.uc.reg_write(UC_X86_REG_EAX, self.manager if widget is None else widget)
        self.uc.reg_write(UC_X86_REG_EDX, edx)
        self.uc.reg_write(UC_X86_REG_ESI, esi)
        self.uc.reg_write(UC_X86_REG_ESP, self.sp)
        self.uc.emu_start(self.at(entry), end, count=2000)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_EIP), end)

    def frame(self):
        self.run_at(chat.FRAME, self.at(chat.FRAME_DRAW+6))

    def arrow(self):
        self.run_at(chat.BUTTON, self.stop)
        self.assertEqual(self.uc.reg_read(UC_X86_REG_ESP), self.sp+8)

    def test_dock_expands_grid_once_and_restores_native_chat_when_leaving(self):
        self.frame()
        self.assertEqual(self.read(self.window+0x34), 1028)
        self.assertEqual(self.read(self.grid+0x3c), 724)
        self.arrow()
        self.frame()
        self.assertEqual(self.read(self.window+0x34), 824)
        self.assertEqual(self.read(self.grid+0x3c), 724)
        self.uc.mem_write(self.table+0x49, b'\x00')
        self.frame()
        self.assertEqual(self.read(self.window+0x34), 824)
        self.assertEqual(self.read(self.page+0x3c), 768)
        self.uc.mem_write(self.table+0x49, b'\x01')
        self.frame()
        self.assertEqual(self.read(self.window+0x34), 1028)

    def test_collapse_releases_keyboard_focus_from_chat(self):
        self.frame()
        self.arrow()
        self.write(self.manager+0x298, self.edit)
        self.arrow()
        self.assertEqual(self.read(self.base+chat.EXPANDED), 0)
        self.assertEqual(self.read(self.manager+0x298), 0)

    def test_arrow_releases_the_covered_warehouse_search(self):
        self.frame()
        self.write(self.edit+0x4c, self.table)
        self.write(self.manager+0x298, self.edit)
        self.arrow()
        self.assertEqual(self.read(self.base+chat.EXPANDED), 1)
        self.assertEqual(self.read(self.manager+0x298), 0)

    def test_opening_from_a_tab_releases_the_covered_warehouse_search(self):
        self.frame()
        self.write(self.edit+0x4c, self.table)
        self.write(self.manager+0x298, self.edit)
        frame, tabs = self.heap+0x2400, self.heap+0x2800
        self.write(frame-4, tabs)
        self.write(tabs+0x4c, self.window)
        self.uc.reg_write(UC_X86_REG_EBP, frame)
        self.run_at(chat.TAB, self.at(chat.TAB_SELECT+6))
        self.assertEqual(self.read(self.base+chat.EXPANDED), 1)
        self.assertEqual(self.read(self.manager+0x298), 0)

    def test_tab_autofocus_is_suppressed_only_inside_the_docked_chat(self):
        self.frame()
        self.run_at(chat.AUTO_FOCUS, self.at(0xa4fabc), widget=self.edit, edx=1)
        self.assertEqual(self.read(self.manager+0x298), 0)
        self.write(self.base+chat.ACTIVE, 0)
        self.run_at(chat.AUTO_FOCUS, self.at(chat.TAB_AUTO_FOCUS+5), widget=self.edit, edx=1)
        self.assertEqual(self.read(self.manager+0x298), self.edit)

    def test_overlay_tint_depends_on_pointer_or_edit_focus(self):
        self.frame()
        self.arrow()
        self.frame()
        for y, focus, alpha in ((790, 0, 0xa6), (900, 0, 0xff), (790, self.edit, 0xff)):
            self.write(self.heap+0x4c, y)
            self.write(self.manager+0x298, focus)
            self.colors.clear()
            self.run_at(chat.CHAT, self.stop, widget=self.window)
            self.assertEqual(self.colors[0] >> 24, alpha)

    def test_selected_tab_can_blink_while_its_messages_are_covered(self):
        self.frame()
        tab, pager = self.heap+0x2400, self.heap+0x2800
        self.write(tab+0x4c, pager)
        self.write(pager+0x4c, self.window)
        self.uc.mem_write(tab+0x4a, b'\x01')
        self.run_at(chat.SET_UNREAD, self.at(0xa4f7e5), esi=tab)
        self.run_at(chat.BLINK_UNREAD, self.at(0xa50948), widget=tab)
        self.arrow()
        self.run_at(chat.SET_UNREAD, self.at(0xa4f7e9), esi=tab)
        self.run_at(chat.BLINK_UNREAD, self.at(0xa50980), widget=tab)
