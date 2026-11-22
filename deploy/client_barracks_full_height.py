"""Continue the native PDA frame and fill the taller A2 barracks columns."""
from __future__ import annotations

import hashlib
import re
import struct

import pefile

from . import client_warehouse_chat as chat
from .client_barracks_a2 import BASE, LEFT, LAYOUT, TABLE, TABS, _child, _global
from .client_barracks_bag import BAG
from .client_barracks_skin import native_colour
from .client_equipment_batch import Code
from .client_ui_scale import ITEMS_VIEW

SOURCE_SHA = 'a1fb3517cdbda86e89c05f512a05546516194e45720f2efed4fcb3ef51d6492e'
SHELL_PAINT, BAG_PAINT = 0x9e76e8, 0xca9200
REFLOW, SHELL, SHELL_HEIGHT, BAG_DRAW, PANEL_HEIGHT, RAIL_LABEL = (
    0xcb8000, 0xcb8600, 0xcb8a00, 0xcb8b00, 0xcb9000, 0xcb9100,
)
SCREEN_WIDTH = 0xac56e0
RAIL_OFFSET = 156
HEIGHT_WRAPPERS = 0xcb9200
COLUMN_ANCHORS = 0xcb9400


def reflow_code() -> bytes:
    c = Code(REFLOW)
    c.emit('9c60 83ec10 8d6c2410')
    _global(c, TABLE, 'done'); c.emit('89c6')
    _global(c, LEFT, 'done'); c.emit('89c7')
    c.emit('8b574c 39564c'); c.branch('0f85', 'done')
    c.emit('8b5634 03563c 2b5734 8955fc 8b473c 29c2')
    c.branch('0f8e', 'done')
    c.emit('8955f8 8b55fc 89573c')
    _global(c, TABS, 'done')
    c.emit('8b5734 0355fc 83ea40 895034 8955f4')

    _global(c, BAG, 'model')
    c.emit('39784c'); c.branch('0f85', 'model')
    c.emit('89c6 8b45fc 2b4634 83e824 31d2 b93e000000')
    c.emit('817e383a010000'); c.branch('0f85', 'rows')
    c.emit('b930000000')
    c.label('rows')
    c.emit('f7f1 0fafc1 89c2 89f0'); c.call(ITEMS_VIEW)
    _child(c, LEFT, 26, 'model')
    c.emit('8b5634 03563c 83c207 895034')

    c.label('model')
    _child(c, LEFT, 2, 'done')
    # The native render target is square. Move its centre down and widen the
    # square while keeping the armour and skill hit regions out of the way.
    c.emit('89c6 8b4638 89c1')
    c.emit('817d f8d0000000'); c.branch('0f8e', 'compact_model')
    c.emit('c1e901 01c8 894638 d1e9 83e908'); c.branch('e9', 'position_model')
    c.label('compact_model')
    c.emit('c1e903 01c8 894638 d1e9 83c106')
    c.label('position_model')
    c.emit('294e30')
    c.emit('8b45f8 6bc002 31d2 b903000000 f7f1 83c010 014634')
    c.emit('8b463c d1e8 034634 034734 8b55f4 83c20c 29c2 8996f0020000')
    c.label('done')
    c.emit('83c410 619dc3')
    return c.finish(SHELL-REFLOW)


def _fill(c: Code, colour: int) -> None:
    c.emit('6a00 68'); c.word(native_colour(colour))
    c.emit('6802010000')


