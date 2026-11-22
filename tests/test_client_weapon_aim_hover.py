"""Replay the native hover and post-shot animation paths with isolated graphics calls."""
from pathlib import Path
from struct import pack, unpack
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
                               UC_X86_REG_EIP, UC_X86_REG_ESP)


SOURCE = Path(__file__).resolve().parents[1] / 'work/weapon-aim-hover-20261121/source-silver.dll'
BASE = 0x400000
DATA, STACK, STOP = 0x2000000, 0x2100000, 0x2110000
ACTOR, ENEMY, TABLE = DATA, DATA + 0x8000, DATA + 0x10000
SP = STACK + 0x8000
NOW, MODE, OPTION = TABLE + 0x100, TABLE + 0x104, TABLE + 0x108


class NativeAim:
    def __init__(self, raw: bytes, delta: int):
        self.delta = delta
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        with pefile.PE(data=raw) as pe:
            image = pe.get_memory_mapped_image(ImageBase=BASE + delta)
            self.uc.mem_map(BASE + delta, (pe.OPTIONAL_HEADER.SizeOfImage + 0xfff) & ~0xfff)
            self.uc.mem_write(BASE + delta, image)
        self.uc.mem_map(DATA, 0x20000)
        self.uc.mem_map(STACK, 0x20000)
        for slot, pointer in ((0xac618c, TABLE), (0xac5fe4, NOW), (0xac5a30, MODE),
                              (0xac5db8, OPTION), (0xac61b0, TABLE), (0xac6068, TABLE)):
            self.put(slot + delta, pointer)
        self.put(TABLE, ACTOR)
        self.put(TABLE + 4, ENEMY)
        self.put(ENEMY + 0x6006, 100, 'H')
        self.put(ENEMY + 0x603c, 12)
        self.put(ENEMY + 0x6040, 8)
        self.put(ACTOR + 0x41, 1, 'B')
        self.put(ACTOR + 0x6004, 12, 'B')
        self.put(ACTOR + 0x6098, -1, 'i')
        self.put(ACTOR + 0x609c, -1, 'i')
        self.hovering = True
        self.selected = 0
        self.busy = False
        self.occluded = False
        self.clips = []
        self.uc.hook_add(UC_HOOK_CODE, self.boundary)

    def put(self, address, value, fmt='I'):
        self.uc.mem_write(address, pack('<'+fmt, value))

    def get(self, address, fmt='I'):
        return unpack('<'+fmt, self.uc.mem_read(address, len(pack('<'+fmt, 0))))[0]

    def boundary(self, uc, address, _size, _data):
        va = address - self.delta
        stubs = {0xa843d4: self.selected & 0xffffffff, 0x95dbb8: int(self.occluded),
                 0xa867e0: 0, 0xa84248: int(self.hovering), 0xa7b098: 3,
                 0xa867c0: 0, 0xa867d0: 0, 0xa896f0: 0, 0x68a840: int(self.busy)}
        stack = uc.reg_read(UC_X86_REG_ESP)
        if va == 0xa84704:
            actor = uc.reg_read(UC_X86_REG_EAX)
            sequence = uc.reg_read(UC_X86_REG_EDX)
            # Record the native animation boundary. Native seq12 does not replay
            # its clip when retargeting from seq12.
            if self.get(actor + 0x60b2, 'H') != sequence:
                self.clips.append(sequence)
            self.put(actor + 0x60b2, sequence, 'H')
            if sequence in (0, 15):
                self.put(actor + 0x6098, -1, 'i')
                self.put(actor + 0x609c, -1, 'i')
                self.put(actor + 0x60a8, 0, 'B')
            uc.reg_write(UC_X86_REG_ESP, stack + 12)
            uc.reg_write(UC_X86_REG_EIP, self.get(stack))
        elif va in stubs:
            uc.reg_write(UC_X86_REG_EAX, stubs[va])
            uc.reg_write(UC_X86_REG_ESP, stack + 4)
            uc.reg_write(UC_X86_REG_EIP, self.get(stack))

    def hover(self, mode=1):
        self.put(MODE, mode, 'B')
        self.put(SP, STOP)
        self.uc.reg_write(UC_X86_REG_ESP, SP)
        self.uc.emu_start(0x9eefe0 + self.delta, STOP, count=2500)
        if self.uc.reg_read(UC_X86_REG_EIP) != STOP:
            raise AssertionError('Native hover did not return')

    def process(self, tick):
        self.put(NOW, tick)
        self.uc.reg_write(UC_X86_REG_EDI, ACTOR)
        self.uc.reg_write(UC_X86_REG_ESP, SP)
        until = 0xa8651d + self.delta
        self.uc.emu_start(0xa86492 + self.delta, until, count=1200)
        if self.uc.reg_read(UC_X86_REG_EIP) != until:
            raise AssertionError('Native post-shot processing did not return')

    def inventory_idle(self, call):
        self.put(SP, 0)
        self.put(SP + 4, 0)
        self.uc.reg_write(UC_X86_REG_EAX, ACTOR)
        self.uc.reg_write(UC_X86_REG_EDX, 0)
        self.uc.reg_write(UC_X86_REG_ECX, 0xffffffff)
        self.uc.reg_write(UC_X86_REG_ESP, SP)
        self.uc.emu_start(call + self.delta, call + self.delta + 5, count=1200)
        if self.uc.reg_read(UC_X86_REG_ESP) != SP + 8:
            raise AssertionError('Native inventory callback stack changed')


