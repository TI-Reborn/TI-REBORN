"""Pure, SHA-guarded portrait supersampling and native enlarged preview.

TI's persistent charmodel_closeup target becomes 512 square. Its orthographic
world projection remains 256 square and the ordinary GUI destination stays 244
square. A right click on the native portrait opens a separate native window;
left dragging and the existing arrows still rotate the same selected actor.
No installed file, process, account, manifest, or remote service is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import pefile
from .client_equipment_batch import Code

IMAGE_BASE = 0x400000
TI_SHA = 'e288de090e162660604750075c3e633f60744ee8a24915a9bc24e8cc39ee3f1c'
SECTION_RVA = 0x82b000
SIZE = 0x3000
MOUSE_ENTRY = IMAGE_BASE + SECTION_RVA
LAYOUT_ENTRY = MOUSE_ENTRY + 0x500
DRAW_ENTRY = MOUSE_ENTRY + 0x800
QUAD_ENTRY = MOUSE_ENTRY + 0xa00
CLOSE_ENTRY = MOUSE_ENTRY + 0xd00
NAME_EQUAL_ENTRY = MOUSE_ENTRY + 0xe00
HIT_ENTRY = MOUSE_ENTRY + 0xf00
DISPATCH_ENTRY = MOUSE_ENTRY + 0x1000
WALK_ENTRY = MOUSE_ENTRY + 0x1200
STRINGS = SECTION_RVA + 0x1800
WINDOW_NAME = STRINGS
CAPTION = STRINGS + 0x80
CONTROL_NAME = STRINGS + 0x180
SIGNATURE = b'TIO-portrait-512-preview-v1'
SIGNATURE_RVA = SECTION_RVA + 0x1f00
STARTUP_ENTRY = MOUSE_ENTRY + 0x2000
INSTALL_ENTRY = MOUSE_ENTRY + 0x2100
STATE = SECTION_RVA + 0x2e00
PREVIEW_SIDE = 488


def sha(data):
    return hashlib.sha256(data).hexdigest()


def host_call(c, address):
    # TI is the pinned fixed-base EXE; Silver's own relative calls relocate.
    c.emit('bf'); c.word(address); c.emit('ffd7')


def literal(c, register, rva, header=12):
    c.emit({'eax': '8d83', 'edx': '8d93', 'ecx': '8d8b'}[register])
    c.word(rva + header)


def find_window(c):
    # GUI manager is taken from the current native control. No cached instance
    # survives manager replacement, reconnect, or native destruction.
    c.emit('89f8'); literal(c, 'edx', WINDOW_NAME); c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84', 'create')
    c.emit('89c2 89f8'); c.call(0xa3f2a0); c.emit('89c6')


def mouse_code():
    c = Code(MOUSE_ENTRY)
    # Native VMT+28 receives EAX=self, DL=button, ECX=x, stack=y; ret4.
    # Preserve the exact original left-button drag path (and other buttons).
    c.emit('80fa01'); c.branch('0f85', 'stock')
    c.emit('9c60'); c.base()
    c.emit('8b44241c 8bb87c010000 85ff'); c.branch('0f84', 'done')
    find_window(c)
    c.emit('807e4900'); c.branch('0f84', 'show')
    c.emit('89f0'); c.call(0xa4370c)
    c.branch('e9', 'done')
    c.label('create')
    c.emit('89f9 b201 8b83'); c.word(0xa319e8-IMAGE_BASE)
    c.call(0xa4341c); c.emit('89c6')
    c.emit('8d4668'); literal(c, 'edx', WINDOW_NAME); c.call(0x40b47c)
    c.emit('89f0'); literal(c, 'edx', CAPTION, 4); c.call(0xa42b04)
    # A fixed native frame owns the panel. Existing frame close button is made
    # visible and receives one no-argument native callback; no script event.
    c.emit('c6868c02000000 c6868d02000000 c686ac02000001')
    c.emit('8b8644030000 c6404901 05a0020000')
    c.emit('8d93'); c.word(CLOSE_ENTRY-IMAGE_BASE); c.call(0xa55038)
    # The native render-area constructor takes parent,height,width,y on the
    # stack and x in ECX; its closure and lifetime remain native.
    c.emit('6a30'); c.emit('68'); c.word(PREVIEW_SIDE)
    c.emit('68'); c.word(PREVIEW_SIDE); c.emit('56 b914000000 b201 8b83')
    c.word(0x8a228c-IMAGE_BASE); c.call(0x8aa4a4)
    c.emit('8d4068'); literal(c, 'edx', CONTROL_NAME); c.call(0x40b47c)
    c.label('show')
    c.emit('89f0'); c.call(LAYOUT_ENTRY)
    c.emit('89f0 b201'); c.call(0xa43a54)
    c.label('done'); c.emit('619d c20400')
    c.label('stock'); c.jump(0x8aa5a0)
    return c.finish(0x500)


def layout_code():
    c = Code(LAYOUT_ENTRY); c.emit('9c60'); c.base()
    c.emit('8b74241c')  # concrete preview window
    # Silver core exposes logical dimensions here; physical D3D dimensions and
    # the portrait projection are independent. Leave room for native frame,
    # caption, arrows, and the close button even on the smallest logical UI.
    c.emit('8b83'); c.word(0xac56e0-IMAGE_BASE); c.emit('8b00 83e860 89c1')
    c.emit('8b83'); c.word(0xac5e60-IMAGE_BASE); c.emit('8b00 2d80000000')
    c.emit('39c8'); c.branch('0f8e', 'height_min'); c.emit('89c8')
    c.label('height_min'); c.emit('3d'); c.word(PREVIEW_SIDE)
    c.branch('0f8e', 'side_max'); c.emit('b8'); c.word(PREVIEW_SIDE)
    c.label('side_max'); c.emit('3df4000000'); c.branch('0f8d', 'side_min')
    c.emit('b8f4000000')
    c.label('side_min'); c.emit('89c7 8d4830 51 8d4870 51 31c9 31d2 89f0')
    # Native window setter stack order is width, then height (height at +4).
    c.call(0xa439d8)
    c.emit('89f0'); c.call(0xa43748)
    # Native SetWidth anchors the close button at W-22, although its actual
    # width may be64. Keep the whole existing button within the frame.
    c.emit('8b8644030000 85c0'); c.branch('0f84', 'close_done')
    c.emit('8b4e38 2b4838 83e910'); c.branch('0f89', 'close_x')
    c.emit('31c9')
    c.label('close_x'); c.emit('894830')
    c.label('close_done')
    c.emit('89f0'); c.call(0xa424d4)
    c.emit('85c0'); c.branch('0f84', 'done')
    # Only one portrait child is constructed, besides the close button. Find
    # its concrete class rather than assuming native child-list ordering.
    c.emit('89c5 31d2')
    c.label('child'); c.emit('52 89f0'); c.call(0xa424c4); c.emit('5a')
    c.emit('8d8b'); c.word(0x8a22e4-IMAGE_BASE); c.emit('3908')
    c.branch('0f84', 'portrait')
    c.emit('42 39ea'); c.branch('0f8c', 'child'); c.branch('e9', 'done')
    c.label('portrait')
    c.emit('89c1 8b4638 29f8 d1f8 894130 c7413430000000')
    c.emit('897938 89793c 89f8 d1f8 83c012 8981f0020000')
    # Native update8aa5c0 ends its drag rectangle at absY + this field.
    # Keep the entire enlarged portrait within that native polling region.
    c.emit('89b9f4020000 c681e002000000')
    c.label('done'); c.emit('619d c3')
    return c.finish(0x300)


def draw_code():
    c = Code(DRAW_ENTRY); c.emit('60'); c.base()
    # The existing render closure stores its native control in EDI+0xc.
    c.emit('8b4f0c 85c9'); c.branch('0f84', 'stock')
    c.emit('8b414c 85c0'); c.branch('0f84', 'stock')
    c.emit('8b4068 51'); literal(c, 'edx', WINDOW_NAME)
    c.emit('b9'); c.word(len('window_portrait_preview')); c.call(NAME_EQUAL_ENTRY)
    c.emit('59 85c0'); c.branch('0f84', 'stock')
    # Restore original XY and all preserved registers, replacing only volatile
    # ECX with the preview control's current square size for the custom quad.
    c.emit('8b4938 894c2418 61'); c.jump(QUAD_ENTRY)
    c.label('stock'); c.emit('61'); c.jump(0x9b63d0)
    return c.finish(0x200)


def quad_code():
    c = Code(QUAD_ENTRY)
    c.emit('55 89e5 83ec60 53 56 57')
    c.emit('894df4 894df0 d1f9 29c8 29ca 8945fc 8955f8')
    c.emit('b803000000'); host_call(c, 0x7427d8)
    # Identical native quad order and UV/color arguments to TI6f709c. Only its
    # logical destination changes, using the actual preview-control size.
    for left, top in ((True, True), (False, True), (False, False), (True, False)):
        for origin, extent, include_extent in ((0xfc, 0xf4, not left), (0xf8, 0xf0, not top)):
            c.emit('8b45'); c.emit(f'{origin:02x}')
            if include_extent: c.emit('0345'); c.emit(f'{extent:02x}')
            c.emit('8945dc db45dc 83ec08 dd1c24')
    c.emit('6aff 6aff 6a00 6a00 6a00 83c9ff 83caff a1'); c.word(0x777030)
    host_call(c, 0x611c10)
    c.emit('31c0'); host_call(c, 0x7427d8)
    c.emit('5f 5e 5b 89ec 5d c3')
    return c.finish(0x300)


def name_equal_code():
    # Native UnicodeString assignment clones static refcount-1 literals.
    # Compare bounded content, never pointer identity; nil and wrong lengths
    # return before reading any UTF16 character. EAXactual,EDXliteral,ECXlength.
    c = Code(NAME_EQUAL_ENTRY); c.emit('56 89c6 85f6')
    c.branch('0f84', 'different')
    c.emit('394efc'); c.branch('0f85', 'different')
    c.label('word'); c.emit('668b06 663b02'); c.branch('0f85', 'different')
    c.emit('83c602 83c202 49'); c.branch('0f85', 'word')
    c.emit('b801000000 5e c3')
    c.label('different'); c.emit('31c0 5e c3')
    return c.finish(0x100)


def hit_code():
    # A standalone native RenderArea is mouse-transparent without registered
    # script mouse callbacks. Only our concrete preview child accepts native
    # hit testing; its unchanged native MouseDown then starts the native drag.
    c = Code(HIT_ENTRY); c.emit('9c60'); c.base()
    c.emit('8b74241c 85f6'); c.branch('0f84', 'stock')
    c.emit('8d83'); c.word(0x8a22e4-IMAGE_BASE)
    c.emit('3906'); c.branch('0f85', 'stock')
    c.emit('8b464c 85c0'); c.branch('0f84', 'stock')
    c.emit('8b93'); c.word(0xa319e8-IMAGE_BASE)
    c.emit('3910'); c.branch('0f85', 'stock')
    c.emit('8b4068'); literal(c, 'edx', WINDOW_NAME)
    c.emit('b9'); c.word(len('window_portrait_preview')); c.call(NAME_EQUAL_ENTRY)
    c.emit('85c0'); c.branch('0f84', 'stock')
    c.emit('619d 31c0 c3')
    c.label('stock'); c.emit('619d 558bec515356'); c.jump(0xa4d68a)
    return c.finish(0x100)


def close_code():
    c = Code(CLOSE_ENTRY); c.emit('9c60'); c.base()
    c.emit('8b83'); c.word(0xb76650-IMAGE_BASE); c.emit('89c7 85ff')
    c.branch('0f84', 'done')
    c.emit('89f8'); literal(c, 'edx', WINDOW_NAME); c.call(0xa3fca8)
    c.emit('83f8ff'); c.branch('0f84', 'done')
    c.emit('89c2 89f8'); c.call(0xa3f2a0); c.call(0xa4370c)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x100)


def dispatch_code():
    c = Code(DISPATCH_ENTRY); c.emit('9c60')
    # Core has already converted ESI/EDI to logical XY. Never inspect, convert,
    # consume or change the original left/middle input or TI's physical input.
    # TI passes button modifiers in the high bytes (real right click 0x101).
    # Native GUI handlers interpret DL: only inspect that low byte, retaining
    # the complete tagged button value for every original fallback path.
    c.emit('807c241001'); c.branch('0f85', 'stock')
    c.base(); c.emit('83ec10 8b83'); c.word(0xb76650-IMAGE_BASE)
    c.emit('85c0'); c.branch('0f84', 'miss')
    c.emit('8b8080020000 85c0'); c.branch('0f84', 'miss')
    c.emit('8b4808 85c9'); c.branch('0f84', 'miss')
    c.emit('81f900020000'); c.branch('0f87', 'miss')
    c.emit('890c24 8b4004 89442404 85c0'); c.branch('0f84', 'miss')
    c.emit('c744240800000000')
    c.label('root')
    c.emit('8b4c2408 8b442404 8b0488 8b542414 8b4c2410 6a00')
    c.call(WALK_ENTRY)
    c.emit('85c0'); c.branch('0f85', 'found')
    c.emit('ff442408 8b442408 3b0424'); c.branch('0f82', 'root')
    c.label('miss'); c.emit('83c410'); c.branch('e9', 'stock')
    c.label('found')
    c.emit('8b4c2414 ff742410 b201'); c.call(MOUSE_ENTRY)
    c.emit('83c410 619d 5f5e5b 83c408 5d c20c00')
    c.label('stock'); c.emit('619d')
    # Replay the removed SEH prologue with a PIC handler pointer. ECX is native
    # volatile; ESI/EDI/EBX and the export's stack convention stay unchanged.
    c.emit('e800000000 59 81c1')
    c.word(0x9f4ab7-(c.address+len(c.data)-3))
    c.emit('33c0 55 51'); c.jump(0x9f4867)
    return c.finish(0x200)


def walk_code():
    c = Code(WALK_ENTRY); c.emit('55 89e5 83ec10 53 56 57'); c.base()
    c.emit('89c6 8955fc 894df8 85f6'); c.branch('0f84', 'none')
    c.emit('807e4900'); c.branch('0f84', 'none')
    c.emit('837d0810'); c.branch('0f83', 'none')
    c.emit('8d83'); c.word(0x8a22e4-IMAGE_BASE); c.emit('3906')
    c.branch('0f84', 'portrait')
    # The city shop uses a regular render area named shopchar, rather than the
    # character-specific VMT. Its existing draw closure remains unchanged.
    c.emit('8b83'); c.word(0xa2c1b0-IMAGE_BASE); c.emit('3906')
    c.branch('0f85', 'children')
    c.emit('8b4668 8d93'); c.word(0x8d5acc-IMAGE_BASE)
    c.emit('b908000000'); c.call(NAME_EQUAL_ENTRY)
    c.emit('85c0'); c.branch('0f84', 'children')
    c.label('portrait')
    # Respect real native hover layering. A sibling button, equipment cell,
    # modal dialog or any other hovered component keeps its original input.
    c.emit('8b83'); c.word(0xb76650-IMAGE_BASE); c.emit('8b88d4020000 85c9')
    c.branch('0f84', 'bounds')
    c.emit('89f0 ba20000000')
    c.label('ancestor'); c.emit('39c8'); c.branch('0f84', 'bounds')
    c.emit('8b404c 85c0'); c.branch('0f84', 'children')
    c.emit('4a'); c.branch('0f85', 'ancestor'); c.branch('e9', 'children')
    c.label('bounds')
    c.emit('89f0'); c.call(0xa4211c); c.emit('8945f4')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f0')
    c.emit('8b464c 85c0'); c.branch('0f84', 'normal_bounds')
    c.emit('8b4068'); literal(c, 'edx', WINDOW_NAME)
    c.emit('b9'); c.word(len('window_portrait_preview')); c.call(NAME_EQUAL_ENTRY)
    c.emit('85c0'); c.branch('0f84', 'normal_bounds')
    c.emit('8b7e38'); c.branch('e9', 'test')
    c.label('normal_bounds')
    c.emit('8b4638 d1f8 83e87c 0145f4 8b463c d1f8 2d98000000 0145f0')
    c.emit('bff4000000')
    c.label('test')
    c.emit('8b55fc 2b55f4 39fa'); c.branch('0f83', 'children')
    c.emit('8b55f8 2b55f0 39fa'); c.branch('0f83', 'children')
    c.emit('89f0'); c.branch('e9', 'return')
    c.label('children')
    c.emit('89f0'); c.call(0xa424d4)
    c.emit('85c0'); c.branch('0f84', 'none')
    c.emit('3d00040000'); c.branch('0f87', 'none')
    c.emit('89c7')
    c.label('child')
    c.emit('4f 89fa 89f0'); c.call(0xa424c4)
    c.emit('8b5508 42 52 8b55fc 8b4df8'); c.call(WALK_ENTRY)
    c.emit('85c0'); c.branch('0f85', 'return')
    c.emit('85ff'); c.branch('0f85', 'child')
    c.label('none'); c.emit('31c0')
    c.label('return'); c.emit('5f5e5b 89ec 5d c20400')
    return c.finish(0x600)


def state_store(c, offset):
    c.emit('8983'); c.word(STATE + offset)


def state_set(c, offset, value):
    c.emit('c783'); c.word(STATE + offset); c.word(value & 0xffffffff)


def startup_code():
    c = Code(STARTUP_ENTRY)
    # The Screen preference wrapper already owns the native registration tail.
    # Run on the startup UI thread after TI creates its portrait target and
    # before the timer's rendering loop, then retain the exact existing chain.
    c.emit('9c60'); c.call(INSTALL_ENTRY); c.emit('619d'); c.jump(0xc29b00)
    return c.finish(0x100)


def install_code():
    c = Code(INSTALL_ENTRY); c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(STATE); c.emit('00'); c.branch('0f85', 'done')
    # The launcher pins TI on disk. Additional executable guards reject an
    # unexpected runtime host without changing any executable instruction.
    for address, raw in ((0x6f702a, bytes.fromhex('b9000100')),
                         (0x6f702e, bytes.fromhex('00ba0001')),
                         (0x6108f0, bytes.fromhex('558bec83'))):
        c.emit('813d'); c.word(address); c.emit(raw.hex())
        c.branch('0f85', 'unavailable')
    c.emit('66813d32706f000000'); c.branch('0f85', 'unavailable')
    c.emit('66813df4086100c4e4'); c.branch('0f85', 'unavailable')
    c.emit('8b3530707700 85f6'); c.branch('0f84', 'unavailable')
    c.emit('8b4608 85c0'); c.branch('0f84', 'unavailable')
    c.emit('83784400'); c.branch('0f84', 'unavailable')
    c.emit('807e6001'); c.branch('0f85', 'unavailable')
    c.emit('837e0c00'); c.branch('0f84', 'unavailable')
    # Original closeup allocation has no owned depth surface: its native
    # binding keeps the renderer's shared depth when +10 is null. Reject an
    # unexpected owned surface rather than release an unsupported contract.
    c.emit('837e1000'); c.branch('0f85', 'unavailable')
    # Idempotent binding: do not release an already valid 512 target.
    c.emit('817e2000020000'); c.branch('0f85', 'original')
    c.emit('817e1c00020000'); c.branch('0f85', 'unavailable')
    c.emit('817e1400020000'); c.branch('0f85', 'unavailable')
    c.emit('817e1800020000'); c.branch('0f85', 'unavailable')
    c.branch('e9', 'success')
    c.label('original')
    for field in (0x20, 0x1c, 0x14, 0x18):
        c.emit('817e'+f'{field:02x}'+'00010000'); c.branch('0f85', 'unavailable')
    c.emit('89f0'); state_store(c, 8)
    c.emit('0fb64661'); state_store(c, 0xc)
    # The original factory uses Format21 and restores depthWanted after the
    # same method. Its shared target object and manager ownership stay intact.
    c.emit('6a15 89f0 ba00020000 b900020000'); host_call(c, 0x6108f0)
    c.emit('8b83'); c.word(STATE + 0xc); c.emit('884661')
    c.emit('807e6001'); c.branch('0f85', 'rollback')
    c.emit('837e0c00'); c.branch('0f84', 'rollback')
    for field in (0x20, 0x1c, 0x14, 0x18):
        c.emit('817e'+f'{field:02x}'+'00020000'); c.branch('0f85', 'rollback')
    c.label('success'); state_set(c, 0, 1); c.branch('e9', 'done')
    c.label('rollback')
    state_set(c, 4, 2)
    c.emit('6a15 89f0 ba00010000 b900010000'); host_call(c, 0x6108f0)
    c.emit('8b83'); c.word(STATE + 0xc); c.emit('884661')
    state_set(c, 0, -1)
    c.emit('807e6001'); c.branch('0f85', 'rollback_failed')
    c.emit('837e0c00'); c.branch('0f84', 'rollback_failed')
    for field in (0x20, 0x1c, 0x14, 0x18):
        c.emit('817e'+f'{field:02x}'+'00010000'); c.branch('0f85', 'rollback_failed')
    c.branch('e9', 'done')
    c.label('rollback_failed'); state_set(c, 4, 3); c.branch('e9', 'done')
    c.label('unavailable'); state_set(c, 0, -1); state_set(c, 4, 1)
    c.label('done'); c.emit('619d c3')
    return c.finish(0x700)


def extension():
    result = bytearray(SIZE)
    for offset, code in ((0, mouse_code()), (0x500, layout_code()),
                         (0x800, draw_code()), (0xa00, quad_code()), (0xd00, close_code()),
                         (0xe00, name_equal_code()), (0xf00, hit_code()),
                         (0x1000, dispatch_code()), (0x1200, walk_code()),
                         (0x2000, startup_code()), (0x2100, install_code())):
        result[offset:offset+len(code)] = code
    for rva, value, limit in ((WINDOW_NAME, 'window_portrait_preview', 0x80),
                             (CAPTION, 'Боец: мышь — поворот, ПКМ — закрыть', 0x100),
                             (CONTROL_NAME, 'portrait_preview_model', 0x80)):
        encoded = value.encode('utf-16le')
        # Names and lookup are native managed UnicodeString; captions use the
        # separate native BSTR ABI, whose length at pointer-4 is in bytes.
        raw = ((struct.pack('<I', len(encoded)) if rva == CAPTION else
                struct.pack('<HHiI', 1200, 2, -1, len(value)))+encoded+b'\0\0')
        assert len(raw) <= limit
        result[rva-SECTION_RVA:rva-SECTION_RVA+len(raw)] = raw
    result[SIGNATURE_RVA-SECTION_RVA:SIGNATURE_RVA-SECTION_RVA+len(SIGNATURE)] = SIGNATURE
    return bytes(result)


def patch_ti(data):
    """Validate and retain the launcher's exact pinned executable unchanged."""
    if sha(data) != TI_SHA:
        raise ValueError('Portrait requires the exact original TI executable')
    pe = pefile.PE(data=data)
    site = pe.get_offset_from_rva(0x6f702a-IMAGE_BASE)
    before = bytes.fromhex('b900010000 ba00010000')
    if data[site:site+10] != before:
        raise ValueError('Portrait target creation changed')
    return data