def shell_code() -> bytes:
    c = Code(SHELL)
    c.emit('9c60'); c.base()
    chat._get(c, 'esi', chat.ACTIVE); c.emit('85f6'); c.branch('0f84', 'stock')
    c.emit('83ec2c 8d6c242c')
    chat._get(c, 'eax', chat.SCREEN_HEIGHT-BASE)
    c.emit('8b00 8945fc 2b463c 8945f8')
    chat._get(c, 'eax', SCREEN_WIDTH-BASE)
    c.emit('8b00 8945f4 ff763c')
    _fill(c, 0xff1b2026)
    c.emit('31c0 8b55f8 8b4df4'); c.call(0x4f2888)
    # Bridge the stretch between the native upper and lower right corners
    # with the matching right rail already registered in the PDA atlas.
    c.emit('8d55d8 8d83'); c.word(RAIL_LABEL-BASE+12); c.call(0x4f26f4)
    c.emit('0fb74ddc 0fb77dde 85c9'); c.branch('0f84', 'end')
    c.emit('85ff'); c.branch('0f84', 'end')
    c.emit('294df4 8b45fc 05'); c.word(RAIL_OFFSET-512)
    c.emit('8945fc be80010000')
    c.label('segment')
    c.emit('3b75fc'); c.branch('0f8d', 'end')
    c.emit('8975f0 db45f4 83ec04 d91c24 db45f0 83ec04 d91c24')
    c.emit('31d2 31c9 8d45d8'); c.call(0x4f2788)
    c.emit('01fe'); c.branch('e9', 'segment')
    c.label('end')
    c.emit('83c42c')
    chat._stock(c, SHELL_PAINT, '558bec 83c4b8')
    return c.finish(SHELL_HEIGHT-SHELL)


def shell_height_code() -> bytes:
    c = Code(SHELL_HEIGHT)
    c.emit('9c53'); c.base()
    c.emit('8b00 83bb'); c.word(chat.ACTIVE); c.emit('00'); c.branch('0f84', 'done')
    c.emit('05'); c.word(RAIL_OFFSET)
    c.label('done')
    c.emit('5b9dc3')
    return c.finish(BAG_DRAW-SHELL_HEIGHT)


def bag_code(first_row: int = 3) -> bytes:
    c = Code(BAG_DRAW)
    c.emit('9c60'); c.base()
    c.emit('83bb'); c.word(chat.ACTIVE); c.emit('00'); c.branch('0f84', 'stock')
    c.emit('8b74241c 3bb3'); c.word(BAG-BASE); c.branch('0f85', 'stock')
    c.emit('83ec1c 8d6c241c 89f0'); c.call(0xa4211c); c.emit('8945fc')
    c.emit('89f0'); c.call(0xa42140); c.emit('8945f8')
    c.emit('b85e000000 ba3e000000 817e383a010000'); c.branch('0f85', 'start')
    c.emit('b845000000 ba30000000')
    c.label('start')
    c.emit(f'8945f4 8955f0 6bc2{first_row:02x} 83c003 8945ec')
    c.label('row')
    c.emit('8b45ec 0345f0 83e806 3b463c'); c.branch('0f8f', 'done')
    c.emit('c745e803000000 c745e404000000')
    c.label('cell')
    for inset, colour in ((0, 0xff30383c), (1, 0xff14191d)):
        c.emit(f'8b45f0 83e8{6+2*inset:02x} 50')
        _fill(c, colour)
        c.emit('8b45fc 0345e8 8b55f8 0355ec 8b4df4')
        if inset:
            c.emit('40 42 83e902')
        c.call(0x4f2888)
    c.emit('8b45f4 83c006 0145e8 ff4de4'); c.branch('0f85', 'cell')
    c.emit('8b45f0 0145ec'); c.branch('e9', 'row')
    c.label('done')
    c.emit('83c41c')
    chat._stock(c, BAG_PAINT, '558bec 83ec30')
    return c.finish(PANEL_HEIGHT-BAG_DRAW)


