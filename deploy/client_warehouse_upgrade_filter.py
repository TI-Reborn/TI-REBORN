"""Anchor and extend the native warehouse filter in client 2026.11.20.15."""
from hashlib import sha256
import struct

import pefile

from .client_barracks_a2 import STATE
from .client_equipment_batch import Code
from .client_ui_scale import INVENTORY_FOOTER

BASE = 0x400000
SOURCE_SHA = 'a398f8d896b0fff92a3d5638f6ebbef95be518ba37d3b073c2640ca919fd9836'
UPGRADES = 30
MAIN_MENU, SECONDARY_MENU = 0xac4bb4, 0xac4998
MENU_ENTRY, CAPTION = 0xcc6c00, 0xcc6c80
SORT_ENTRY, COMPARE = 0xcc6f00, 0xcc6fc0
ANCHOR_ENTRY, ANCHOR_SITE = 0xcc7000, INVENTORY_FOOTER + 0x94
MENU_HOOK, SORT_HOOK = 0x6cbf1d, 0x9169f4
INCLUDE_PATHS = (
    # Hook, displaced compare/branch, no query, reject, wrapper, category and upgrade fields.
    (0x91597d, '837dfc007439', 0x9159bc, 0x915ad2, 0xcc6d00, '807df3', '807f4e00'),
    (0x917123, '837df800743f', 0x917168, 0x917305, 0xcc6e00, '80bd3bf8ffff', '80bdaefdffff00'),
)


def menu_code() -> bytes:
    c = Code(MENU_ENTRY)
    c.emit('53')
    c.base()
    c.emit('8d93')
    c.word(CAPTION + 12 - BASE)
    c.emit('68a69d51ff 6a' + f'{UPGRADES:02x}' + ' 6a00 31c9 89f0')
    c.call(0x6cc718)
    c.emit('5b 33c0 5a 59 59')
    c.jump(MENU_HOOK + 5)
    return c.finish(CAPTION - MENU_ENTRY)


def anchor_code() -> bytes:
    c = Code(ANCHOR_ENTRY)
    # The footer keeps the image base in its frame while EDX holds the menu height.
    c.emit('8b55ec 83ba')
    c.word(STATE)
    c.emit('01')
    c.branch('0f84', 'under_button')
    c.emit('8b5638 83ea7d 895030 c3')
    c.label('under_button')
    c.emit('31d2 895030 c3')
    return c.finish(0x20)


def include_code(site: int, displaced: str, no_query: int, reject: int,
                 wrapper: int, category: str, upgrade: str) -> bytes:
    c = Code(wrapper)
    c.emit(category + f'{UPGRADES:02x}')
    c.branch('0f85', 'search')
    c.emit(upgrade)
    c.branch('0f85', 'search')
    # A previously selected item is normally pinned through a filter change.
    c.emit('31db')
    c.jump(reject)
    c.label('search')
    c.emit(displaced[:8])
    c.branch('0f85', 'native_search')
    c.jump(no_query)
    c.label('native_search')
    c.jump(site + len(bytes.fromhex(displaced)))
    return c.finish(0x100)


def sort_code() -> bytes:
    c = Code(SORT_ENTRY)
    c.emit('53 51 52')
    c.base()
    c.emit('80b8d802000000')
    c.branch('0f84', 'main')
    c.emit('80b8d802000001')
    c.branch('0f85', 'stock')
    c.emit('8b93')
    c.word(SECONDARY_MENU - BASE)
    c.branch('e9', 'menu')
    c.label('main')
    c.emit('8b93')
    c.word(MAIN_MENU - BASE)
    c.label('menu')
    c.emit('85d2')
    c.branch('0f84', 'stock')
    # This constructor always appends the upgrade option after the stock rows.
    c.emit('8b9288020000 8b4a08 8b5204 8b548afc 66817a0c01' + f'{UPGRADES:02x}')
    c.branch('0f85', 'stock')
    c.emit('8b400c 85c0')
    c.branch('0f84', 'done')
    c.emit('8b50fc 83fa01')
    c.branch('0f86', 'done')
    c.emit('4a 8d8b')
    c.word(COMPARE - BASE)
    # The native sorter borrows this interface and calls only vtable slot +12.
    c.emit('83c408 5b 51 6a00 6a00 6a00 54 89e1')
    c.call(0x7057a0)
    c.emit('83c414 c3')
    c.label('done')
    c.emit('5a 59 5b c3')
    c.label('stock')
    c.emit('5a 59 5b 55 8bec 6a00')
    c.jump(SORT_HOOK + 5)
    return c.finish(COMPARE - SORT_ENTRY)


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the published 2026.11.20.15 client')
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        def write(address: int, before: bytes, after: bytes) -> None:
            offset = pe.get_offset_from_rva(address - BASE)
            if source[offset:offset+len(after)] != before:
                raise ValueError(f'Unexpected warehouse filter patch site {address:#x}')
            result[offset:offset+len(after)] = after

        def redirect(address: int, displaced: str, target: int) -> None:
            before = bytes.fromhex(displaced)
            jump = Code(address)
            jump.jump(target)
            write(address, before, bytes(jump.data).ljust(len(before), b'\x90'))

        label = 'Улучшения'
        caption = struct.pack('<HHiI', 1200, 2, -1, len(label)) + (label + '\0').encode('utf-16le')
        comparator = bytes.fromhex('0fb6414e 0fb6524e 29d0 c3')
        for address, code in ((MENU_ENTRY, menu_code()), (CAPTION, caption),
                              (SORT_ENTRY, sort_code()), (COMPARE, comparator),
                              (ANCHOR_ENTRY, anchor_code())):
            write(address, bytes(len(code)), code)
        displaced = bytes.fromhex('8b5638 83ea7d 895030')
        anchor = Code(ANCHOR_SITE)
        anchor.call(ANCHOR_ENTRY)
        write(ANCHOR_SITE, displaced, bytes(anchor.data).ljust(len(displaced), b'\x90'))
        redirect(MENU_HOOK, '33c05a5959', MENU_ENTRY)
        redirect(SORT_HOOK, '558bec6a00', SORT_ENTRY)
        for path in INCLUDE_PATHS:
            site, displaced, _, _, wrapper, _, _ = path
            code = include_code(*path)
            write(wrapper, bytes(len(code)), code)
            redirect(site, displaced, wrapper)
    return bytes(result)
