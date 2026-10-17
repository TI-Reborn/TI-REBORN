"""Execute the item loaders and real native HD quad/UV pipeline in Unicorn.

Only Unicode allocations, resource cache objects and final GPU calls are
fixtures. Genuine Silver loader/adapter and TI source/destination UV math run.
This is automated ABI/geometry evidence, not a graphical game-client claim.
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
from deploy import client_battle_ui_hd as a
from tools.verify_ui_hd_icons_native import NativeLoaderFixture, put, get, close, DATA


class Fixture(NativeLoaderFixture):
    def __init__(self, image, ti, base, ti_base, assets):
        super().__init__(image, ti, base, ti_base)
        self.has_hd = pefile.PE(data=image).OPTIONAL_HEADER.SizeOfImage == a.BASE_RVA + a.SIZE
        put(self.u, self.va(0xacc4b0), self.tva(0x71c73c))
        self.scaled_stock = []
        self.one_loads = []
        self.fail_sources = set()
        self.asset_rows = {row['native_path']: row for row in assets['assets']}
        for resource in a.RESOURCES:
            w, h = resource['logical_size']
            self.asset_dimensions['base\\' + resource['native_path']] = (w, h)
            row = self.asset_rows['base/' + resource['native_path'].replace('\\', '/')]
            self.asset_dimensions['base\\' + resource['hd_path']] = tuple(row['dimensions'])
        self.asset_dimensions['base\\pda\\bui_controls_btn.png'] = (256, 128)
        self.asset_dimensions['base\\pda\\bui_controls_btn2.png'] = (276, 276)

    def texture(self, width, height):
        texture = super().texture(width, height)
        # Actual native material-name lookup accepts a null/empty fixture name.
        put(self.u, texture + 4, 0)
        return texture

    def hook(self, u, address, size, user):
        if address == self.va(a.LOAD_ONE_NATIVE):
            self.one_loads.append(self.text(u.reg_read(UC_X86_REG_EAX)))
        if address == self.tva(0x71bd8c):
            sp = u.reg_read(UC_X86_REG_ESP)
            self.scaled_stock.append([get(u, sp + 4 * i) for i in range(1, 11)])
            u.reg_write(UC_X86_REG_EAX, 0x9abcdef0); self.ret(40); return
        if address == self.tva(0x6b11f4):
            source = self.text(u.reg_read(UC_X86_REG_EAX))
            if source in self.fail_sources:
                u.reg_write(UC_X86_REG_EAX, 0); self.ret(); return
        super().hook(u, address, size, user)

    def load_resource(self, index, path_override=None):
        resource = a.RESOURCES[index]
        path = self.unicode(path_override or resource['native_path'])
        out = DATA + 0xa000 + index * 0x20
        if resource['kind'] == 'item':
            self.run(0x4f2c50, path, 2, out)
        else:
            self.run((a.LOAD_TWO + (index - a.ITEM_COUNT) * 0x100) if self.has_hd else 0x4f2cb4,
                     path, 46, 46, args=(out, 2, 0, 0))
        return out


class ActualRenderFixture(Fixture):
    """Also execute the original Image_Render APIs for before/after comparison."""
    def hook(self, u, address, size, user):
        if address in (self.tva(0x71bd8c), self.tva(0x71bbe0)):
            return
        super().hook(u, address, size, user)


def verify(source, ti, manifest, output, candidate_path):
    assets = json.loads(manifest.read_text(encoding='utf-8'))
    assert len(assets['assets']) == len(a.RESOURCES)
    for item in assets['assets']:
        raw = Path(item['path']).read_bytes()
        assert a.sha(raw) == item['sha256'] and len(raw) == item['size']
        im = Image.open(Path(item['path']))
        assert im.mode == 'RGBA' and list(im.size) == item['dimensions']
        assert item['client_relative_path'].startswith(('base/ui-hd/battle-items/', 'base/ui-hd/battle-controls/'))
    candidate = a.patch(source, expected_sha=a.sha(source))
    candidate_path.write_bytes(candidate)
    try: a.patch(source, expected_sha='0' * 64)
    except ValueError: pass
    else: raise AssertionError('Source SHA guard failed')
    before, after = pefile.PE(data=source), pefile.PE(data=candidate)
    assert before.FILE_HEADER.NumberOfSections == after.FILE_HEADER.NumberOfSections == 13
    assert after.OPTIONAL_HEADER.SizeOfImage == a.BASE_RVA + a.SIZE
    assert after.sections[-1].Misc_VirtualSize == before.sections[-1].Misc_VirtualSize + a.SIZE
    assert after.sections[-1].SizeOfRawData == before.sections[-1].SizeOfRawData + a.SIZE
    assert after.get_data(a.BASE_RVA, a.SIZE) == a.extension()
    cases = []
    for base, ti_base in ((0x10000000, 0x400000), (0x17000000, 0x600000)):
        f = Fixture(candidate, ti, base, ti_base, assets)
        put(f.u, f.va(0xacc424), f.tva(0x71bd8c))
        outputs = []
        for index, resource in enumerate(a.RESOURCES):
            out = f.load_resource(index); outputs.append(out)
            row = base + a.ROWS + index * a.ROW_SIZE
            assert get(f.u, row) == get(f.u, out) != 0
            hd = get(f.u, row + 0x14)
            assert hd != 0 and hd != get(f.u, out)
            original_record = bytes(f.u.mem_read(out, 12))
            start = len(f.loads); f.load_resource(index)
            assert len(f.loads) == start + (0 if resource['kind'] == 'item' else 1)
            assert bytes(f.u.mem_read(out, 12)) == original_record
            w, h = resource['logical_size']; sw, sh = w * 4, h * 4
            aw, ah = get(f.u, hd + 0x14), get(f.u, hd + 0x18)
            for frame in range(resource['frames']):
                for scaled in (False, True):
                    dw, dh = (max(1, w // 2), max(1, h // 2)) if scaled else (w, h)
                    args = (0x102, 0x90dbefb1, frame, dh, dw) if scaled else (0, frame, 0x90dbefb1)
                    n = len(f.quads)
                    assert f.run(0x4f2910 if scaled else 0x4f27fc, out, 41, 52, args=args) == 1
                    assert len(f.quads) == n + 1 and f.quads[-1]['texture'] == hd
                    sx, sy = (frame % resource['columns']) * sw, (frame // resource['columns']) * sh
                    expected = [(41, 52, sx / aw, sy / ah), (41 + dw, 52, (sx + sw) / aw, sy / ah),
                                (41 + dw, 52 + dh, (sx + sw) / aw, (sy + sh) / ah),
                                (41, 52 + dh, sx / aw, (sy + sh) / ah)]
                    for vertex, (x, y, uvx, uvy) in zip(f.quads[-1]['vertices'], expected):
                        close(vertex[0], x); close(vertex[1], y); close(vertex[5], uvx); close(vertex[6], uvy)
                        assert vertex[4] == 0x90dbefb1, hex(vertex[4])
                    assert bytes(f.u.mem_read(out, 12)) == original_record
                    assert f.u.mem_read(f.renderer + 0x2d5, 1) == b'\x07'
                    cases.append({'case': 'real_native_quad_uv_tint', 'resource': resource['id'],
                                  'scaled': scaled, 'frame': frame, 'silver_base': hex(base), 'ti_base': hex(ti_base)})
        # Native custom destination sizes and every tint component survive.
        out = outputs[0]
        f.run(0x4f2910, out, 13, 29, args=(0, 0x80553412, 0, 37, 83))
        quad = f.quads[-1]['vertices']
        assert quad[0][:2] == [13, 29] and quad[2][:2] == [96, 66]
        assert all(v[4] == 0x80553412 for v in quad)
        # Unknown handles, mismatched dimensions, unsupported frames/effects,
        # missing HD assets and unregistered native-host pointers stay stock.
        unknown = f.image(40, 40)
        wrong = f.image(39, a.RESOURCES[0]['logical_size'][1]); put(f.u, wrong, get(f.u, out))
        for label, image, flags, frame in [('unknown', unknown, 0, 0), ('wrong_tile', wrong, 0, 0),
                                           ('negative_frame', out, 0, 0xffffffff), ('invalid_frame', out, 0, 1),
                                           ('default_effect', out, 1, 0)]:
            start = len(f.stock)
            assert f.run(0x4f27fc, image, 41, 52, args=(flags, frame, 0x12345678)) == 0x9abcdef0
            assert len(f.stock) == start + 1
            cases.append({'case': 'stock_fallback_' + label, 'silver_base': hex(base)})
        for image, frame in ((unknown, 0), (wrong, 0), (out, 1), (out, 0xffffffff)):
            start = len(f.scaled_stock)
            assert f.run(0x4f2910, image, 41, 52, args=(0x102, 0x12345678, frame, 37, 83)) == 0x9abcdef0
            assert len(f.scaled_stock) == start + 1
            packed = list(struct.unpack('<III', f.u.mem_read(image, 12)))
            assert f.scaled_stock[-1] == packed + [41, 52, 83, 37, frame, 0x12345678, 0x102]
        start = len(f.scaled_stock)
        f.run(0x4f2910, out, 41, 52, args=(7, 0x12345678, 0, 37, 83))
        assert len(f.scaled_stock) == start + 1
        row = base + a.ROWS; saved = get(f.u, row + 0x14); put(f.u, row + 0x14, 0)
        start = len(f.stock); f.run(0x4f27fc, out, 41, 52, args=(0, 0, 0xffffffff)); assert len(f.stock) == start + 1
        put(f.u, row + 0x14, saved)
        ptr = f.va(0xacc3fc); saved = get(f.u, ptr); put(f.u, ptr, 0)
        # The old adapter passes unknown item handles to stock; restore its
        # callback before executing so the fallback fixture remains valid.
        f.run(0x4f2910, out, 41, 52, args=(0x102, 0xffffffff, 0, 37, 83))
        put(f.u, ptr, saved)
        assert get(f.u, base + a.STATE + 4) == len(a.RESOURCES)
        assert get(f.u, base + a.STATE + 8) == 0
        assert '0x7492cc' in f.loader_executed
        assert f.executed == {'0x740610', '0x611958', '0x661b18', '0x651c30', '0x6619dc', '0x749a3c'}
        # Missing originals never trigger an HD request. A missing HD file
        # retains stock and never causes texture allocation during drawing.
        absent = Fixture(candidate, ti, base, ti_base, assets)
        absent.fail_sources.add('base\\' + a.RESOURCES[0]['native_path'])
        missing_out = absent.load_resource(0)
        assert get(absent.u, missing_out) == 0 and get(absent.u, base + a.STATE) == 0
        failed = Fixture(candidate, ti, base, ti_base, assets)
        failed.fail_sources.add('base\\' + a.RESOURCES[0]['hd_path'])
        missing_hd_out = failed.load_resource(0)
        assert get(failed.u, base + a.ROWS + 0x14) == 0
        assert get(failed.u, base + a.STATE + 8) == 1
        loads = len(failed.loads)
        for _ in range(3):
            failed.run(0x4f27fc, missing_hd_out, 41, 52, args=(0, 0, 0xffffffff))
        assert len(failed.loads) == loads and len(failed.stock) == 3
        cases.extend([{'case': 'missing_original_no_hd_request', 'silver_base': hex(base)},
                      {'case': 'missing_hd_stock_no_draw_load', 'silver_base': hex(base)}])
        # Caller ownership survives native add-ref/release; case-insensitive
        # registration is independent of the resource manager's filename key.
        mixed = Fixture(candidate, ti, base, ti_base, assets)
        alternate = a.RESOURCES[0]['native_path'].upper()
        mixed.asset_dimensions['base\\' + alternate] = tuple(a.RESOURCES[0]['logical_size'])
        mixed_out = mixed.load_resource(0, alternate)
        assert get(mixed.u, base + a.ROWS) == get(mixed.u, mixed_out)
        assert get(mixed.u, base + a.ROWS + 0x14) != 0
        path = mixed.unicode(a.RESOURCES[1]['native_path'])
        put(mixed.u, path - 8, 1)
        original_path = bytes(mixed.u.mem_read(path, len(a.RESOURCES[1]['native_path']) * 2 + 2))
        heap_out = DATA + 0xf000
        mixed.run(0x4f2c50, path, 2, heap_out)
        assert get(mixed.u, path - 8) == 1
        assert bytes(mixed.u.mem_read(path, len(original_path))) == original_path
        assert get(mixed.u, base + a.ROWS + a.ROW_SIZE) == get(mixed.u, heap_out)
        # Existing PDA density loaders and render routing still execute.
        legacy = Fixture(candidate, ti, base, ti_base, assets)
        legacy_out = NativeLoaderFixture.load(legacy, 0)
        put(legacy.u, base + 0x828f00, 150)
        legacy.run(0x4f27fc, legacy_out, 41, 52, args=(0, 3, 0xffffffff))
        assert len(legacy.quads) == 1 and len(legacy.stock) == 0
        assert get(legacy.u, base + 0x848f00 + 0x10) == 150
        cases.extend([{'case': 'casefold_native_owned_path_registration', 'silver_base': hex(base)},
                      {'case': 'heap_path_refcount_and_bytes_preserved', 'silver_base': hex(base)},
                      {'case': 'existing_pda_hd_route_preserved', 'silver_base': hex(base)}])
        # Triangulate against genuine original API implementations and their
        # real native GPU vertex assembly, rather than a substituted API stub.
        # This catches API argument ordering and the bridge's colour conversion.
        old = ActualRenderFixture(source, ti, base, ti_base, assets)
        new = ActualRenderFixture(candidate, ti, base, ti_base, assets)
        for fixture in (old, new):
            put(fixture.u, fixture.va(0xacc424), fixture.tva(0x71bd8c))
        for index in (0, next(i for i,r in enumerate(a.RESOURCES) if r['id'] == 'icon-itm_gasdrill'),
                      a.ITEM_COUNT, a.ITEM_COUNT + 1):
            old_out = old.load_resource(index); new_out = new.load_resource(index)
            resource = a.RESOURCES[index]
            w, h = resource['logical_size']
            for frame in range(resource['frames']):
                for color in (0xffffffff, 0x80553412, 0x90dbefb1, 0xff778899):
                    for scaled in (False, True):
                        args = (0x102, color, frame, max(1,h//2), max(1,w//2)) if scaled else (0,frame,color)
                        for fixture, native_out in ((old,old_out),(new,new_out)):
                            fixture.run(0x4f2910 if scaled else 0x4f27fc, native_out, 13,29,args=args)
                        before_quad, after_quad = old.quads[-1]['vertices'], new.quads[-1]['vertices']
                        assert len(before_quad) == len(after_quad) == 4
                        for before_vertex, after_vertex in zip(before_quad,after_quad):
                            assert before_vertex[:5] == after_vertex[:5], (resource['id'],scaled,frame,color,before_vertex,after_vertex)
                        cases.append({'case':'actual_original_api_geometry_and_tint_match', 'resource':resource['id'],
                                      'scaled':scaled,'frame':frame,'tint':hex(color),'silver_base':hex(base)})
    hooks = [(0x4f27fc, 6), (0x4f2910, 6), (0x4f2c50, 6), (0xa6b834, 5), (0xa6b852, 5)]
    spans = [{'offset': before.get_offset_from_rva(va - a.IMAGE_BASE), 'size': size,
              'virtual_address': hex(va), 'purpose': 'item/battle icon hook'} for va, size in hooks]
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        spans.append({'offset': before.sections[-1].get_field_absolute_offset(field), 'size': 4, 'purpose': 'extend final section ' + field})
    for field in ('SizeOfImage', 'CheckSum'):
        spans.append({'offset': before.OPTIONAL_HEADER.get_field_absolute_offset(field), 'size': 4, 'purpose': field})
    approved = {i for span in spans for i in range(span['offset'], span['offset'] + span['size'])}
    assert all(i in approved for i, (x, y) in enumerate(zip(source, candidate)) if x != y)
    result = {**a.metadata(), 'PASS': True, 'candidate_path': str(candidate_path.resolve()),
              'source_sha256': a.sha(source), 'candidate_sha256': a.sha(candidate),
              'candidate_bytes': len(candidate), 'native_edit_spans': spans,
              'append_offset': len(source), 'append_size': a.SIZE, 'cases': cases,
              'native_tests': len(cases), 'assets_manifest': str(manifest.resolve()),
              'asset_count': len(assets['assets']), 'native_abi_preserved': True,
              'tint_and_custom_destination_preserved': True, 'actual_graphical_client': False,
              'loader_pipeline': ['Silver4f2c50', 'Silver4f2cb4', 'TI71c73c', 'TI71c844', 'TI74046c', 'TI7404fc', 'TI7492cc'],
              'render_pipeline': sorted(f.executed)}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'PASS': True, 'cases': len(cases), 'candidate_sha256': a.sha(candidate),
                      'candidate': str(candidate_path.resolve()), 'proof': str(output.resolve())}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--ti', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    args = p.parse_args()
    verify(args.source.read_bytes(), args.ti.read_bytes(), args.assets, args.output, args.candidate)