@unittest.skipUnless(SOURCE.is_file(), 'retained hosted Silver baseline required')
class WeaponAimHoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from deploy.client_weapon_aim_hover import patch

        cls.raw = patch(SOURCE.read_bytes())

    def test_hover_keeps_aim_across_two_native_fire_sequences(self):
        for base_delta in (0, 0x14000000):
            with self.subTest(base_delta=base_delta):
                game = NativeAim(self.raw, base_delta)
                game.hover()
                self.assertEqual(game.clips, [12])
                self.assertEqual((game.get(ACTOR + 0x6098), game.get(ACTOR + 0x609c)), (12, 8))
                for tick in (1000, 11000):
                    # Enter the firing state normally started by the server response.
                    game.put(ACTOR + 0x60b2, 2, 'H')
                    game.busy = True
                    game.process(tick)
                    game.hover(mode=0)  # Stock click handler briefly clears the cursor mode.
                    self.assertEqual(game.get(ACTOR + 0x60b2, 'H'), 2)
                    game.busy = False
                    game.process(tick + 8000)
                    self.assertEqual(game.get(ACTOR + 0x60b2, 'H'), 12)
                    game.hover()
                self.assertEqual(game.clips, [12])

    def test_ground_lowers_promptly_and_rehover_raises_once(self):
        game = NativeAim(self.raw, 0)
        game.hover()
        game.process(100)
        game.hover()
        game.process(116)
        game.hovering = False
        game.hover(mode=0)
        game.process(132)
        self.assertEqual(game.clips, [12, 15])
        game.put(ACTOR + 0x60b2, 0, 'H')  # Native lower clip finished.
        game.hovering = True
        game.hover()
        game.process(900)
        game.hover()
        self.assertEqual(game.clips, [12, 15, 12])

    def test_losing_hover_does_not_cut_off_shot_or_apply_to_remote_actor(self):
        game = NativeAim(self.raw, 0)
        game.hover()
        game.process(1)
        game.put(ACTOR + 0x60b2, 2, 'H')
        game.busy = True
        game.occluded = True
        game.hover(mode=0)
        game.process(400)
        self.assertEqual(game.get(ACTOR + 0x60b2, 'H'), 2)
        game.busy = False
        game.process(800)
        self.assertEqual(game.clips, [12, 15])
        game.put(ACTOR + 0x60b2, 2, 'H')
        game.process(1000)
        game.process(5999)
        self.assertEqual(game.clips, [12, 15])
        game.process(6001)
        self.assertEqual(game.clips, [12, 15, 15])

    def test_retarget_during_shot_preserves_original_fire_direction(self):
        game = NativeAim(self.raw, 0)
        game.hover()
        game.put(ACTOR + 0x60b2, 2, 'H')
        game.put(ENEMY + 0x603c, 13)
        game.hover()
        self.assertEqual(game.get(ACTOR + 0x6098), 12)
        self.assertEqual(game.clips, [12])

    def test_inventory_refresh_keeps_pose_until_the_weapon_changes(self):
        game = NativeAim(self.raw, 0x14000000)
        game.hover()
        game.put(ACTOR + 0x38, 301)  # Mesh's previous active weapon metadata index.
        game.put(ACTOR + 0xdf4, 301)
        for call, sequence in ((0xa85a1e, 2), (0x8c5f4a, 12)):
            game.put(ACTOR + 0x60b2, sequence, 'H')
            game.inventory_idle(call)
            self.assertEqual(game.get(ACTOR + 0x60b2, 'H'), sequence)
            self.assertEqual(game.get(ACTOR + 0x6098), 12)
        game.put(ACTOR + 0xdf4, 302)
        game.inventory_idle(0x8c5f4a)
        self.assertEqual(game.get(ACTOR + 0x60b2, 'H'), 0)
        self.assertEqual(game.get(ACTOR + 0x6098, 'i'), -1)


if __name__ == '__main__':
    unittest.main()
