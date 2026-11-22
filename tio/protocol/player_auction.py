"""General player auction C8/08..0F, recovered from silver.dll 62d290..62e965.

Trade time is HOURS (8feb35..8feb5c), not a dropdown index.
Names are CP1251 C strings; descriptions are UTF-16LE C strings.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

BID = 0x0d
BUYOUT = 0x0e
CANCEL = 0x0f


def boolean(r):
    n = r.u8()
    if n not in (0, 1):
        raise PacketError('Invalid auction optional flag')
    return bool(n)


def wide(r, limit=1000):
    chunks = []
    for _ in range(limit + 1):
        part = r.read(2)
        if part == b'\0\0':
            try:
                return b''.join(chunks).decode('utf-16le')
            except UnicodeError as error:
                raise PacketError('Invalid auction description') from error
        chunks.append(part)
    raise PacketError('Auction description too long')


@dataclass(frozen=True)
class CreateLot:
    request: int
    items: tuple
    hours: int
    price: int
    step: int
    description: str
    buyout: int | None


def decode_create(packet):
    r = Reader(packet)
    if r.read(2) != b'\xc8\x0a':
        raise PacketError('Expected create auction lot')
    request, count = r.u32(), r.u32()
    if not 1 <= count <= 30:
        raise PacketError('A lot requires 1–30 item entries')
    items = tuple((r.u32(), r.u32()) for _ in range(count))
    hours, price, step = r.u8(), r.u32(), r.u32()
    description = wide(r)
    buyout = r.u32() if boolean(r) else None
    r.finish()
    if hours not in (12, 24, 48, 96, 168):
        raise PacketError('Unsupported auction duration')
    if not 0 < price <= 0x7fffffff or not 0 < step <= 0x7fffffff or (buyout is not None and not price <= buyout <= 0x7fffffff):
        raise PacketError('Invalid auction prices')
    if len(set(i for i, _ in items)) != count or any(not i or not n for i, n in items):
        raise PacketError('Invalid or duplicate auction items')
    return CreateLot(request, items, hours, price, step, description, buyout)


def decode_list(packet):
    r = Reader(packet)
    if r.read(2) != b'\xc8\x08':
        raise PacketError('Expected auction list request')
    kind, request = r.u32(), r.u32()
    ids, types, enhance, durability = (), (), None, None
    if boolean(r):
        count = r.u32()
        if count > 1000:
            raise PacketError('Too many item filters')
        ids = tuple(r.u32() for _ in range(count))
        count = r.u32()
        if count > 16:
            raise PacketError('Too many item type filters')
        types = tuple(r.u32() for _ in range(count))
        if boolean(r):
            enhance = (r.u8(), r.u8())
        if boolean(r):
            durability = (r.u8(), r.u8())
    order = (r.u32(), r.u32()) if boolean(r) else None
    page = r.u32()
    r.finish()
    if kind not in (0, 1) or any(t > 15 for t in types):
        raise PacketError('Invalid auction list filter')
    return kind, request, page, ids, types, enhance, durability, order


def decode_action(packet):
    r = Reader(packet)
    if r.u8() != 0xc8:
        raise PacketError('Expected auction action')
    op = r.u8()
    if op not in (BID, BUYOUT, CANCEL):
        raise PacketError('Unknown auction action')
    lot = r.u32()
    bid, index = (r.u32(), r.u32()) if op == BID else (None, None)
    r.finish()
    return op, lot, bid, index


def write_lot(w, row, items):
    w.u32(row['id']).u32(row['ends']).u32(row['starts'])
    w.data.extend(row['seller_name'].encode('cp1251')+b'\0')
    w.data.extend((row['description']+'\0').encode('utf-16le'))
    w.u32(row['price']).u32(row['step']).u8(int(row['buyout'] is not None))
    if row['buyout'] is not None:
        w.u32(row['buyout'])
    w.u32(len(items))
    for item in items:
        w.u32(item.template_id).u32(item.count).u16(item.unknown_words[0]).u16(item.unknown_words[1])
        for n in item.unknown_bytes_03:
            w.u8(n)
    w.u8(int(row['bidder'] is not None))
    if row['bidder'] is not None:
        w.data.extend(row['bidder_name'].encode('cp1251')+b'\0')
        w.u32(row['bid']).u32(row['bid_index'])
    w.u32(1 if row['state']=='active' else 2 if row['state']=='cancelled' else 3)


def encode_lots(request, page, pages, lots):
    w=Writer().u8(0xc8).u8(9).u32(request).u32(page).u32(pages).u32(len(lots))
    for row,items in lots:
        write_lot(w,row,items)
    if len(w.data)>65533:
        raise PacketError('Auction page exceeds transport frame')
    return w.build()


def encode_added(lots):
    w=Writer().u8(0xc8).u8(3).u32(len(lots))
    for row,items in lots:
        write_lot(w,row,items)
    return w.build()


def encode_settings(now, pledge_percent=5, *, heal_price=None,clan_warfare=False,mail=False,
                    enhancement: tuple[int,int,int] | None = None, tournament_free_entry: bool = False):
    """C8/37 full settings (651fec), retaining zero defaults for other fields.

    Alliance fees and Assault4 limits use the original C8/37 fields when the
    shared warfare handlers are present. Mail limits use native settings.
    """
    import math,struct
    if heal_price is None:
        from ..battle_recovery import CREDITS_PER_HP
        heal_price=CREDITS_PER_HP
    if not math.isfinite(heal_price) or heal_price<0:raise PacketError('Invalid treatment tariff')
    w=Writer().u8(0xc8).u8(0x37)
    w.data.extend(struct.pack('<f',heal_price))
    w.u8(0)  # external billing disabled
    if type(clan_warfare) is not bool:raise PacketError('Invalid clan warfare setting')
    values=(0,0,0) if enhancement is None else enhancement
    if (len(values)!=3 or any(type(value) is not int or not 0<=value<=100 for value in values)
            or values[0]>25):raise PacketError('Invalid enhancement settings')
    for value in (*values,0,0,0):
        w.u32(value)  # enhancement settings, mark price, empty helpers/sheriffs
    prices=(50_000,10_000,25_000,5_000,100_000,20_000) if clan_warfare else (0,)*6
    for value in prices:w.u32(value)
    if type(mail) is not bool:raise PacketError('Invalid mail setting')
    if mail:
        from ..mail import policy
        limits=policy()
        # Original RTTI fmailAdminAccess/fmailMaxMessageBodySize/TitleSize.
        w.u32(0).u32(limits['maximum_body_bytes']).u32(limits['maximum_subject_bytes'])
    else:
        for _ in range(3):w.u32(0)
    w.data.extend(struct.pack('<Q',now))
    w.u32(0).u8(0).u8(int(tournament_free_entry)).u8(1).u32(pledge_percent).u32(0)
    for value in ((4,4,3,1) if clan_warfare else (0,)*4):w.u32(value)
    return w.build()