def panel_height_code(address: int, stock_offset: int, docked_offset: int) -> bytes:
    c = Code(address)
    c.emit('83bb'); c.word(chat.ACTIVE); c.emit('00'); c.branch('0f84', 'original')
    chat._get(c, 'edx', LEFT-BASE)
    c.emit('8b523c')
    if docked_offset:
        c.emit('81c2'); c.word(docked_offset)
    c.emit('c3')
    c.label('original')
    c.emit('81c2'); c.word(stock_offset); c.emit('c3')
    return c.finish(0x40)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the verified warehouse with the chat dock')
    candidate = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        def write(va: int, data: bytes, *, empty: bool = False) -> None:
            at = pe.get_offset_from_rva(va-BASE)
            if empty and any(source[at:at+len(data)]):
                raise ValueError(f'Occupied barracks code space at {va:#x}')
            candidate[at:at+len(data)] = data

        def redirect(site: int, target: int, size: int, *, call: bool = False) -> None:
            c = Code(site)
            (c.call if call else c.jump)(target)
            write(site, bytes(c.data).ljust(size, b'\x90'))

        if pe.get_data(chat.FRAME-BASE, len(chat.frame_code())) != chat.frame_code():
            raise ValueError('Unexpected warehouse frame entry')
        write(chat.FRAME, chat.frame_code(layout=REFLOW, restore=LAYOUT))
        for address, code in ((REFLOW, reflow_code()), (SHELL, shell_code()),
                              (SHELL_HEIGHT, shell_height_code()), (BAG_DRAW, bag_code())):
            write(address, code, empty=True)
        rail = 'gui_main_1-6'
        write(RAIL_LABEL, struct.pack('<HHiI',1200,2,-1,len(rail))+rail.encode('utf-16le')+b'\0\0',
              empty=True)
        redirect(SHELL_PAINT, SHELL, 5)
        redirect(BAG_PAINT, BAG_DRAW, 5)
        # Leave each relocated absolute load intact and extend its result.
        for index, (site, tail) in enumerate((
            (0x9e77f4, '0fb75706'), (0x9e781c, '0345e4'), (0x9e7849, '2d80010000'),
            (0x9e7876, '0fb75706'), (0x9e78fa, '0fb75706'), (0x9e7939, '0fb75706'),
            (0x9e7987, '0fb75706'),
        )):
            old = bytes.fromhex('8b00 '+tail)
            if pe.get_data(site-BASE, len(old)) != old:
                raise ValueError(f'Unexpected native chassis anchor at {site:#x}')
            c = Code(HEIGHT_WRAPPERS+index*0x40)
            c.call(SHELL_HEIGHT)
            c.emit(tail)
            c.jump(site+len(old))
            write(c.address,c.finish(0x40),empty=True)
            redirect(site,c.address,len(old))
        for inset, sites in (
            (0, (0xcb00b7, 0xcb018b, 0xcb1087, 0xcb115b, 0xcb2057,
                 0xcb212b, 0xcb301f, 0xcb30f3, 0xcb3fe7, 0xcb40bb)),
            (2, (0xcb0109, 0xcb01f1, 0xcb10d9, 0xcb11c1, 0xcb20a9,
                 0xcb2191, 0xcb3071, 0xcb3159, 0xcb4039, 0xcb4121)),
        ):
            address = PANEL_HEIGHT+0x20*inset
            write(address, panel_height_code(address,-124-inset,-inset), empty=True)
            for site in sites:
                if pe.get_data(site-BASE, 6) != b'\x81\xc2'+struct.pack('<i', -124-inset):
                    raise ValueError(f'Unexpected column frame at {site:#x}')
                redirect(site,address,6,call=True)
        # The A2 skin has one rule per width profile. Its bottom corners
        # and the warehouse divider share the same capped height calculation.
        skin = 0xcb0000
        data = pe.get_data(skin-BASE, 0x4f81)
        for index, (offset, count) in enumerate(((-14, 20), (-28, 20), (-94, 10))):
            old = b'\x81\xc2'+struct.pack('<i',offset)
            sites = [skin+m.start() for m in re.finditer(re.escape(old+b'\x03\x55\xf8\xe8'),data)]
            if len(sites) != count:
                raise ValueError(f'Unexpected A2 frame anchors for {offset}')
            address = COLUMN_ANCHORS+index*0x40
            write(address,panel_height_code(address,offset,124+offset),empty=True)
            for site in sites:
                redirect(site,address,6,call=True)
    return bytes(candidate)
