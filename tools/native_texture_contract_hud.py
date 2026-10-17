"""Self-contained stdlib contract for the main HUD BMP32/PNG/JPEG package.

BMP headers, original orientation, payload size and native fourth-byte alpha
are byte-exact. JPEG SOF geometry/components/subsampling stay byte-exact;
quantization tables and encoded colour may change for reviewed bitmap edits.
"""
from __future__ import annotations

import hashlib
import struct
import zlib


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jpeg_dimensions(raw: bytes) -> tuple[int, int]:
    if raw[:2] != b'\xff\xd8' or raw[-2:] != b'\xff\xd9':
        raise ValueError('JPEG SOI/EOI missing')
    offset = 2
    dimensions = None
    while offset < len(raw):
        if raw[offset] != 255:
            raise ValueError('JPEG marker expected')
        while raw[offset] == 255:
            offset += 1
        marker = raw[offset]
        offset += 1
        if marker == 0xd9:
            if offset != len(raw) or dimensions is None:
                raise ValueError('Unexpected JPEG EOI')
            return dimensions
        if marker in (0xd8, 0, 0x01) or 0xd0 <= marker <= 0xd7:
            raise ValueError('Unexpected JPEG marker')
        if offset + 2 > len(raw):
            raise ValueError('JPEG segment truncated')
        length = struct.unpack_from('>H', raw, offset)[0]
        if length < 2 or offset + length > len(raw):
            raise ValueError('JPEG segment length invalid')
        payload = raw[offset + 2:offset + length]
        if marker in (0xc0, 0xc1, 0xc2):
            if len(payload) < 6 or payload[0] != 8:
                raise ValueError('Unsupported JPEG precision')
            height, width = struct.unpack_from('>HH', payload, 1)
            if min(width, height) < 1 or payload[5] not in (1, 3):
                raise ValueError('JPEG dimensions/components invalid')
            if len(payload) != 6 + payload[5] * 3:
                raise ValueError('JPEG component descriptors invalid')
            if dimensions is not None:
                raise ValueError('Multiple JPEG frame markers')
            dimensions = (width, height)
        offset += length
        if marker == 0xda:
            if dimensions is None:
                raise ValueError('JPEG scan before frame')
            while offset < len(raw):
                if raw[offset] != 255:
                    offset += 1
                    continue
                start = offset
                while offset < len(raw) and raw[offset] == 255:
                    offset += 1
                if offset >= len(raw):
                    raise ValueError('JPEG scan truncated')
                mark = raw[offset]
                if mark == 0 or 0xd0 <= mark <= 0xd7:
                    offset += 1
                    continue
                offset = start
                break
    raise ValueError('JPEG missing terminal EOI')


def ajpg_plain(raw: bytes) -> bytes:
    key = 100
    plain = bytearray()
    for cipher in raw:
        plain.append(cipher ^ (key >> 8))
        key = ((key + cipher) * 0xce6d + 0x58bf) & 65535
    if plain[:8] != b'\x07AJPG_EX' or len(plain) < 55:
        raise ValueError('Invalid AJPG_EX native header')
    return bytes(plain)


