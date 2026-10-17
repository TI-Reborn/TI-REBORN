"""FB/v1 cosmetic rain extension; independent of the F7 item snapshot."""
from .binary import Reader,Writer,PacketError
MAX_CELLS=4096


def encode_weather(rain,thunder,cells):
    cells=tuple(cells)
    if type(rain) is not bool or len(cells)>MAX_CELLS or len(set(cells))!=len(cells):raise PacketError('Invalid weather snapshot')
    if not rain and (thunder or cells):raise PacketError('Dry weather must be empty')
    w=Writer().u8(0xfb).u8(1).u8(int(rain)).u32(thunder).u16(len(cells))
    for x,y in cells:
        if any(type(n) is not int or not 0<=n<255 for n in (x,y)):raise PacketError('Invalid rain cell')
        w.u8(x).u8(y)
    return w.build()


def decode_weather(packet):
    r=Reader(packet)
    if (r.u8(),r.u8())!=(0xfb,1):raise PacketError('Unsupported weather snapshot')
    flag=r.u8();thunder=r.u32();count=r.u16()
    if flag not in (0,1) or count>MAX_CELLS:raise PacketError('Invalid weather header')
    cells=tuple((r.u8(),r.u8()) for _ in range(count));r.finish()
    encode_weather(bool(flag),thunder,cells)
    return bool(flag),thunder,cells
