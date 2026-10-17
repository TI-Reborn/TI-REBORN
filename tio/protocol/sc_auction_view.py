"""Explicit emulator F8/v1 snapshots for the dormant original SC GUI.

This is a new protocol, not a recovered historical BD receive ABI. The original
RTTI proves TAuctionLot=88, history=24 and prize=12 bytes. Managed pointers are
always zero on the wire; the checked client receiver allocates them through the
original Delphi RTL. Stock BD requests continue to be sent by native callbacks.
"""
import math
import struct
import time
from .binary import Reader, Writer, PacketError
from .item_list import decode_item_list

MAX_ROWS = 200
MAX_PRIZES = 32
MAX_TEXT = 256
MAX_PACKET = 65533  # Two-byte total-length prefix belongs to the transport.
LOT_SIZE = 88
HISTORY_SIZE = 24
PRIZE_SIZE = 12
DAY_ZERO = 25569.0  # 1970-01-01 minus Delphi 1899-12-30, in days.
HISTORY_ACTIONS = {'created': 1, 'closed': 2, 'bid': 4, 'claim': 7}


def datetime_days(unix_seconds):
    value = DAY_ZERO + float(unix_seconds) / 86400
    if not math.isfinite(value) or not 30000 <= value <= 100000:
        raise PacketError('Invalid SC calendar date')
    return value


def _integer(value, *, positive=False, maximum=0x7fffffff):
    if type(value) is not int or not int(positive) <= value <= maximum:
        raise PacketError('Invalid SC integer')
    return value


def _boolean(value):
    if type(value) is not bool: raise PacketError('Invalid SC boolean')
    return int(value)


def _text(value):
    if not isinstance(value, str) or '\0' in value or len(value) > MAX_TEXT:
        raise PacketError('Invalid SC text')
    # The original character-at-a-time wide-string reader supports BMP units.
    if any(0xd800 <= ord(c) <= 0xdfff or ord(c) > 0xffff for c in value):
        raise PacketError('SC text must contain BMP characters')
    return value.encode('utf-16le') + b'\0\0'


def _read_text(r):
    data = bytearray()
    for _ in range(MAX_TEXT + 1):
        unit = r.read(2)
        if unit == b'\0\0':
            try: value = data.decode('utf-16le')
            except UnicodeError as error: raise PacketError('Invalid SC text') from error
            _text(value); return value
        data.extend(unit)
    raise PacketError('SC text too long')


def _packet(w):
    data = w.build()
    if len(data) > MAX_PACKET: raise PacketError('SC snapshot exceeds transport bound')
    return data


def _header(op): return Writer().u8(0xf8).u8(1).u8(op)


def encode_clear(): return _header(0).build()


def lot_view(lot, *, bidder_name='', personal=False, notes='', group=None, now=None):
    """Project a store row; callers resolve public names, never publish owners.

    Group strings are exact original tab-filter keys. The explicit offer policy
    puts enhanced equipment in expensive lots, other prizes in fun lots.
    Original runtime base_duration is remaining milliseconds, while duration is
    a client tick deadline when ac490d is set. The receiver aligns that deadline
    locally. Start_date is Delphi calendar UTC;
    the caller may supply native_date explicitly after client clock alignment.
    """
    _, items, _ = decode_item_list(lot['item_packet'])
    prizes = tuple((i.template_id, i.count, i.unknown_bytes_03[0]) for i in items)
    expensive = any(p[2] > 0 for p in prizes)
    currency = 0 if lot['currency'] == 'credits' else 1 if lot['currency'] == 'gold' else -1
    if currency < 0: raise PacketError('Invalid SC currency')
    if group is None:
        group = ('Дорогой' if expensive else 'Фановый') + (' за кредиты' if currency == 0 else ' за золото')
    state = lot['state']
    if state not in ('active', 'won', 'delivered', 'unsold', 'expired'):
        raise PacketError('Invalid SC state')
    remaining = max(0, lot['ends'] - (int(time.time()) if now is None else now)) * 1000
    return dict(id=lot['id'], resource_id=0, state=1 if state == 'active' else 2,
        currency=currency, start_price=lot['start_price'], price=lot['price'],
        real_price=lot['price'], fee=lot['fee'], step=lot['step'],
        start_date=lot.get('native_date', datetime_days(lot['started'])),
        base_duration=remaining, duration=remaining,
        extension=lot['extension'] * 1000, notes=notes, name=bidder_name,
        personal=personal, bought=state in ('delivered', 'expired', 'unsold'),
        group=group, weight=0.0, weight_change=False,
        can_bot=bool(lot['automatic']), discount=0, prizes=prizes)


