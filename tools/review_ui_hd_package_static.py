"""Independent static review of the exact selected HD package and native hooks.

Reads the reviewed package, actual PE tables and PNG pixels. No patch builder,
game, GUI, GPU, network, hosting write or publication function is called.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import struct
import sys

import pefile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import publish_ui_hd_assets_remote as pub
from tools import review_ui_hd_font_filename_abi as filename_review
from deploy import client_ui_hd_fonts as fonts
from deploy import client_ui_hd_icons as icons


def require(value, message):
    if not value:
        raise ValueError(message)


def word(pe, rva):
    return struct.unpack('<I', pe.get_data(rva, 4))[0]


def text(pe, rva):
    raw = bytearray()
    for index in range(256):
        value = pe.get_data(rva + index * 2, 2)
        if value == b'\0\0':
            return raw.decode('utf-16le')
        require(len(value) == 2, 'Embedded string exceeds mapped file')
        raw.extend(value)
    raise ValueError('Embedded resource string exceeds its bounded region')


def branch(data, pe, va, opcode):
    raw = data[pe.get_offset_from_rva(va - 0x400000):][:5]
    require(raw[0] == opcode, 'Unexpected hook opcode')
    return va + 5 + struct.unpack_from('<i', raw, 1)[0]


def review(package_path, expected):
    package, payloads = pub.load_package(package_path, expected_sha=expected)
    data = payloads['silver.dll']
    source = (pub.DEPLOYMENT / 'baseline/silver.dll').read_bytes()
    require(pub.sha(source) == pub.SILVER_SHA, 'Trusted native source differs')
    old, new = pefile.PE(data=source), pefile.PE(data=data)
    hooks = [(fonts.HOOK, fonts.HOOK_BEFORE, fonts.STARTUP, 0xe9),
             (0x4f27fc, bytes.fromhex('558bec83c4f4'), icons.DRAW, 0xe9)]
    for index, (_, _, _, _, site) in enumerate(icons.RESOURCES):
        before = b'\xe8' + struct.pack('<i', 0x4f2cb4 - site - 5)
        hooks.append((site, before, icons.LOAD_WRAPPERS + index * 0x80, 0xe8))
    allowed, hook_results = set(), []
    relocations = [entry.rva for block in new.DIRECTORY_ENTRY_BASERELOC
                   for entry in block.entries if entry.type == 3]
    for va, before, target, opcode in hooks:
        rva = va - 0x400000
        offset = old.get_offset_from_rva(rva)
        require(source[offset:offset + len(before)] == before, 'Pinned native hook input differs')
        require(branch(data, new, va, opcode) == target, 'Hook does not reach its exact owned entry')
        if len(before) == 6:
            require(new.get_data(rva + 5, 1) == b'\x90', 'Six-byte prologue hook has no NOP tail')
        require(not any(rva <= value < rva + len(before) for value in relocations),
                'Hook overlaps a native relocation')
        allowed.update(range(offset, offset + len(before)))
        hook_results.append(dict(va=hex(va), target=hex(target), bytes=len(before),
                                 original=before.hex(), relocation_overlap=False))
    fields = [old.sections[-1].get_field_absolute_offset(key)
              for key in ('Misc_VirtualSize', 'SizeOfRawData')]
    fields += [old.OPTIONAL_HEADER.get_field_absolute_offset(key)
               for key in ('SizeOfImage', 'CheckSum')]
    for offset in fields:
        allowed.update(range(offset, offset + 4))
    changed = [i for i, (before, after) in enumerate(zip(source, data)) if before != after]
    require(set(changed) <= allowed, 'Unreviewed original native byte was changed')
    require(old.get_data(0x823000, 0xb000) == new.get_data(0x823000, 0xb000),
            'Published .11/.12 runtime payload changed')
    for va, size in pub.AUTH_SPANS:
        require(old.get_data(va - 0x400000, size) == new.get_data(va - 0x400000, size),
                'Original authentication span changed')
    require(len(old.sections) == len(new.sections) == 13, 'Unexpected PE section count')
    require(new.OPTIONAL_HEADER.SizeOfImage == icons.SECTION_RVA + icons.SIZE,
            'Combined PE image end differs')
    require(not any(value >= fonts.RVA for value in relocations), 'Appended PIC has relocations')
    for section in new.sections:
        require(section.PointerToRawData + section.SizeOfRawData <= len(data),
                'PE raw section exceeds actual candidate')
    last = new.sections[-1]
    require(last.VirtualAddress + last.Misc_VirtualSize == new.OPTIONAL_HEADER.SizeOfImage
            and last.PointerToRawData + last.SizeOfRawData == len(data),
            'Appended native PE section is not a complete file/image tail')

    decoded = {}
    for item in package['files']:
        if item['kind'] not in ('font_atlas', 'icon_image'):
            continue
        with Image.open(io.BytesIO(payloads[item['path']])) as image:
            image.load()
            require(image.format == 'PNG' and image.mode == 'RGBA', 'Selected atlas is not decoded RGBA')
            require(image.getchannel('A').getbbox() is not None, 'Selected atlas has no visible ink')
            decoded[item['path']] = dict(width=image.width, height=image.height, mode=image.mode)

    manifest = fonts.assets_manifest()
    referenced = {'silver.dll'}
    font_rows = []
    for index, role in enumerate(manifest['fonts']):
        row = fonts.TABLE + index * 0x80
        count, glyph_rva = word(new, row + 8), word(new, row + 12)
        require(count == len(role['glyphs']) and 0 < count <= 256, 'Native glyph count differs')
        for density, atlas in enumerate(role['density_sets']):
            header = word(new, row + 0x38 + density * 4)
            path = text(new, header + 12).replace('\\', '/')
            require(path == atlas['path'], 'Embedded font path differs from selected atlas')
            require(word(new, header + 8) == len(path), 'Font filename is not a Unicode character count')
            packed = word(new, row + 0x28 + density * 4)
            geometry = decoded[path]
            require((packed & 0xffff, packed >> 16) == (geometry['width'], geometry['height']),
                    'Actual font PNG dimensions differ from native table')
            referenced.add(path)
        for number, glyph in enumerate(role['glyphs']):
            cp, dx, dy, width, height = struct.unpack('<IhhHH', new.get_data(glyph_rva + number * 0x2c, 12))
            require((cp, dx, dy, width, height) == (glyph['codepoint'], *glyph['visual_logical_box']),
                    'Native glyph ink/role table differs from approved raster contract')
            for density, atlas in enumerate(role['density_sets']):
                rect = struct.unpack('<4H', new.get_data(glyph_rva + number * 0x2c + 12 + density * 8, 8))
                require(tuple(glyph['source_rects'][density]) == rect, 'Native glyph source rect differs')
                require(rect[0] + rect[2] <= atlas['width'] and rect[1] + rect[3] <= atlas['height'],
                        'Glyph source crop exceeds actual atlas')
        font_rows.append(dict(role=role['font'], glyphs=count, densities=4))

    icon_rows = []
    for index, (_, symbol, width, height, _) in enumerate(icons.RESOURCES):
        row = icons.ROWS + index * 0x80
        require((word(new, row + 4), word(new, row + 8)) == (width, height),
                'Native icon logical control dimensions changed')
        for density_index, density in enumerate(icons.DENSITIES):
            pointer = word(new, row + 0x50 + density_index * 4)
            path = text(new, pointer)
            require(word(new, pointer - 4) == len(path), 'Icon filename count differs from Silver Unicode ABI')
            path = 'base/' + path.replace('\\', '/')
            require(path == 'base/' + icons.path_for(symbol, density).replace('\\', '/'),
                    'Embedded icon resource name differs')
            physical_width = word(new, row + 0x60 + density_index * 4)
            physical_height = word(new, row + 0x70 + density_index * 4)
            geometry = decoded[path]
            require((physical_width, physical_height) ==
                    ((width * density + 50) // 100, (height * density + 50) // 100),
                    'Native icon density dimensions differ')
            require((geometry['width'], geometry['height']) == (physical_width * 2, physical_height * 2),
                    'Native four-state icon tiles do not match the actual 2x2 PNG')
            referenced.add(path)
        icon_rows.append(dict(symbol=symbol, logical_size=[width, height], densities=4))
    licenses = {item['path'] for item in package['files'] if item['kind'] == 'license'}
    require(len(licenses) == 1 and referenced | licenses == set(payloads),
            'Package carries an unreferenced/missing selected file')
    native_filenames = [Path(path).name.casefold() for path in referenced if path.endswith('.png')]
    require(len(native_filenames) == len(set(native_filenames)) == 96,
            'Selected basename-only native texture cache would alias densities/roles')
    original_manifest = pub.BASELINE.read_bytes()
    payload = pub.make_payload(package_path, expected, 'inspect')
    transition = pub.manifest_transition(original_manifest,
        __import__('base64').b64decode(payload['after_manifest']), package)
    scanner = filename_review.review(Path(package_path).parent / 'silver.dll', pub.sha(data))
    require(scanner['result'] == 'PASS', 'Actual native font basename scanner rejects candidate literals')
    return dict(result='PASS_FOR_STATIC_PACKAGE_REVIEW', package_sha256=expected,
                candidate_sha256=pub.sha(data), candidate_bytes=len(data),
                package_files=len(payloads), package_bytes=sum(map(len, payloads.values())),
                decoded_rgba_pngs=len(decoded), native_hooks=hook_results,
                changed_existing_bytes=len(changed), appended_bytes=len(data) - len(source),
                prior_runtime_bytes_preserved=0xb000, auth_functions_preserved=len(pub.AUTH_SPANS),
                font_rows=font_rows, icon_rows=icon_rows, unique_native_png_basenames=96,
                native_font_filename_scanner_checks=scanner['checks'],
                manifest_transition=transition,
                original_native_png_xml_paths_changed=False, ti_changed=False,
                graphical_validation=False, remote_mutations=0, publish_allowed=False,
                limits=['Static geometry and native filename scanning do not prove actual PNG decode/GPU draw or hosted graphical behavior.'],
                reviewer_sha256=pub.sha(Path(__file__).read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--package-sha256', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    target = args.report.absolute()
    require(target.is_relative_to(pub.DEPLOYMENT) and not target.exists()
            and pub.no_symlinks(target) and target.resolve() == target,
            'Use a new non-linked independent deployment evidence path')
    result = review(args.package, args.package_sha256)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write('\n')
    print(json.dumps({key: result[key] for key in ('result', 'candidate_sha256', 'package_sha256',
                                                  'package_files', 'decoded_rgba_pngs')}))


if __name__ == '__main__':
    main()
