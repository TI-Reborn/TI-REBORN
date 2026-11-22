"""Requests to hire, dismiss or rename a roster member."""
from .binary import Reader, Writer, PacketError

PAID_PET_RENAME = b'\xb9\x06'


def encode_hire_request(candidate_id):
    return Writer().u8(0x63).u32(candidate_id).build()


def decode_hire_request(packet):
    r=Reader(packet)
    if r.u8()!=0x63:raise PacketError('Expected hire request63')
    candidate_id=r.u32()
    r.finish()
    return candidate_id


def encode_dismiss_request(pet_id):
    return Writer().u8(0x64).u32(pet_id).build()


def decode_dismiss_request(packet):
    r=Reader(packet)
    if r.u8()!=0x64:raise PacketError('Expected dismiss request64')
    pet_id=r.u32();r.finish()
    return pet_id


def encode_pet_deleted(pet_id):
    return Writer().u8(0x65).u32(pet_id).build()


def decode_paid_rename(packet: bytes) -> tuple[int, str]:
    if not packet.startswith(PAID_PET_RENAME) or not 10 <= len(packet) <= 23:
        raise PacketError('Некорректный запрос смены имени')
    reader = Reader(packet)
    reader.read(2)
    pet_id = reader.u32()
    raw_name = reader.read(len(packet) - 7)
    if not pet_id or b'\0' in raw_name or reader.u8() != 0:
        raise PacketError('Некорректный запрос смены имени')
    try:
        return pet_id, raw_name.decode('cp1251')
    except UnicodeDecodeError as exc:
        raise PacketError('Некорректный запрос смены имени') from exc
