"""Exercise the exact Silver camera hook at its preferred and relocated bases."""
from __future__ import annotations

import argparse
from pathlib import Path
from struct import pack
import sys
import unittest

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32
from unicorn.x86_const import (
    UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EDI,
    UC_X86_REG_EDX, UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.client_battle_shot_camera import (
    BASE, FOCUS, PLAYBACK, CREATE, PROJECTILE_FOCUS, HIT_FOCUS, focus_code,
    playback_code, policy_code, impact_code, strings, MARK_SHOT, SHOT_ACTOR,
    SHOT_TIME, NATIVE_TICK, mark_shot_code,
)


DATA = 0x20000000
SNAPSHOT_CALL = 0x8c5c96
PLAYBACK_CALL = 0x95f38b
PROJECTILE_CALLS = (0x95fcf9, 0x9600b4)
HIT_CALLS = (0x961726, 0x961863, 0x9619a0)
NATIVE_FOCUS = 0xa88a78


class CameraHookTests(unittest.TestCase):
    candidate: Path

    def setUp(self) -> None:
        entrypoints = ((SNAPSHOT_CALL, FOCUS), (PLAYBACK_CALL, PLAYBACK),
                       *((site, PROJECTILE_FOCUS) for site in PROJECTILE_CALLS),
                       *((site, HIT_FOCUS) for site in HIT_CALLS))
        impact = impact_code(strings()[1])
        with pefile.PE(str(self.candidate)) as image:
            self.calls = {site: image.get_data(site - BASE, 5)
                          for site, _ in entrypoints}
            self.focus = image.get_data(FOCUS - BASE, CREATE - FOCUS)
            self.impact = image.get_data(PROJECTILE_FOCUS - BASE, len(impact))
            self.assertEqual(image.get_data(MARK_SHOT - BASE, 0x68), mark_shot_code() + bytes(8))
            self.assertEqual(image.get_data(0x95fab4 - BASE, 5),
                             b'\xe8' + pack('<i', MARK_SHOT - 0x95fab4 - 5))
        self.assertEqual(self.focus, focus_code() + playback_code() + policy_code(strings()[1]))
        self.assertEqual(self.impact, impact)
        for site, destination in entrypoints:
            self.assertEqual(self.calls[site], b'\xe8' + pack('<i', destination - site - 5))

    def run_focus(self, mode: int, sequence: int, screen: tuple[int, int],
                  *, base: int, caller: int = SNAPSHOT_CALL, own: bool = True,
                  actor_index: int = 1, shot_age: int | None = 0) -> bool:
        cpu = Uc(UC_ARCH_X86, UC_MODE_32)
        cpu.mem_map(base, 0x930000)
        cpu.mem_map(DATA, 0xb000)
        delta = base - BASE
        cpu.mem_write(caller + delta, self.calls[caller])
        cpu.mem_write(FOCUS + delta, self.focus)
        cpu.mem_write(PROJECTILE_FOCUS + delta, self.impact)
        cpu.mem_write(0x688328 + delta, bytes.fromhex('31c931d2b8') + pack('<i', mode) + b'\xc3')
        cpu.mem_write(NATIVE_FOCUS + delta, b'\xc3')
        calls = []
        cpu.hook_add(UC_HOOK_CODE, lambda *_: calls.append(True),
                     begin=NATIVE_FOCUS + delta, end=NATIVE_FOCUS + delta)
        tile_x, tile_y = 19, 26
        x, y = screen
        for native, cell, value in (
            (0xac61b0, DATA + 0x100, x - (tile_y - tile_x) * 32),
            (0xac6068, DATA + 0x104, y - (tile_x + tile_y) * 16 - 16),
            (0xac56e0, DATA + 0x108, 1024),
            (0xac5e60, DATA + 0x10c, 768),
        ):
            cpu.mem_write(native + delta, pack('<I', cell))
            cpu.mem_write(cell, pack('<i', value))
        cpu.mem_write(0xac618c + delta, pack('<I', DATA + 0x200))
        # Actor index is nonzero, and different from ECX.
        actor = DATA + 0x4000
        cpu.mem_write(DATA + 0x204, pack('<I', actor))
        cpu.mem_write(base + NATIVE_TICK, pack('<I', DATA + 0x110))
        cpu.mem_write(DATA + 0x110, pack('<I', 5000))
        if shot_age is not None:
            cpu.mem_write(base + SHOT_ACTOR, pack('<I', actor))
            cpu.mem_write(base + SHOT_TIME, pack('<I', 5000 - shot_age))
        cpu.mem_write(actor + 0x60b2, pack('<H', sequence))
        cpu.mem_write(actor + 0x41, bytes((own,)))
        cpu.mem_write(actor + 0x603c, pack('<II', tile_x, tile_y))
        frame = DATA + 0x3800
        cpu.mem_write(frame - 0x2e0, pack('<I', tile_x))
        cpu.mem_write(frame - 0x2e4, pack('<I', tile_y))
        cpu.mem_write(frame - 8, pack('<i', actor_index))
        registers = {
            UC_X86_REG_EAX: DATA + 0x500, UC_X86_REG_EBX: actor_index & 0xffffffff,
            UC_X86_REG_ECX: 0x1234, UC_X86_REG_EDI: DATA + 0x600,
            UC_X86_REG_ESI: DATA + 0x200 if caller == SNAPSHOT_CALL else 1, UC_X86_REG_EDX: 2,
            UC_X86_REG_EBP: frame, UC_X86_REG_ESP: DATA + 0x4800,
            UC_X86_REG_EFLAGS: 0x246,
        }
        for reg, value in registers.items():
            cpu.reg_write(reg, value)
        cpu.emu_start(caller + delta, caller + delta + 5, count=110)
        self.assertEqual(cpu.reg_read(UC_X86_REG_EIP), caller + delta + 5)
        self.assertEqual({reg: cpu.reg_read(reg) for reg in registers}, registers)
        return bool(calls)

    def test_focus_respects_mode_and_native_viewport_edges(self) -> None:
        for base in (BASE, 0x54000000):
            for mode, sequence, point, expected in (
                (0, 2, (500, 400), True),
                (0, 2, (980, 600), True),
                (1, 2, (500, 400), False),
                (1, 2, (0, 0), False),
                (1, 2, (1023, 767), False),
                (1, 2, (-1, 100), True),
                (1, 2, (1024, 100), True),
                (1, 2, (500, -1), True),
                (1, 2, (500, 768), True),
                (2, 2, (500, 400), False),
                (2, 2, (500, 600), False),
                (2, 0, (500, 400), False),
                (2, 12, (500, 400), False),
                (-1, 2, (500, 400), True),
                (3, 2, (500, 400), True),
            ):
                with self.subTest(base=hex(base), mode=mode, sequence=sequence, point=point):
                    self.assertEqual(self.run_focus(mode, sequence, point, base=base), expected)

    def test_unrelated_and_expired_actor_refreshes_use_stock_focus(self) -> None:
        for shot_age in (None, 3001):
            with self.subTest(shot_age=shot_age):
                self.assertTrue(self.run_focus(2, 12, (500, 400), base=BASE, shot_age=shot_age))

    def test_playback_uses_same_modes_and_preserves_enemy_focus(self) -> None:
        for mode, own, point, expected in (
            (0, True, (500, 400), True),
            (1, True, (500, 400), False),
            (1, True, (1024, 400), True),
            (2, True, (-1, 400), False),
            (2, False, (-1, 400), True),
        ):
            with self.subTest(mode=mode, own=own, point=point):
                self.assertEqual(self.run_focus(mode, 0, point, base=0x54000000,
                                               caller=PLAYBACK_CALL, own=own), expected)

    def test_only_default_and_enemy_attacks_keep_impact_focus(self) -> None:
        for site in (*PROJECTILE_CALLS, *HIT_CALLS):
            for mode, own, index, expected in (
                (0, True, 1, True),
                (1, True, 1, False),
                (2, True, 1, False),
                (2, False, 1, True),
                (2, False, -1, True),
            ):
                with self.subTest(site=hex(site), mode=mode, own=own, index=index):
                    self.assertEqual(self.run_focus(mode, 0, (500, 400), base=0x54000000,
                                                   caller=site, own=own, actor_index=index), expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    CameraHookTests.candidate = parser.parse_args().candidate
    unittest.main(argv=[sys.argv[0]], verbosity=2)
