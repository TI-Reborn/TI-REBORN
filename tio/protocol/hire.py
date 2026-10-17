"""C2S63 selected candidate ID; original writer8c3c34, UI8ab9ae."""
from .binary import Reader, Writer, PacketError


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
