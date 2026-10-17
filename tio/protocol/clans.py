"""Native clan packets, silver.dll 6e6690..6e7150 (see CLANS.md).

53 requests dissolution, not a member-list refresh. State is pushed by the
server on login and after changes. Names are ANSI, terminated by one zero.
"""
from .binary import Reader, Writer, PacketError


def string(reader, limit=64):
    value=bytearray()
    while (c:=reader.u8()):
        value.append(c)
        if len(value)>limit:raise PacketError('Слишком длинное название')
    return bytes(value)


def put_string(writer, value):
    if not isinstance(value,bytes) or b'\0' in value or len(value)>255:
        raise PacketError('Invalid clan string')
    writer.data.extend(value+b'\0')
    return writer


def decode_request(packet):
    r=Reader(packet);op=r.u8()
    if op==0x52:args=(string(r),)
    elif op==0x53:args=(r.u32(),)
    elif op in (0x5b,0x5f,0x99):args=(string(r,16),)
    elif op in (0x5d,0x31):args=(r.u8(),)
    elif op==0x98:args=(r.u32(),r.u32(),r.u8())
    elif op==0x60:args=()
    else:raise PacketError('Unknown clan operation')
    r.finish();return op,args


def encode_info(clan=None):
    w=Writer().u8(0x54).u32(clan['id'] if clan else 0)
    put_string(w,clan['name'] if clan else b'')
    put_string(w,clan['leader_name'] if clan else b'')
    w.u8(clan['level'] if clan else 0).u32(clan.get('crest_id',0) if clan else 0)
    w.u16(clan['capacity'] if clan else 0).u16(clan['capacity'] if clan else 0)
    w.u32(clan['influence'] if clan else 0).u8(0)
    return w.build()


def encode_members(members):
    members=tuple(members)
    if len(members)>255:raise PacketError('Too many clan members')
    w=Writer().u8(0x55).u8(len(members))
    for m in members:
        w.u32(m['id']);put_string(w,m['name'])
        w.u8(m['level']).u8(int(m.get('online',False))).u8(1 if m['leader'] else 0)
        w.u32(m['permissions']).u8(m['title']).u32(m['contribution']).u32(0)
    return w.build()


def encode_invitation(identity, name, clan_name):
    w=Writer().u8(0x5c).u32(identity)
    put_string(w,name);put_string(w,clan_name)
    return w.build()


def encode_join(identity):return Writer().u8(0x5e).u32(identity).build()