def png_contract(raw: bytes) -> dict:
    offset, header, packed = 8, None, bytearray()
    metadata = bytearray()
    seen_end = False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError('PNG chunk truncated')
        length = struct.unpack_from('>I', raw, offset)[0]
        kind = raw[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError('PNG chunk length invalid')
        payload = raw[offset + 8:offset + 8 + length]
        crc = struct.unpack_from('>I', raw, offset + 8 + length)[0]
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError('PNG CRC invalid')
        if kind == b'IHDR':
            if header is not None or offset != 8 or length != 13:
                raise ValueError('PNG IHDR invalid')
            header = payload
        elif kind == b'IDAT':
            if header is None:
                raise ValueError('PNG IDAT before IHDR')
            packed.extend(payload)
        elif kind == b'IEND':
            if length or end != len(raw):
                raise ValueError('PNG IEND invalid')
            seen_end = True
        elif kind in (b'pHYs', b'iCCP', b'cHRM'):
            if header is None or seen_end or (kind == b'pHYs' and length != 9) or (kind == b'cHRM' and length != 32):
                raise ValueError('Native PNG metadata invalid')
            metadata.extend(raw[offset:end])
        else:
            raise ValueError('Unreviewed PNG chunk ' + repr(kind))
        offset = end
    if not header or not packed or not seen_end:
        raise ValueError('PNG missing chunks')
    width, height, bits, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', header)
    if bits != 8 or color != 6 or compression or filtering or interlace:
        raise ValueError('Expected native RGBA8 noninterlaced PNG')
    if width < 1 or height < 1 or width * height > 16_777_216:
        raise ValueError('PNG dimensions exceed reviewed range')
    row_size = width * 4
    stream = zlib.decompressobj()
    scan = stream.decompress(bytes(packed), (row_size + 1) * height + 1)
    if not stream.eof or stream.unused_data or stream.unconsumed_tail or len(scan) != (row_size + 1) * height:
        raise ValueError('PNG decompressed size invalid')
    alpha, previous = bytearray(), bytearray(row_size)
    for y in range(height):
        start = y * (row_size + 1)
        method = scan[start]
        if method > 4:
            raise ValueError('PNG filter invalid')
        row = bytearray(scan[start + 1:start + 1 + row_size])
        for x in range(row_size):
            left = row[x - 4] if x >= 4 else 0
            up = previous[x]
            upper_left = previous[x - 4] if x >= 4 else 0
            if method == 1: value = left
            elif method == 2: value = up
            elif method == 3: value = (left + up) // 2
            elif method == 4:
                estimate = left + up - upper_left
                ds = (abs(estimate-left), abs(estimate-up), abs(estimate-upper_left))
                value = (left, up, upper_left)[ds.index(min(ds))]
            else: value = 0
            row[x] = (row[x] + value) & 255
        alpha.extend(row[3::4])
        previous = row
    return dict(codec='PNG', width=width, height=height, bit_depth=32,
                header_sha256=digest(header), alpha_sha256=digest(alpha),
                metadata_sha256=digest(metadata),
                alpha_contract='decoded RGBA8 alpha pixels')


def _legacy_inspect_texture(raw: bytes) -> dict:
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return png_contract(raw)
    if raw.startswith(bytes.fromhex('07e181')):
        plain = ajpg_plain(raw)
        color_size, mask_size = struct.unpack_from('<QQ', plain, 39)
        if min(color_size, mask_size) < 1 or 55 + color_size + mask_size != len(plain):
            raise ValueError('AJPG_EX stream lengths invalid')
        color, mask = plain[55:55 + color_size], plain[55 + color_size:]
        width, height = jpeg_dimensions(color)
        if jpeg_dimensions(mask) != (width, height):
            raise ValueError('AJPG_EX mask dimensions differ')
        return dict(codec='AJPG_EX', width=width, height=height, bit_depth=32,
                    header_sha256=digest(plain[:39]), alpha_sha256=digest(mask),
                    mask_size=mask_size, alpha_contract='exact original encoded JPEG mask plane')
    if len(raw) >= 18 and raw[1] == 0 and raw[2] == 2 and raw[16] == 32:
        width, height = struct.unpack_from('<HH', raw, 12)
        if min(width, height) < 1 or raw[17] & 0xc0:
            raise ValueError('Unsupported TGA dimensions/interleave')
        offset = 18 + raw[0]
        end = offset + width * height * 4
        if end > len(raw):
            raise ValueError('TGA pixels truncated')
        alpha = raw[offset + 3:end:4]
        return dict(codec='TGA', width=width, height=height, bit_depth=32,
                    header_sha256=digest(raw[:offset]), trailer_sha256=digest(raw[end:]),
                    alpha_sha256=digest(alpha), alpha_contract='exact original raw TGA alpha plane')
    raise ValueError('Texture codec outside reviewed scope')


def validate_replacement(before: bytes, after: bytes) -> dict:
    old, new = inspect_texture(before), inspect_texture(after)
    if old != new:
        mismatch = [key for key in old if old[key] != new.get(key)]
        raise ValueError('Native texture invariant changed: ' + ', '.join(mismatch))
    if before == after:
        raise ValueError('Texture unchanged')
    return new


def inspect_texture(raw: bytes) -> dict:
    if raw.startswith(b'BM'):
        if len(raw) < 54:
            raise ValueError('BMP header truncated')
        file_size, reserved, offset = struct.unpack_from('<III', raw, 2)
        dib, width, signed_height, planes, bits, compression, image_size = struct.unpack_from('<IiiHHII', raw, 14)
        height = abs(signed_height)
        if dib != 40 or planes != 1 or bits != 32 or compression != 0:
            raise ValueError('Expected native BITMAPINFOHEADER BMP32 BI_RGB')
        if width < 1 or height < 1 or width * height > 16_777_216 or reserved:
            raise ValueError('Unsupported BMP dimensions/reserved fields')
        if file_size != len(raw) or offset < 54 or offset > len(raw):
            raise ValueError('BMP file size/pixel offset invalid')
        pixel_size = width * height * 4
        if offset + pixel_size > len(raw) or image_size not in (0, pixel_size):
            raise ValueError('BMP pixel size invalid')
        end = offset + pixel_size
        return dict(codec='BMP32', width=width, height=height, bit_depth=32,
                    header_sha256=digest(raw[:offset]), trailer_sha256=digest(raw[end:]),
                    alpha_sha256=digest(raw[offset + 3:end:4]),
                    alpha_contract='exact original native BMP fourth-byte alpha plane',
                    top_down=signed_height < 0, pixel_offset=offset)
    if raw.startswith(b'\xff\xd8'):
        width, height = jpeg_dimensions(raw)
        offset = 2
        frame = None
        while offset < len(raw):
            while raw[offset] == 255:
                offset += 1
            marker = raw[offset]
            offset += 1
            if marker == 0xda:
                break
            length = struct.unpack_from('>H', raw, offset)[0]
            if marker in (0xc0, 0xc1, 0xc2):
                frame = bytes((marker,)) + raw[offset + 2:offset + length]
            offset += length
        if frame is None:
            raise ValueError('JPEG frame missing')
        return dict(codec='JPEG', width=width, height=height, bit_depth=24,
                    header_sha256=digest(frame), alpha_sha256=digest(b'\xff' * (width * height)),
                    alpha_contract='implicit fully opaque JPEG plane',
                    components=frame[6], precision=frame[1], frame_marker=frame[0],
                    frame_hex=frame.hex())
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return png_contract(raw)
    raise ValueError('Texture codec outside main HUD reviewed scope')
