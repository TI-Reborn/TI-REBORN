"""Pure, SHA-guarded modern resolution presets for the published TI Screen panel.

This transformer does not launch a client, publish files, or apply video modes.
It keeps the native radio controls, grouping, caption parser and Apply callback.
The added code is PIC: existing relocation records and all previous patches stay
intact. The separate .tiosui section leaves one final PE header slot available.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile

BASE_SHA = 'bd0ce7a29d4cfdb4689330da8086052c287146fe7a383ed50710493a7ba0b0ac'
IMAGE_BASE = 0x400000
SECTION_NAME = b'.tiosui'
SECTION_RVA = 0x822000
SECTION_SIZE = 0x1000
CREATE_RVA = SECTION_RVA
ENABLE_RVA = SECTION_RVA + 0xa00
LOOKUP_RVA = SECTION_RVA + 0xc00
TABLE_RVA = SECTION_RVA + 0xd00
STRINGS_RVA = SECTION_RVA + 0xd80
SIGNATURE_RVA = SECTION_RVA + 0xf80
SIGNATURE = b'TIO-screen-resolution-ui-v1'
RESOLUTIONS = (
    (800, 600), (1024, 768), (1280, 720), (1280, 800), (1366, 768),
    (1600, 900), (1920, 1080), (2560, 1440), (3440, 1440), (3840, 2160),
)
HOOKS = (
    (0x886f28, bytes.fromhex('5633c9b201'), CREATE_RVA),
    (0x884928, bytes.fromhex('8b45fc83e802'), LOOKUP_RVA),
)
ENABLE_VA = 0x884912
ENABLE_BEFORE = bytes.fromhex('837dfc00740a837df000740433d2eb02b201')
# The LCD Fullscreen and Desktop paths use native desktop client dimensions.
# Presets select the render dimensions in windowed mode or CRT fullscreen only.
ENABLE_AFTER = b'\xe9' + struct.pack('<i', IMAGE_BASE+ENABLE_RVA-ENABLE_VA-5) + b'\x90' * 13
SCREEN_BOUNDS_VA = 0x8867b8
SCREEN_BOUNDS_BEFORE = bytes.fromhex('68800100006840010000')
SCREEN_BOUNDS_AFTER = bytes.fromhex('68800100006880010000')
BUTTON_ROW_VAS = (0x88687f, 0x8868fe)
BUTTON_ROW_CODE = bytes.fromhex('8b463c83e830894334')


class Assembler:
    def __init__(self, rva: int):
        self.rva = rva
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []

    def emit(self, value: str):
        self.data.extend(bytes.fromhex(value))

    def word(self, value: int):
        self.data.extend(struct.pack('<I', value & 0xffffffff))

    def relative(self, opcode: str, preferred_va: int):
        self.emit(opcode)
        self.word(preferred_va - IMAGE_BASE - self.rva - len(self.data) - 4)

    def branch(self, opcode: str, label: str):
        self.emit(opcode)
        self.fixups.append((len(self.data), label))
        self.word(0)

    def label(self, name: str):
        self.labels[name] = len(self.data)

    def base_edi(self):
        # CALL's pushed address relocates naturally. Subtract only its RVA.
        self.emit('e8 00000000 5f 81ef')
        self.word(self.rva + len(self.data) - 3)

    def finish(self) -> bytes:
        for at, label in self.fixups:
            struct.pack_into('<i', self.data, at, self.labels[label] - at - 4)
        return bytes(self.data)


def section_payload() -> tuple[bytes, dict]:
    payload = bytearray(SECTION_SIZE)
    captions = [f'{width}x{height}' for width, height in RESOLUTIONS] + ['Current']
    caption_rvas = []
    at = STRINGS_RVA - SECTION_RVA
    for caption in captions:
        encoded = caption.encode('utf-16le')
        # The native caption setter receives a BSTR (byte length at pointer-4).
        constant = struct.pack('<I', len(encoded)) + encoded + b'\0\0'
        caption_rvas.append(SECTION_RVA + at + 4)
        payload[at:at+len(constant)] = constant
        at = (at + len(constant) + 3) & ~3
    if SECTION_RVA + at > SIGNATURE_RVA:
        raise ValueError('Caption constants exceed reserved section bounds')
    for index, (width, height) in enumerate(RESOLUTIONS):
        struct.pack_into('<II', payload, TABLE_RVA - SECTION_RVA + index * 8, width, height)

    create = Assembler(CREATE_RVA)
    create.emit('9c60 89e5 83ec0c')
    create.base_edi()
    # Save the current cvars once, before constructing controls. ESI remains the
    # native parent; [EBP] is the original EDI/Y from PUSHAD's saved frame.
    create.emit('8d87'); create.word(0x8839dc - IMAGE_BASE)
    create.relative('e8', 0x688328); create.emit('8945fc')
    create.emit('8d87'); create.word(0x8839ec - IMAGE_BASE)
    create.relative('e8', 0x688328); create.emit('8945f8 c745f400000000')

    def radio(index: int, width: int | None, height: int | None):
        create.emit('56 31c9 b201 8b87'); create.word(0xa309f4 - IMAGE_BASE)
        create.relative('e8', 0xa44c9c)
        create.emit('89c3 c78378020000'); create.word(index)
        create.emit('c7838402000003000000 c74330'); create.word(128 + 96 * (index % 2))
        create.emit('8b4500 05'); create.word(16 * (index // 2))
        create.emit('894334 c743385c000000')
        create.emit('8d97'); create.word(caption_rvas[index])
        create.emit('89d8'); create.relative('e8', 0xa42b04)
        if width is None:
            create.emit('b201')
        else:
            create.emit('31d2 817dfc'); create.word(width)
            create.branch('0f85', f'unselected_{index}')
            create.emit('817df8'); create.word(height)
            create.branch('0f85', f'unselected_{index}')
            create.emit('b201 c745f401000000')
            create.label(f'unselected_{index}')
        create.emit('89d8'); create.relative('e8', 0xa44eac)

    for index, (width, height) in enumerate(RESOLUTIONS):
        radio(index, width, height)
    # Keep an arbitrary previously saved resolution usable. Construct this last
    # radio only when none of the preset dimensions matches the current cvars.
    create.emit('837df400'); create.branch('0f85', 'no_custom')
    radio(len(RESOLUTIONS), None, None)
    create.label('no_custom')
    create.relative('e8', 0x884688)
    create.emit('89ec 619d')
    create.relative('e9', 0x886f98)
    create_bytes = create.finish()
    if len(create_bytes) > ENABLE_RVA - CREATE_RVA:
        raise ValueError('Constructor exceeds reserved section bounds')
    payload[:len(create_bytes)] = create_bytes

    enable = Assembler(ENABLE_RVA)
    # Original caption-helper locals: EBP-4 is selected screen type (category
    # one), EBP-0x10 is selected window/fullscreen/desktop mode (category two).
    # EAX is the radio object; leave it untouched for its native enable method.
    enable.emit('837df000'); enable.branch('0f84', 'enabled')
    enable.emit('837df001'); enable.branch('0f85', 'disabled')
    enable.emit('837dfc00'); enable.branch('0f85', 'disabled')
    enable.label('enabled'); enable.emit('b201'); enable.branch('e9', 'done')
    enable.label('disabled'); enable.emit('31d2')
    enable.label('done'); enable.relative('e9', 0x884924)
    enable_bytes = enable.finish()
    if len(enable_bytes) > LOOKUP_RVA - ENABLE_RVA:
        raise ValueError('Enable helper exceeds reserved section bounds')
    payload[ENABLE_RVA-SECTION_RVA:ENABLE_RVA-SECTION_RVA+len(enable_bytes)] = enable_bytes

    lookup = Assembler(LOOKUP_RVA)
    lookup.emit('57'); lookup.base_edi()
    # This is called inside the original caption helper, with native page index
    # in EBX and child index in ESI. Reacquire the child just like its old switch.
    lookup.emit('89da 8b87'); lookup.word(0xb76650 - IMAGE_BASE)
    lookup.relative('e8', 0xa3f2a0)
    lookup.emit('89f2'); lookup.relative('e8', 0xa424c4)
    lookup.emit('8b8878020000 83f9'); lookup.emit(f'{len(RESOLUTIONS):02x}')
    lookup.branch('0f83', 'custom')
    lookup.emit('8b94cf'); lookup.word(TABLE_RVA)
    lookup.emit('8955f8 8b94cf'); lookup.word(TABLE_RVA + 4)
    lookup.emit('8955f4'); lookup.branch('e9', 'done')
    lookup.label('custom')
    lookup.emit('8d87'); lookup.word(0x8839dc - IMAGE_BASE)
    lookup.relative('e8', 0x688328); lookup.emit('8945f8')
    lookup.emit('8d87'); lookup.word(0x8839ec - IMAGE_BASE)
    lookup.relative('e8', 0x688328); lookup.emit('8945f4')
    lookup.label('done')
    lookup.emit('5f'); lookup.relative('e9', 0x8849c2)
    lookup_bytes = lookup.finish()
    if len(lookup_bytes) > TABLE_RVA - LOOKUP_RVA:
        raise ValueError('Lookup exceeds reserved section bounds')
    payload[LOOKUP_RVA-SECTION_RVA:LOOKUP_RVA-SECTION_RVA+len(lookup_bytes)] = lookup_bytes
    payload[SIGNATURE_RVA-SECTION_RVA:SIGNATURE_RVA-SECTION_RVA+len(SIGNATURE)] = SIGNATURE
    return bytes(payload), dict(
        section_name=SECTION_NAME.decode(), section_rva=hex(SECTION_RVA),
        section_bytes=SECTION_SIZE, constructor_bytes=len(create_bytes),
        enable_bytes=len(enable_bytes), lookup_bytes=len(lookup_bytes), presets=[list(pair) for pair in RESOLUTIONS],
        custom_saved_resolution_preserved=True, position_independent=True,
        native_apply_callback_preserved=True, native_caption_parser_preserved=True,
        enabled_in_all_windowed_types=True, enabled_in_crt_fullscreen_only=True,
        lcd_fullscreen_and_desktop_use_native_desktop_dimensions=True, desktop_mode=2,
        native_panel_before=[384, 320], native_panel_after=[384, 384],
        native_buttons_follow_panel_height=True, button_y_before=272,
        button_y_after=336, maximum_resolution_row_bottom=304,
        minimum_gap_above_buttons=32,
    )


def replacement(va: int, before: bytes, rva: int) -> bytes:
    return b'\xe9' + struct.pack('<i', IMAGE_BASE + rva - va - 5) + b'\x90' * (len(before)-5)


def patch(data: bytes) -> bytes:
    """Return a patched copy, rejecting every unrecognized original image."""
    pe = pefile.PE(data=data)
    payload, _ = section_payload()
    installed = [s for s in pe.sections if s.Name.rstrip(b'\0') == SECTION_NAME]
    if installed:
        section = installed[0]
        if len(installed) != 1 or section.VirtualAddress != SECTION_RVA or \
                data[section.PointerToRawData:section.PointerToRawData+SECTION_SIZE] != payload:
            raise ValueError('Unrecognized existing resolution UI extension')
        for va, before, rva in HOOKS:
            offset = pe.get_offset_from_rva(va - IMAGE_BASE)
            if data[offset:offset+len(before)] != replacement(va, before, rva):
                raise ValueError('Existing resolution UI hook differs')
        offset = pe.get_offset_from_rva(ENABLE_VA - IMAGE_BASE)
        if data[offset:offset+len(ENABLE_AFTER)] != ENABLE_AFTER:
            raise ValueError('Existing resolution enable behavior differs')
        offset = pe.get_offset_from_rva(SCREEN_BOUNDS_VA - IMAGE_BASE)
        if data[offset:offset+len(SCREEN_BOUNDS_AFTER)] != SCREEN_BOUNDS_AFTER:
            raise ValueError('Existing resolution panel geometry differs')
        for va in BUTTON_ROW_VAS:
            offset = pe.get_offset_from_rva(va - IMAGE_BASE)
            if data[offset:offset+len(BUTTON_ROW_CODE)] != BUTTON_ROW_CODE:
                raise ValueError('Native button positioning differs')
        return data
    if hashlib.sha256(data).hexdigest() != BASE_SHA:
        raise ValueError('Unsupported silver.dll; expected published 2026.10.09.10')
    if pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE:
        raise ValueError('Unexpected preferred image base')
    last_end = max(s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData) for s in pe.sections)
    alignment = pe.OPTIONAL_HEADER.SectionAlignment
    if (last_end + alignment - 1) // alignment * alignment != SECTION_RVA:
        raise ValueError('Unexpected preceding section layout')
    header = pe.sections[-1].get_file_offset() + 40
    if header + 40 > pe.OPTIONAL_HEADER.SizeOfHeaders or any(data[header:header+40]):
        raise ValueError('No verified empty PE section header slot')
    result = bytearray(data)
    for va, before, rva in HOOKS:
        offset = pe.get_offset_from_rva(va - IMAGE_BASE)
        if data[offset:offset+len(before)] != before:
            raise ValueError(f'Unexpected native hook at {va:#x}')
        result[offset:offset+len(before)] = replacement(va, before, rva)
    offset = pe.get_offset_from_rva(ENABLE_VA - IMAGE_BASE)
    if data[offset:offset+len(ENABLE_BEFORE)] != ENABLE_BEFORE:
        raise ValueError('Unexpected native resolution enable code')
    result[offset:offset+len(ENABLE_AFTER)] = ENABLE_AFTER
    # Native bounds stack order is width=384, height=320. All new presets fit
    # within height384, including an unmatched saved-resolution sixth row.
    # Both native buttons already derive Y as parent.Height-48, so increasing
    # the parent height moves Apply/Back down64 without changing their logic.
    offset = pe.get_offset_from_rva(SCREEN_BOUNDS_VA - IMAGE_BASE)
    if data[offset:offset+len(SCREEN_BOUNDS_BEFORE)] != SCREEN_BOUNDS_BEFORE:
        raise ValueError('Unexpected native Screen panel bounds')
    for va in BUTTON_ROW_VAS:
        at = pe.get_offset_from_rva(va - IMAGE_BASE)
        if data[at:at+len(BUTTON_ROW_CODE)] != BUTTON_ROW_CODE:
            raise ValueError('Native buttons no longer follow panel height')
    result[offset:offset+len(SCREEN_BOUNDS_AFTER)] = SCREEN_BOUNDS_AFTER
    file_alignment = pe.OPTIONAL_HEADER.FileAlignment
    raw_offset = (len(result) + file_alignment - 1) // file_alignment * file_alignment
    result.extend(bytes(raw_offset-len(result)))
    result.extend(payload)
    result[header:header+40] = struct.pack(
        '<8sIIIIIIHHI', SECTION_NAME, SECTION_SIZE, SECTION_RVA,
        SECTION_SIZE, raw_offset, 0, 0, 0, 0, 0xe0000020,
    )
    struct.pack_into('<H', result, pe.FILE_HEADER.get_field_absolute_offset('NumberOfSections'), len(pe.sections)+1)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), SECTION_RVA+SECTION_SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    original = args.source.read_bytes()
    updated = patch(original)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(updated)
    _, report = section_payload()
    report.update(base_sha256=hashlib.sha256(original).hexdigest(),
                  candidate_sha256=hashlib.sha256(updated).hexdigest(),
                  base_bytes=len(original), candidate_bytes=len(updated),
                  graphical_client_validation=False, published=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