def _lot_record(row):
    raw = bytearray(LOT_SIZE)
    struct.pack_into('<II', raw, 0, _integer(row['id'], positive=True), _integer(row.get('resource_id', 0)))
    state, currency = row['state'], row['currency']
    if state not in (1, 2) or currency not in (0, 1): raise PacketError('Invalid SC state/currency')
    raw[8:10] = bytes((state, currency))
    for offset, key in ((12,'start_price'),(16,'price'),(20,'real_price'),(24,'fee'),(28,'step'),
                        (40,'base_duration'),(44,'duration'),(48,'extension')):
        struct.pack_into('<I', raw, offset, _integer(row[key]))
    date = row['start_date']
    if not math.isfinite(date) or not 30000 <= date <= 100000: raise PacketError('Invalid SC date')
    struct.pack_into('<d', raw, 32, date)
    raw[60], raw[61] = _boolean(row['personal']), _boolean(row['bought'])
    weight = row.get('weight', 0.0)
    if not math.isfinite(weight) or not 0 <= weight <= 100000: raise PacketError('Invalid SC weight')
    struct.pack_into('<f', raw, 68, weight)
    raw[72], raw[73] = _boolean(row['weight_change']), _boolean(row['can_bot'])
    struct.pack_into('<i', raw, 76, _integer(row.get('discount', 0)))
    return bytes(raw)


def encode_catalogue(rows):
    rows = tuple(rows)
    if len(rows) > MAX_ROWS or len({row['id'] for row in rows}) != len(rows):
        raise PacketError('Invalid SC catalogue count/duplicate ID')
    w = _header(1).u16(len(rows))
    for row in rows:
        w.data.extend(_lot_record(row))
        for key in ('notes', 'name', 'group'): w.data.extend(_text(row[key]))
        prizes = tuple(row['prizes'])
        if not 1 <= len(prizes) <= MAX_PRIZES: raise PacketError('Invalid SC prize count')
        w.u16(len(prizes))
        for template, count, enhance in prizes:
            w.data.extend(struct.pack('<IIB3x', _integer(template, positive=True),
                _integer(count, positive=True), _integer(enhance, maximum=27)))
    return _packet(w)


def history_view(row, *, public_name='', currency=0):
    action = HISTORY_ACTIONS.get(row['action'])
    if action is None: return None  # Ledger-only bot reservations/refunds have no original GUI action.
    return dict(date=datetime_days(row['occurred']), action=action, name=public_name,
                amount=row['amount'], automatic=bool(row['automatic']), currency=currency)


def encode_history(lot, rows, *, page=1, pages=1, remaining_ms=0):
    rows = tuple(rows)
    if len(rows) > MAX_ROWS: raise PacketError('Too many SC history rows')
    if not 1 <= page <= pages <= 65535: raise PacketError('Invalid SC history page')
    w = _header(2).u32(_integer(lot, positive=True)).u16(page).u16(pages).u32(_integer(remaining_ms)).u16(len(rows))
    for row in rows:
        if row['action'] not in (1,2,4,5,6,7,9) or row['currency'] not in (0,1):
            raise PacketError('Invalid SC history action/currency')
        date = row['date']
        if not math.isfinite(date) or not 30000 <= date <= 100000: raise PacketError('Invalid SC history date')
        raw = bytearray(HISTORY_SIZE); struct.pack_into('<d', raw, 0, date)
        raw[8] = row['action']; struct.pack_into('<i', raw, 16, _integer(row['amount']))
        raw[20], raw[21] = _boolean(row['automatic']), row['currency']
        w.data.extend(raw); w.data.extend(_text(row['name']))
    return _packet(w)


def encode_bot(lot, fee, from_price, to_price, bids):
    # Original bot form has no currency field; fee displays only a number.
    w = _header(3)
    for index, value in enumerate((lot, fee, from_price, to_price, bids)):
        w.u32(_integer(value, positive=index == 0))
    return w.build()


