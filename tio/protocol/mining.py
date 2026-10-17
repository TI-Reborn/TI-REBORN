"""Original silver.dll net3_Checkpoint835108 and its B0 serializers."""
import struct
from .binary import Reader,Writer,PacketError


def occurrence(identity,x,y,installed,initial,left,extracted,carried=0):
    # RECV_BattleOccurrenceStatus83481c; the last four fields map POccurrence.
    return (Writer().u8(0xb0).u8(0x16).u32(identity).u8(x).u8(y).u8(int(bool(installed)))
            .u32(initial).u32(left).u32(extracted).u32(carried).build())


def player_state(*,can_raid=True,can_defend=False,miners=0,defenders=0,raiders=0,waiting_defenders=0,waiting_raiders=0):
    # 834aa4 reads two flags and five signed16 counts (state offsets c,8,4,10,14).
    # 81541c -> button_raid(acee5c), defense(acee58); mining has no flag.
    return struct.pack('<BBBB5h',0xb0,0x1a,can_raid,can_defend,miners,defenders,raiders,waiting_defenders,waiting_raiders)


def price(value):
    return struct.pack('<BBfB',0xb0,0x20,value,0)


def price_history(values=()):
    if len(values)>32767:raise PacketError('Too many price history records')
    return b'\xb0\x1f'+struct.pack('<h',len(values))+b''.join(struct.pack('<4f',*v) for v in values)


def decode_pickup(packet):
    r=Reader(packet)
    if r.read(2)!=b'\xb0\x15':raise PacketError('Expected drill pickup B0/15')
    actor,x,y,amount=r.u32(),r.u8(),r.u8(),r.u32();r.finish()
    return actor,x,y,amount


def battle_state(enabled):
    # Native 9622C8 reads exactly one bool into AC6590.
    return bytes((0xb2,0x0a,int(bool(enabled))))


def can_quit(enabled):
    # Native 95E3A0 reads one byte (==1) and updates the CanQuit UI flag.
    return bytes((0xb2,0x16,int(bool(enabled))))
