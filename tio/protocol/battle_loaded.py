"""Loading acknowledgement36 and member notification37, verified native."""
from .binary import Reader, Writer, PacketError


def encode_battle_load_end():
    """ti.exe7182c0 dispatch41 ->718138 changes loading state to3."""
    return b'\x41'


def validate_battle_loaded(packet):
    if packet != b'\x36':
        raise PacketError('Expected battle load completion36 without arguments')


def encode_member_loaded(character_id):
    return Writer().u8(0x37).u32(character_id).build()


def decode_member_loaded(packet):
    r=Reader(packet)
    if r.u8()!=0x37:
        raise PacketError('Expected battle member loaded37')
    character_id=r.u32()
    r.finish()
    return character_id
