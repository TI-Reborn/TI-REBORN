"""Original single-tournament C6 messages in silver.dll (0x80456c–0x806120)."""
import struct

from .arena import _name_write
from .binary import PacketError, Reader, Writer
from .ranked import decode_join

REGISTER = b'\xc6\x40\x01'
CANCEL = b'\xc6\x40\x00'
READY = b'\xc6\x41'
UNREADY = b'\xc6\x44'
BRACKET = b'\xc6\x53'
OPEN = b'\xc6\x51'


def decode_ready(packet: bytes) -> tuple[tuple[int, tuple[tuple[int, int], ...], int], ...]:
    if packet[:2] != READY or packet[2:4] not in (b'\0\0', b'\1\0', b'\2\0'):
        raise PacketError('Некорректная заявка на турнирный бой')
    return decode_join(b'\xc6\x21\0\0' + packet[4:])[1]


def bracket_request(packet: bytes) -> int:
    r = Reader(packet)
    if r.read(2) != BRACKET:
        raise PacketError('Ожидался запрос турнирной сетки')
    value = int.from_bytes(r.read(8), 'little')
    r.finish()
    return value


def encode_status(phase: int, milliseconds: int, *, registered: bool = False, participants: int = 0,
                  rounds: tuple[tuple[tuple[bytes, int], ...], ...] = ()) -> bytes:
    w = Writer().u8(0xc6).u8(0x39).u8(1).u8(phase)
    w.data.extend(struct.pack('<Q', max(milliseconds, 0)))
    w.u8(len(rounds))
    for rows in rounds:
        w.u8(len(rows))
        for name, status in rows:
            w.u8(status).u8(1)
            _name_write(w, name)
            w.u32(0).u32(0).u8(0)
    return w.u8(int(registered)).u32(participants).build()


def encode_bracket(event: int, rounds: tuple[tuple[tuple[bytes, int], ...], ...]) -> bytes:
    w = Writer().u8(0xc6).u8(0x55)
    w.data.extend(struct.pack('<Q', event))
    w.u32(0).u8(len(rounds))
    for stage, row in enumerate(rounds):
        w.u8(stage + 1).data.extend(bytes(16))
        w.u8(len(row))
        for slot, (name, status) in enumerate(row):
            _name_write(w, name)
            w.u8(status).u8(slot)
    return w.build()


def encode_battle(match: int, stage: int, teams: tuple[tuple[bytes, tuple[tuple[int, int], ...]], ...]) -> bytes:
    w = Writer().u8(0xc6).u8(0x45).u32(match).u8(stage).u8(0)
    for name, fighters in teams:
        w.u32(1)
        _name_write(w, name)
        w.data.extend(bytes(8))
        w.u32(len(fighters))
        for resource, rank in fighters:
            w.u32(resource).u32(rank)
    return w.build()


def encode_countdown(milliseconds: int) -> bytes:
    return b'\xc6\x50' + struct.pack('<Q', max(milliseconds, 0))
