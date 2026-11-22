"""Fit the selected portrait inside the native player-info header."""
import hashlib

import pefile

from .client_portrait_size_20261105 import DRAW, draw_code

SOURCE_SHA = '4908ff724eed1306b6a89cf82af351c466351f97bf5efeb18c24400fe6714aa9'
HEADER_SOURCE_SHA = '9b5031a87c297fa14f40dc7b5879d6138faee66fc3d3675d837d79a04043bf47'
BATTLE_CALLERS = (0x8d0b58, 0x9daae5)
PLAYER_INFO_CALLER = 0x964b49


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected published 2026.11.18.2 Silver')
    with pefile.PE(data=source) as pe:
        offset = pe.get_offset_from_rva(DRAW - pe.OPTIONAL_HEADER.ImageBase)
    before = draw_code(BATTLE_CALLERS)
    if source[offset:offset + len(before)] != before:
        raise ValueError('Native portrait drawing region differs')
    after = draw_code((*BATTLE_CALLERS, PLAYER_INFO_CALLER))
    return source[:offset] + after + source[offset + len(after):]


def patch_header(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != HEADER_SOURCE_SHA:
        raise ValueError('Expected published 2026.11.18.3 Silver')
    # Leave one line beside the portrait for the optional jail or mute notice.
    edits = (
        (0x965e92, '6a12', '6a1a'),                   # portrait top 18 -> 26
        (0x965eee, 'c743343c000000', 'c743344a000000'), # status top 60 -> 74
        (0x965f1f, 'c7433016000000', 'c743304c000000'), # notice left 22 -> 76
        (0x965f26, 'c743344b000000', 'c743343a000000'), # notice top 75 -> 58
    )
    result = bytearray(source)
    with pefile.PE(data=source, fast_load=True) as pe:
        for address, old, new in edits:
            before, after = bytes.fromhex(old), bytes.fromhex(new)
            offset = pe.get_offset_from_rva(address - pe.OPTIONAL_HEADER.ImageBase)
            if source[offset:offset + len(before)] != before:
                raise ValueError(f'Player-info layout differs at {address:#x}')
            result[offset:offset + len(before)] = after
    return bytes(result)
