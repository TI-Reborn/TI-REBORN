"""Original C6/32..38 party and C6/35,36 readers in Silver 7f70d0/7f84a8/7f78f8."""
from .binary import Reader,Writer,PacketError
from .friends import read_name

def text(r):
    size=r.u16()
    if size>200:raise PacketError('Invitation text too long')
    try:value=r.read(size*2).decode('utf-16le')
    except UnicodeError as error:raise PacketError('Invalid invitation text') from error
    if any(ord(c)<32 for c in value):raise PacketError('Invalid invitation text')
    return value

def decode(packet):
    r=Reader(packet)
    if r.u8()!=0xc6:raise PacketError('Expected TrueSkill party request')
    op=r.u8();value=None
    if op==0x32:value=(read_name(r),text(r))
    elif op==0x34:
        value=(r.u32(),r.u8())
        if not 0<=value[1]<=4:raise PacketError('Party soldier allocation must be 0..4')
    elif op==0x37:
        value=r.u8()
        if value not in (0,1):raise PacketError('Invalid invitation answer')
    elif op not in (0x33,0x38):raise PacketError('Unexpected TrueSkill party request')
    r.finish();return op,value

def invite(name,message=''):
    read_name(Reader(name+b'\0'))
    raw=message.encode('utf-16le');w=Writer().u8(0xc6).u8(0x35);w.data.extend(name+b'\0');w.u16(len(raw)//2);w.data.extend(raw);return w.build()

def snapshot(leader,members,tokens=0):
    """Members: wireID,name,level,crests,state,allocated,[(resource,rank,level,hp,maxhp,weapon1,weapon2)]."""
    w=Writer().u8(0xc6).u8(0x36).u32(leader).u32(len(members))
    if len(members)>4:raise PacketError('Party too large')
    for identity,name,level,crest,alliance,state,slots,pets in members:
        w.u32(identity);w.data.extend(name+b'\0');w.u32(level).u32(crest).u32(alliance).u8(state).u8(slots).u8(len(pets))
        for resource,rank,lvl,hp,maximum,weapon1,weapon2 in pets:
            w.u32(resource).u32(rank).u32(lvl).u32(hp).u16(maximum).u16(weapon1).u16(weapon2)
    return w.u16(tokens).build()
