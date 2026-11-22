"""B9/01 manifest from SILVER 9d070c/9d0408; token semantics unconfirmed."""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

MAX_COMPRESSED_SIZE = 50_000


@dataclass(frozen=True)
class SharedConfigEntry:
    name_bytes: bytes
    comparison_value: int


def encode_shared_config_set(entries):
    entries = tuple(entries)
    w = Writer().u8(0xb9).u8(1).u8(len(entries))
    for entry in entries:
        name = entry.name_bytes
        if not isinstance(name, bytes) or b'\0' in name or len(name) > 255:
            raise PacketError('Expected raw CString up to 255 bytes without NUL')
        w.data.extend(name + b'\0')
        w.u32(entry.comparison_value)
    return w.build()


def decode_shared_config_set(data):
    r = Reader(data)
    if r.u8() != 0xb9 or r.u8() != 1:
        raise PacketError('Expected B9/01 SharedConfigSet')
    entries = []
    for _ in range(r.u8()):
        name = bytearray()
        while (value := r.u8()) != 0:
            name.append(value)
            if len(name) > 255:
                raise PacketError('CString exceeds 255 bytes')
        entries.append(SharedConfigEntry(bytes(name), r.u32()))
    r.finish()
    return tuple(entries)


@dataclass(frozen=True)
class SharedConfigData:
    name_bytes: bytes
    decompressed_size: int
    compressed_bytes: bytes


def encode_shared_config_data(value):
    # 50000 is the caller's buffer capacity; the native copy does not enforce it.
    name = value.name_bytes
    if not isinstance(name, bytes) or b'\0' in name or len(name) > 255:
        raise PacketError('Expected raw CString up to 255 bytes without NUL')
    if not isinstance(value.compressed_bytes, bytes) or len(value.compressed_bytes) > MAX_COMPRESSED_SIZE:
        raise PacketError('Compressed config exceeds native buffer capacity')
    w = Writer().u8(0xb9).u8(3)
    w.data.extend(name+b'\0')
    w.u32(value.decompressed_size).u32(len(value.compressed_bytes))
    w.data.extend(value.compressed_bytes)
    return w.build()


def decode_shared_config_data(data):
    r = Reader(data)
    if r.u8() != 0xb9 or r.u8() != 3:
        raise PacketError('Expected B9/03 SharedConfig')
    name = bytearray()
    while (value := r.u8()) != 0:
        name.append(value)
        if len(name) > 255:
            raise PacketError('CString exceeds 255 bytes')
    decompressed_size, compressed_size = r.u32(), r.u32()
    if compressed_size > MAX_COMPRESSED_SIZE:
        raise PacketError('Compressed config exceeds native buffer capacity')
    result = SharedConfigData(bytes(name), decompressed_size, r.read(compressed_size))
    r.finish()
    return result
