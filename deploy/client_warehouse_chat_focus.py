"""Publish an overlay that releases focus from the covered barracks editor."""
from hashlib import sha256

import pefile

from . import client_warehouse_chat as chat

SOURCE_SHA = '0b72c0607ef4058a9be2aca2aa4d334c0ef8a7618391b407e069e7bfcdcf73c8'


def patch(source: bytes) -> bytes:
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the published 2026.11.20.14 client')
    result = bytearray(source)
    release = chat.release_edit_code()
    replacements = (
        (chat.BUTTON, chat.button_code(), chat.button_code(release_covered_focus=True)),
        (chat.TAB, chat.tab_code(), chat.tab_code(release_covered_focus=True)),
        (chat.RELEASE_EDIT, bytes(len(release)), release),
    )
    with pefile.PE(data=source, fast_load=True) as pe:
        for address, before, after in replacements:
            offset = pe.get_offset_from_rva(address - chat.BASE)
            if source[offset:offset+len(after)] != before:
                raise ValueError(f'Unexpected chat patch site {address:#x}')
            result[offset:offset+len(after)] = after
    return bytes(result)