def patch(data, *, expected_sha):
    if sha(data) != expected_sha:
        raise ValueError('Portrait requires the exact reviewed UI-scale panel candidate')
    pe = pefile.PE(data=data)
    if (pe.FILE_HEADER.Machine != 0x14c or pe.OPTIONAL_HEADER.ImageBase != IMAGE_BASE or
            pe.OPTIONAL_HEADER.SizeOfImage != SECTION_RVA):
        raise ValueError('Unknown pre-portrait Silver layout')
    last = pe.sections[-1]
    if (last.VirtualAddress+last.Misc_VirtualSize != SECTION_RVA or
            last.PointerToRawData+last.SizeOfRawData != len(data) or
            last.Misc_VirtualSize != last.SizeOfRawData or len(data)%0x200):
        raise ValueError('Silver final section is not safely appendable')
    result = bytearray(data)
    sites = ((0x8aa21f, bytes.fromhex('e8acc11000'),
              b'\xe8'+struct.pack('<i', DRAW_ENTRY-0x8aa21f-5)),
             (0x8a230c, struct.pack('<I', 0x8aa5a0), struct.pack('<I', MOUSE_ENTRY)),
             (0xa4d684, bytes.fromhex('558bec515356'),
              b'\xe9'+struct.pack('<i', HIT_ENTRY-0xa4d684-5)+b'\x90'),
             (0x9f485f, bytes.fromhex('33c05568b74a9f00'),
              b'\xe9'+struct.pack('<i', DISPATCH_ENTRY-0x9f485f-5)+b'\x90'*3),
             (0x4f255f, b'\xe9'+struct.pack('<i', 0xc29b00-0x4f255f-5),
              b'\xe9'+struct.pack('<i', STARTUP_ENTRY-0x4f255f-5)))
    for va, before, after in sites:
        offset = pe.get_offset_from_rva(va-IMAGE_BASE)
        if data[offset:offset+len(before)] != before:
            raise ValueError(f'Portrait hook changed at {va:#x}')
        result[offset:offset+len(after)] = after
    relocations = [entry for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
                   if entry.type == 3 and entry.rva == 0x8a230c-IMAGE_BASE]
    if len(relocations) != 1:
        raise ValueError('Native portrait VMT pointer relocation missing')
    removed = [entry for block in pe.DIRECTORY_ENTRY_BASERELOC for entry in block.entries
               if entry.type == 3 and 0x5f485f <= entry.rva < 0x5f4867]
    if len(removed) != 1 or removed[0].rva != 0x5f4863:
        raise ValueError('Native mouse SEH relocation differs')
    struct.pack_into('<H', result, removed[0].struct.get_file_offset(), removed[0].rva & 0xfff)
    # The replaced VMT pointer retains its original HIGHLOW relocation. New
    # code is PIC and uses no new absolute Silver operands or relocation table.
    for field in ('Misc_VirtualSize', 'SizeOfRawData'):
        struct.pack_into('<I', result, last.get_field_absolute_offset(field),
                         getattr(last, field)+SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('SizeOfImage'), SECTION_RVA+SIZE)
    struct.pack_into('<I', result, pe.OPTIONAL_HEADER.get_field_absolute_offset('CheckSum'), 0)
    result.extend(extension())
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--ti-source', type=Path, required=True)
    parser.add_argument('--ti-output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    source, ti_source = args.source.read_bytes(), args.ti_source.read_bytes()
    candidate, ti_candidate = patch(source, expected_sha=args.expected_sha), patch_ti(ti_source)
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_bytes(candidate)
    args.ti_output.parent.mkdir(parents=True, exist_ok=True); args.ti_output.write_bytes(ti_candidate)
    report = dict(source_sha256=sha(source), candidate_sha256=sha(candidate), candidate_bytes=len(candidate),
                  ti_source_sha256=sha(ti_source), ti_candidate_sha256=sha(ti_candidate), ti_changed_bytes=0,
                  runtime_executable_changed_bytes=0, existing_target_rebuilt_at_startup=True,
                  target=[512, 512], world_orthographic_projection=[256, 256], normal_destination=[244, 244],
                  enlarged_destination_max=[488, 488], enlarged_native_window=True,
                  native_rotation_preserved=True, native_device_lifecycle=True,
                  graphical_validation=False, published=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
