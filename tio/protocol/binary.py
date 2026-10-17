"""Checked little-endian primitives confirmed in silver.dll 0x605d68/8c/b8."""
import struct


class PacketError(ValueError):
    pass


def uint(value: int, bits: int) -> int:
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise PacketError(f'Expected unsigned {bits}-bit integer')
    return value


class Reader:
    def __init__(self, data: bytes):
        self.data = bytes(data)
        self.offset = 0

    def read(self, size: int) -> bytes:
        if type(size) is not int or size < 0 or self.offset + size > len(self.data):
            raise PacketError('Truncated payload or invalid read size')
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack('<H', self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack('<I', self.read(4))[0]

    def finish(self):
        if self.offset != len(self.data):
            raise PacketError('Unexpected trailing bytes')


class Writer:
    def __init__(self):
        self.data = bytearray()

    def u8(self, value):
        self.data.extend(struct.pack('<B', uint(value, 8)))
        return self

    def u16(self, value):
        self.data.extend(struct.pack('<H', uint(value, 16)))
        return self

    def u32(self, value):
        self.data.extend(struct.pack('<I', uint(value, 32)))
        return self

    def build(self):
        return bytes(self.data)
