"""Prove atlas-only centering against the unchanged .2 native renderer.

Run genuine Silver/TI item loaders and glyph/plate quads, followed by the native
UI GPU-only vertex transformer. Allocation and final GPU calls are fixtures;
the original draw APIs, atlas UV math and UI scaling instructions execute.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

import pefile
from PIL import Image
from unicorn.x86_const import *

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deploy import client_battle_ui_hd as hd
from deploy import client_ui_scale as scale
from tools.verify_battle_ui_hd_native import ActualRenderFixture
from tools.verify_client_ui_scale_native import (Fixture as ScaleFixture, DATA, STACK, END, FRAME, REGS, VALUES)
from tools.verify_ui_hd_icons_native import put, get, close


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def upload(f, vertices, percent):
    """Run the untouched published GPU copy/scale thunk on real native quads."""
    width, height = 3840, 2160  # All four requested scales have >=768 logical rows.
    lw, lh = width * 100 // percent, height * 100 // percent
    for offset, value in ((0, percent), (4, width), (8, height), (0xc, lw), (0x10, lh), (0x14, 1)):
        f.state(offset, value)
    f.u.mem_write(f.base + scale.STATE + 0x1c, struct.pack('<ff', width / lw, height / lh))
    for offset, value in ((0x18, 0x144), (0x1c, 28)):
        put(f.u, f.vb + offset, value)
    put(f.u, FRAME - 4, f.vb)
    put(f.u, f.renderer + 0x299, width); put(f.u, f.renderer + 0x29d, height)
    original = b''.join(struct.pack('<ffffIff', *vertex) for vertex in vertices)
    src, dst = DATA + 0x5000, DATA + 0x6000
    f.u.mem_write(src, original)
    for reg, value in zip(REGS, VALUES):
        f.u.reg_write(reg, value)
    f.u.reg_write(UC_X86_REG_EAX, src); f.u.reg_write(UC_X86_REG_EDX, dst)
    f.u.reg_write(UC_X86_REG_ECX, len(original))
    sp = STACK + 0xf000
    put(f.u, sp, END); f.u.reg_write(UC_X86_REG_ESP, sp)
    before = [f.u.reg_read(reg) for reg in REGS]
    f.u.emu_start(f.va(scale.UPLOAD), END, count=100000)
    assert [f.u.reg_read(reg) for reg in REGS] == before
    assert f.u.reg_read(UC_X86_REG_ESP) == sp + 4
    assert bytes(f.u.mem_read(src, len(original))) == original
    raw = bytes(f.u.mem_read(dst, len(original)))
    output = [list(struct.unpack_from('<ffffIff', raw, i * 28)) for i in range(4)]
    for i, (old, new) in enumerate(zip(vertices, output)):
        close(new[0], old[0] * width / lw); close(new[1], old[1] * height / lh)
        assert raw[i * 28 + 8:(i + 1) * 28] == original[i * 28 + 8:(i + 1) * 28]
    return output


def verify(silver, ti, expected_sha, assets, atlas, registration, output):
    raw = silver.read_bytes()
    assert sha(raw) == expected_sha, 'Unreviewed native baseline'
    pe = pefile.PE(data=raw)
    # The original battle HUD supplies identical origins (including the same
    # pressed offset) for the normal plate and generic action glyph.
    geometry = bytes.fromhex('8d8550fdffff83fe030f94c10fb6c9034b0883fe030f94c20fb6d2035304')
    assert pe.get_data(0x9c2b98 - 0x400000, len(geometry)) == geometry
    assert pe.get_data(0x9c2e3e - 0x400000, len(geometry)) == geometry
    for va in (0x9c2bb6, 0x9c2e5c):
        call = pe.get_data(va - 0x400000, 5)
        assert call[0] == 0xe8 and va + 5 + struct.unpack('<i', call[1:])[0] == 0x4f27fc
    reg = json.loads(registration.read_text(encoding='utf-8'))
    assert sha(atlas.read_bytes()) == reg['sha256']
    picture = Image.open(atlas).convert('RGBA')
    assert picture.size == (1104, 1104)
    tiles = []
    for frame in range(36):
        x, y = frame % 6, frame // 6
        tile = picture.crop((x * 184, y * 184, (x + 1) * 184, (y + 1) * 184))
        bounds = tile.getchannel('A').getbbox()
        if frame >= 15:
            assert bounds is None
            continue
        assert min(bounds[:2]) >= 12 and max(bounds[2:]) <= 172
        core = tile.getchannel('A').point(lambda v: 255 if v >= 16 else 0).getbbox()
        center = ((core[0] + core[2]) / 2, (core[1] + core[3]) / 2)
        assert max(abs(v - 92) for v in center) <= .5
        tiles.append(center)
    asset_data = json.loads(assets.read_text(encoding='utf-8'))
    cases = []
    for base, ti_base in ((0x10000000, 0x400000), (0x17000000, 0x600000)):
        draw = ActualRenderFixture(raw, ti.read_bytes(), base, ti_base, asset_data)
        scaler = ScaleFixture(raw, base)
        plate = draw.load_resource(hd.ITEM_COUNT)
        glyph = draw.load_resource(hd.ITEM_COUNT + 1)
        for percent in scale.PERCENTS:
            for frame in range(15):
                for state, tint in enumerate((0xffffffff, 0x80553412, 0x90dbefb1, 0xff778899)):
                    pressed = int(state == 3)
                    x, y = 1703 + pressed, 997 + pressed
                    draw.run(0x4f27fc, plate, x, y, args=(0, state, tint))
                    plate_quad = draw.quads[-1]['vertices']
                    draw.run(0x4f27fc, glyph, x, y, args=(0, frame, tint))
                    glyph_quad = draw.quads[-1]['vertices']
                    assert all(p[:5] == g[:5] for p, g in zip(plate_quad, glyph_quad))
                    assert plate_quad[0][:2] == [x, y] and plate_quad[2][:2] == [x + 46, y + 46]
                    assert all(v[4] == tint for v in glyph_quad)
                    scaled_plate = upload(scaler, plate_quad, percent)
                    scaled_glyph = upload(scaler, glyph_quad, percent)
                    assert all(p[:5] == g[:5] for p, g in zip(scaled_plate, scaled_glyph))
                    # Complete source frame order/row stride remain native;
                    # repacking cannot change the bound frame or button box.
                    texture = draw.quads[-1]['texture']
                    tw, th = get(draw.u, texture + 0x14), get(draw.u, texture + 0x18)
                    sx, sy = (frame % 6) * 184, (frame // 6) * 184
                    for vertex, uv in zip(glyph_quad, ((sx / tw, sy / th), ((sx + 184) / tw, sy / th),
                                                      ((sx + 184) / tw, (sy + 184) / th), (sx / tw, (sy + 184) / th))):
                        close(vertex[5], uv[0]); close(vertex[6], uv[1])
                    factor = percent / 100
                    physical_box_center = ((x + 23) * factor, (y + 23) * factor)
                    physical_art_center = ((x + tiles[frame][0] / 4) * factor, (y + tiles[frame][1] / 4) * factor)
                    error = max(abs(a - b) for a, b in zip(physical_box_center, physical_art_center))
                    assert error <= .25
                    cases.append({'frame': frame, 'plate_state': state, 'tint': hex(tint), 'percent': percent,
                                  'silver_base': hex(base), 'ti_base': hex(ti_base), 'physical_center_error': error,
                                  'native_plate_glyph_geometry_identical': True})
    assert silver.read_bytes() == raw, 'Native baseline was modified'
    result = {'PASS': True, 'cases': len(cases), 'details': cases, 'native_sha256': expected_sha,
              'native_file_unchanged': True, 'asset_only': True, 'atlas_sha256': reg['sha256'],
              'native_hud_origin_calls': ['0x9c2bb6', '0x9c2e5c'],
              'native_pipeline': ['Silver4f27fc', 'TI740610', 'TI611958', 'TI661b18', 'TI651c30',
                                  'TI6619dc', 'TI749a3c', 'Silverc25a00'],
              'all_15_frames_4_states_4_scales_2_image_bases': True,
              'colors_depth_and_uv_preserved_by_scaling': True,
              'cpu_vertex_data_and_callee_registers_preserved': True,
              'physical_center_error_max': max(case['physical_center_error'] for case in cases),
              'all_21_unused_cells_transparent': True, 'actual_graphical_client': False}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return {key: result[key] for key in ('PASS', 'cases', 'native_sha256', 'atlas_sha256', 'physical_center_error_max')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--silver', type=Path, required=True)
    p.add_argument('--ti', type=Path, required=True)
    p.add_argument('--expected-sha', required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--atlas', type=Path, required=True)
    p.add_argument('--registration', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(verify(args.silver, args.ti, args.expected_sha, args.assets, args.atlas, args.registration, args.output)))
