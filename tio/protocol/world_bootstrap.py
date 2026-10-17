"""Confirmed SILVER18/1A wire layouts; unknown fields preserved."""
from dataclasses import dataclass
from .binary import Reader,Writer,PacketError


def encode_open_map_view():
    """Native EE state2: 88b29c ->85905c selects the global-map renderer.

    F0/97 clears the current town and its controls, but leaves a passive
    party member's town renderer selected. Send this after leaving the town
    and before projecting that member's map movement.
    """
    return Writer().u8(0xee).u16(2).build()


def encode_restore_city_controls():
    """Native EE state0 clears the map-view character state and chat controls.

    The separate F0/117 town-view command selects the town renderer.
    """
    return Writer().u8(0xee).u16(0).build()

@dataclass(frozen=True)
class SelectResult:
    status:int
    discarded_u32_01:int|None=None
    discarded_u32_02:int|None=None

def encode_select_result(p):
    w=Writer().u8(0x18).u8(p.status)
    if p.status==0:w.u32(p.discarded_u32_01).u32(p.discarded_u32_02)
    elif p.discarded_u32_01 is not None or p.discarded_u32_02 is not None:raise PacketError('Failure has no extra fields')
    return w.build()

def decode_select_result(data):
    r=Reader(data)
    if r.u8()!=0x18:raise PacketError('Expected18')
    status=r.u8();p=SelectResult(status,r.u32(),r.u32()) if status==0 else SelectResult(status)
    r.finish();return p

@dataclass(frozen=True)
class MyCharInfo:
    character_id:int
    name_bytes:bytes
    unknown_u16:int
    x_raw_u32:int
    y_raw_u32:int
    unknown_u32:int

def encode_mychar_info(p):
    if not isinstance(p.name_bytes,bytes) or b'\0' in p.name_bytes or len(p.name_bytes)>255:raise PacketError('Invalid CString')
    w=Writer().u8(0x1a).u32(p.character_id);w.data.extend(p.name_bytes+b'\0')
    return w.u16(p.unknown_u16).u32(p.x_raw_u32).u32(p.y_raw_u32).u32(p.unknown_u32).build()

def decode_mychar_info(data):
    r=Reader(data)
    if r.u8()!=0x1a:raise PacketError('Expected1A')
    ident=r.u32();name=bytearray()
    while (c:=r.u8())!=0:
        name.append(c)
        if len(name)>255:raise PacketError('CString exceeds255')
    p=MyCharInfo(ident,bytes(name),r.u16(),r.u32(),r.u32(),r.u32());r.finish();return p
