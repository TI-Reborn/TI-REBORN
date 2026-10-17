"""Early ORANGE mode1 challenge09/reply0A, not the complete game transport."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError

MODE1_KEY_MASK=bytes.fromhex('ac2a77993f3a51b4')

def derive_mode1_key(challenge_bytes):
    if not isinstance(challenge_bytes,bytes) or len(challenge_bytes)!=8:
        raise PacketError('Expected8 challenge bytes')
    return bytes(a^b for a,b in zip(challenge_bytes,MODE1_KEY_MASK))

def encode_mode1_challenge(challenge_bytes):
    derive_mode1_key(challenge_bytes)
    return b'\x09'+challenge_bytes

def decode_mode1_challenge(data):
    r=Reader(data)
    if r.u8()!=9: raise PacketError('Expected transport09')
    result=r.read(8);r.finish();return result

def encode_mode1_challenge_frame(challenge_bytes):
    # First mode1 frame is cleartext, cipher flag remains0 until its09 handler.
    return b'\x0b\x00'+encode_mode1_challenge(challenge_bytes)

@dataclass(frozen=True)
class Mode1Reply:
    previous_transport_u32: int
    completion_u32: int

def encode_mode1_reply(p):
    return Writer().u8(10).u32(p.previous_transport_u32).u32(p.completion_u32).build()

def decode_mode1_reply(data):
    r=Reader(data)
    if r.u8()!=10: raise PacketError('Expected transport0A')
    p=Mode1Reply(r.u32(),r.u32());r.finish();return p


def encode_mode1_completion(status):
    return Writer().u8(11).u8(status).build()

def decode_mode1_completion(data):
    r=Reader(data)
    if r.u8()!=11: raise PacketError('Expected transport0B')
    status=r.u8();r.finish();return status
