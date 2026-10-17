"""Initial TI ORANGE transport only, recovered from unpacked 0x1cd0/0x2710.

Later counter-dependent wire alterations are intentionally outside this codec.
"""
import struct
from dataclasses import dataclass
from .binary import PacketError, Reader, Writer, uint

INITIAL_KEY=bytes.fromhex('50259f9a11913a09')

class InitialCipher:
    """One direction's state. S2C is inverse of native receiver, C2S of sender."""
    def __init__(self,direction,key=INITIAL_KEY):
        if direction not in ('S2C','C2S'): raise ValueError('Invalid direction')
        self.direction=direction
        if not isinstance(key,bytes) or len(key)!=8: raise PacketError("Expected8 key bytes")
        self.key=bytearray(key)

    def transform(self,payload,*,encrypt):
        data=bytes(payload)
        if not 1<=len(data)<=65533: raise PacketError('Invalid initial payload length')
        result=bytearray(); previous=0
        for i,value in enumerate(data):
            k=self.key[i%8 if self.direction=='S2C' else 7-i%8]
            out=value ^ k ^ previous
            result.append(out)
            previous=out if encrypt else value
        if self.direction=='S2C':
            n=(int.from_bytes(self.key[:4],'big')+len(data))&0xffffffff
            self.key[:4]=bytes(((n>>16)&255,(n>>8)&255,n&255,n>>24))
        else:
            n=int.from_bytes(bytes(self.key[i] for i in (0,2,1,3)),'big')
            self.key[:4]=((n+len(data))&0xffffffff).to_bytes(4,'little')
        return bytes(result)

def encode_initial_frame(payload,cipher):
    if cipher.direction=='S2C':
        from tio.localization import for_language
        payload=for_language(payload,getattr(cipher,'language','russian'))
    data=bytes(payload)
    if not 1<=len(data)<=65533: raise PacketError('Initial frame payload out of range')
    return struct.pack('<H',len(data)+2)+cipher.transform(data,encrypt=True)

class InitialFrameReader:
    """TCP split/coalescing support; invalid lengths poison this reader."""
    def __init__(self,cipher):
        self.cipher=cipher
        self.buffer=bytearray()
        self.failed=False

    def feed(self,data):
        if self.failed: raise PacketError('Reader failed; create a new session')
        self.buffer.extend(data)
        result=[]
        while len(self.buffer)>=2:
            length=int.from_bytes(self.buffer[:2],'little')
            if length<3:
                self.failed=True
                self.buffer.clear()
                raise PacketError('Invalid initial frame length')
            if len(self.buffer)<length: break
            payload=bytes(self.buffer[2:length]); del self.buffer[:length]
            result.append(self.cipher.transform(payload,encrypt=False))
        return result

    def finish(self):
        if self.buffer or self.failed: raise PacketError('Incomplete or invalid frame stream')

@dataclass(frozen=True)
class InitialChallenge:
    unknown_u8_01:int
    unknown_u32_01:int
    unknown_u8_02:int
    unknown_u32_02:int

def encode_initial_challenge(p):
    return Writer().u8(0).u8(p.unknown_u8_01).u32(p.unknown_u32_01).u8(p.unknown_u8_02).u32(p.unknown_u32_02).build()

def decode_initial_challenge(data):
    r=Reader(data)
    if r.u8()!=0: raise PacketError('Expected transport 00')
    p=InitialChallenge(r.u8(),r.u32(),r.u8(),r.u32()); r.finish(); return p

@dataclass(frozen=True)
class InitialReply:
    transformed_u32_01:int
    transformed_u32_02:int
    unknown_u32_03:int
    unknown_bytes:bytes

def decode_initial_reply(data):
    r=Reader(data)
    if r.u8()!=1: raise PacketError('Expected transport 01')
    p=InitialReply(r.u32(),r.u32(),r.u32(),r.read(3)); r.finish(); return p

def encode_initial_reply(p):
    tail=bytes(p.unknown_bytes)
    if len(tail)!=3: raise PacketError('Expected 3 opaque trailing bytes')
    return Writer().u8(1).u32(p.transformed_u32_01).u32(p.transformed_u32_02).u32(p.unknown_u32_03).build()+tail

def expected_reply_fields(challenge):
    uint(challenge.unknown_u32_01,32); uint(challenge.unknown_u32_02,32)
    shifted=((challenge.unknown_u32_02 ^ 0x158099e1)<<2)&0xffffffff
    return shifted,(shifted>>2)^challenge.unknown_u32_01

@dataclass(frozen=True)
class InitialCompletion:
    status:int
    unknown_u8_01:int
    unknown_u32_01:int|None=None

def encode_initial_completion(p):
    w=Writer().u8(2).u8(p.status).u8(p.unknown_u8_01)
    if p.status==0: w.u32(p.unknown_u32_01)
    elif p.unknown_u32_01 is not None: raise PacketError('Failure completion has no established u32')
    return w.build()

def decode_initial_completion(data):
    r=Reader(data)
    if r.u8()!=2: raise PacketError('Expected transport 02')
    status=r.u8(); unknown=r.u8()
    p=InitialCompletion(status,unknown,r.u32() if status==0 else None)
    r.finish();return p