def encode_claim(lot, price, currency, expires_at, *, can_pay):
    if currency not in (0,1): raise PacketError('Invalid SC claim currency')
    w = _header(4).u32(_integer(lot, positive=True)); w.data.extend(struct.pack('<d', datetime_days(expires_at)))
    return w.u32(_integer(price)).u8(currency).u8(_boolean(can_pay)).build()


def decode(packet):
    """Review/test decoder; DLL performs its own bounded validation first."""
    if len(packet) > MAX_PACKET: raise PacketError('SC packet too large')
    r = Reader(packet)
    if (r.u8(), r.u8()) != (0xf8, 1): raise PacketError('Expected SC F8/v1')
    op = r.u8(); result = []
    if op == 0: result = ()
    elif op == 1:
        n = r.u16()
        if n > MAX_ROWS: raise PacketError('Too many SC rows')
        ids = set()
        for _ in range(n):
            raw = r.read(LOT_SIZE); ident = struct.unpack_from('<I', raw)[0]
            if ident == 0 or ident in ids or any(raw[at:at+4] != bytes(4) for at in (52,56,64,80)):
                raise PacketError('Invalid SC identity/pointer')
            ids.add(ident)
            values = tuple(_read_text(r) for _ in range(3)); count = r.u16()
            if not 1 <= count <= MAX_PRIZES: raise PacketError('Invalid SC prize count')
            prize_bytes=tuple(r.read(PRIZE_SIZE) for _ in range(count))
            if any(prize[9:]!=bytes(3) for prize in prize_bytes): raise PacketError('Invalid SC prize padding')
            prizes = tuple(struct.unpack('<IIB3x', prize) for prize in prize_bytes)
            reconstructed = dict(id=ident, resource_id=struct.unpack_from('<I',raw,4)[0], state=raw[8],currency=raw[9],
                start_date=struct.unpack_from('<d',raw,32)[0], personal=bool(raw[60]),bought=bool(raw[61]),
                weight=struct.unpack_from('<f',raw,68)[0],weight_change=bool(raw[72]),can_bot=bool(raw[73]),
                discount=struct.unpack_from('<i',raw,76)[0])
            for offset,key in ((12,'start_price'),(16,'price'),(20,'real_price'),(24,'fee'),(28,'step'),
                               (40,'base_duration'),(44,'duration'),(48,'extension')):
                reconstructed[key]=struct.unpack_from('<I',raw,offset)[0]
            if any(raw[at]>1 for at in (60,61,72,73)) or _lot_record(reconstructed)!=raw:
                raise PacketError('Invalid SC lot record')
            for template,units,enhance in prizes:
                _integer(template,positive=True);_integer(units,positive=True);_integer(enhance,maximum=27)
            result.append((raw, values, prizes))
    elif op == 2:
        lot, page, pages, remaining, n = r.u32(), r.u16(), r.u16(), r.u32(), r.u16()
        if not lot or not 1 <= page <= pages or n > MAX_ROWS: raise PacketError('Invalid SC history header')
        for _ in range(n):
            raw = r.read(HISTORY_SIZE)
            date=struct.unpack_from('<d',raw)[0]
            if (raw[9:16]!=bytes(7) or raw[22:24]!=bytes(2) or raw[8]>9 or raw[20]>1 or raw[21]>1
                or not math.isfinite(date) or not 30000<=date<=100000):
                raise PacketError('Invalid SC history record')
            _integer(struct.unpack_from('<i',raw,16)[0])
            result.append((raw, _read_text(r)))
        result = (lot, page, pages, remaining, tuple(result))
    elif op == 3:
        result=tuple(r.u32() for _ in range(5))
        for index,value in enumerate(result):_integer(value,positive=index==0)
    elif op == 4:
        result=(r.u32(),struct.unpack('<d',r.read(8))[0],r.u32(),r.u8(),r.u8())
        _integer(result[0],positive=True);_integer(result[2])
        if not math.isfinite(result[1]) or not 30000<=result[1]<=100000 or result[3]>1 or result[4]>1:
            raise PacketError('Invalid SC claim fields')
    else: raise PacketError('Unknown SC view operation')
    r.finish(); return op, tuple(result)
