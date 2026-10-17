"""Original SILVER B7 mail ABI; selection/draft ids stay server authoritative.

The UI builders use UTF16 NUL strings; generated TANet body serializers use
u16 byte-length UTF16 strings. These distinct encodings are intentional.
"""
from dataclasses import dataclass
import struct

from .binary import Reader,Writer,PacketError


def _cstring(w,value):
    if not isinstance(value,bytes) or b'\0' in value or len(value)>255:
        raise PacketError('Expected bounded character-name CString')
    w.data.extend(value+b'\0')


def _read_cstring(r):
    out=bytearray()
    while (value:=r.u8()):
        out.append(value)
        if len(out)>255:raise PacketError('Character-name CString too long')
    return bytes(out)


def _wide(w,value,*,length=False):
    if not isinstance(value,str) or '\0' in value:raise PacketError('Invalid mail text')
    try:raw=value.encode('utf-16le')
    except UnicodeError as error:raise PacketError('Invalid UTF16 mail text') from error
    if len(raw)>16000:raise PacketError('Mail text exceeds wire policy')
    if length:w.u16(len(raw));w.data.extend(raw)
    else:w.data.extend(raw+bytes(2))


def _read_wide(r,*,length=False):
    if length:
        size=r.u16()
        if size%2 or size>16000:raise PacketError('Invalid UTF16 byte length')
        raw=r.read(size)
    else:
        raw=bytearray()
        while (word:=r.read(2))!=bytes(2):
            raw.extend(word)
            if len(raw)>16000:raise PacketError('Mail text exceeds wire policy')
    try:value=bytes(raw).decode('utf-16le')
    except UnicodeError as error:raise PacketError('Invalid UTF16 mail text') from error
    if '\0' in value:raise PacketError('Embedded NUL in mail text')
    return value


def _bool(r):
    value=r.u8()
    if value not in (0,1):raise PacketError('Expected canonical mail boolean')
    return bool(value)


def _header(r,sub):
    if (r.u8(),r.u8())!=(0xb7,sub):raise PacketError('Unexpected mail packet')


def _packet(w):
    result=w.build()
    if len(result)>65533:raise PacketError('Mail packet exceeds frame policy')
    return result


@dataclass(frozen=True)
class DraftRequest:
    kind:int
    recipient:bytes
    subject:str=''
    body:str=''
    items:tuple[tuple[int,int],...]=()


def encode_draft(request):
    w=Writer().u8(0xb7).u8(7).u8(request.kind)
    _cstring(w,request.recipient);_wide(w,request.subject);_wide(w,request.body)
    w.u16(len(request.items))
    for identity,count in request.items:w.u32(identity).u32(count)
    return _packet(w)


def decode_draft(packet):
    r=Reader(packet);_header(r,7)
    kind=r.u8();recipient=_read_cstring(r);subject=_read_wide(r);body=_read_wide(r)
    count=r.u16()
    if count>64:raise PacketError('Too many mail attachments')
    value=DraftRequest(kind,recipient,subject,body,tuple((r.u32(),r.u32()) for _ in range(count)))
    r.finish();return value


def encode_recalculate(identity=0,calculate=True):
    return Writer().u8(0xb7).u8(8).u8(int(calculate)).u32(identity).build()


def decode_recalculate(packet):
    r=Reader(packet);_header(r,8);value=(_bool(r),r.u32());r.finish();return value


@dataclass(frozen=True)
class MoneyRequest:
    recipient:bytes
    credits:int
    calculate:bool=True


def encode_money(request):
    w=Writer().u8(0xb7).u8(9).u8(2);_cstring(w,request.recipient)
    return w.u32(request.credits).u8(int(request.calculate)).build()


def decode_money(packet):
    r=Reader(packet);_header(r,9)
    if r.u8()!=2:raise PacketError('Unsupported mail template action')
    value=MoneyRequest(_read_cstring(r),r.u32(),_bool(r));r.finish();return value


def encode_page(page=1):return Writer().u8(0xb7).u8(0xd).u16(page).build()


def decode_page(packet):
    r=Reader(packet);_header(r,0xd);page=r.u16();r.finish();return page


@dataclass(frozen=True)
class ClaimItem:
    identity:int
    template:int
    count:int
    durability:tuple[int,int,int]=(0,0,0)
    enhance:int=0
    marker:bytes|None=None
    mark_time:int=0


@dataclass(frozen=True)
class BodyRequest:
    action:int
    identity:int
    subject:str=''
    body:str=''
    reserved:int=0
    items:tuple[ClaimItem,...]=()


def encode_body_request(request):
    w=Writer().u8(0xb7).u8(0xe).u8(request.action).u32(request.identity)
    if request.action==1:
        _wide(w,request.subject);_wide(w,request.body);w.u32(request.reserved).u16(len(request.items))
        for item in request.items:
            w.u32(item.identity).u16(item.template).u32(item.count)
            for value in item.durability:w.u16(value)
            w.u8(item.enhance).u8(int(item.marker is not None))
            if item.marker is not None:_cstring(w,item.marker);w.u32(item.mark_time)
    elif request.action not in (0,2):raise PacketError('Unsupported mail body action')
    return _packet(w)


def decode_body_request(packet):
    r=Reader(packet);_header(r,0xe);action=r.u8();identity=r.u32()
    if action==1:
        subject=_read_wide(r);body=_read_wide(r);reserved=r.u32();count=r.u16()
        if count>64:raise PacketError('Too many mail attachments')
        items=[]
        for _ in range(count):
            key=r.u32();template=r.u16();amount=r.u32();durability=tuple(r.u16() for _ in range(3));enhance=r.u8();marked=_bool(r)
            marker=_read_cstring(r) if marked else None;time=r.u32() if marked else 0
            items.append(ClaimItem(key,template,amount,durability,enhance,marker,time))
        value=BodyRequest(action,identity,subject,body,reserved,tuple(items))
    elif action in (0,2):value=BodyRequest(action,identity)
    else:raise PacketError('Unsupported mail body action')
    r.finish();return value


@dataclass(frozen=True)
class MailSummary:
    identity:int
    sender:str
    subject:str
    created:int
    attachments:int=0
    unread:bool=True
    kind:int=0


def encode_list(rows,*,pages=1,page=1):
    w=Writer().u8(0xb7).u8(0x79).u16(pages).u16(page).u16(len(rows))
    for row in rows:
        w.u32(row.identity);_wide(w,row.sender);_wide(w,row.subject)
        w.u32(row.created).u16(row.attachments).u8(int(row.unread)).u8(row.kind)
    return _packet(w)


def decode_list(packet):
    r=Reader(packet);_header(r,0x79);pages=r.u16();page=r.u16();count=r.u16()
    if count>1000:raise PacketError('Too many mail summaries')
    rows=tuple(MailSummary(r.u32(),_read_wide(r),_read_wide(r),r.u32(),r.u16(),_bool(r),r.u8()) for _ in range(count))
    r.finish();return pages,page,rows


@dataclass(frozen=True)
class PostItem:
    identity:int
    template:int
    count:int
    durability:tuple[int,int,int]=(0,0,0)
    enhance:int=0
    damage_enhance:int=0
    special_enhance:bool=False
    rented:bool=False
    marker:str|None=None
    mark_time:int=0


def _post_item(w,item):
    w.u32(item.identity).u32(item.template).u32(item.count)
    for value in item.durability:w.u16(value)
    w.u8(item.enhance).u8(item.damage_enhance).u8(int(item.special_enhance)).u8(int(item.marker is not None))
    if item.marker is not None:
        w.u8(int(item.rented));_wide(w,item.marker);w.u32(item.mark_time)


def _read_post_item(r):
    identity=r.u32();template=r.u32();count=r.u32();durability=tuple(r.u16() for _ in range(3))
    enhance=r.u8();damage=r.u8();special=_bool(r);marked=_bool(r)
    rented=_bool(r) if marked else False;marker=_read_wide(r) if marked else None;time=r.u32() if marked else 0
    return PostItem(identity,template,count,durability,enhance,damage,special,rented,marker,time)


@dataclass(frozen=True)
class MailBody:
    identity:int
    sender:str
    subject:str
    created:int
    lifetime_days:int
    unread:bool
    has_items:bool
    body:str
    price:int
    items:tuple[PostItem,...]=()


def encode_body(row):
    w=Writer().u8(0xb7).u8(0x7a).u32(row.identity)
    _wide(w,row.sender,length=True);_wide(w,row.subject,length=True)
    if type(row.created)is not int or not 0<=row.created<1<<63:raise PacketError('Invalid mail UTC timestamp')
    w.data.extend(struct.pack('<q',row.created));w.u32(row.lifetime_days).u8(int(row.unread)).u8(int(row.has_items))
    _wide(w,row.body,length=True);w.u32(row.price).u32(len(row.items))
    for item in row.items:_post_item(w,item)
    return _packet(w)


def decode_body(packet):
    r=Reader(packet);_header(r,0x7a);identity=r.u32();sender=_read_wide(r,length=True);subject=_read_wide(r,length=True)
    created=struct.unpack('<q',r.read(8))[0];days=r.u32();unread=_bool(r);has_items=_bool(r);body=_read_wide(r,length=True);price=r.u32();count=r.u32()
    if count>64:raise PacketError('Too many mail attachments')
    value=MailBody(identity,sender,subject,created,days,unread,has_items,body,price,tuple(_read_post_item(r) for _ in range(count)))
    r.finish();return value


def encode_notification(sender,subject,has_items=False):
    w=Writer().u8(0xb7).u8(0x74);_wide(w,sender);_wide(w,subject);w.u8(int(has_items));return _packet(w)


def decode_notification(packet):
    r=Reader(packet);_header(r,0x74);value=(_read_wide(r),_read_wide(r),_bool(r));r.finish();return value


@dataclass(frozen=True)
class PostWarehouseItem:
    identity:int
    sender:str
    subject:str
    created:int
    item:PostItem


def encode_post_warehouse(rows=()):
    w=Writer().u8(0xb7).u8(0x75).u32(len(rows))
    for row in rows:
        w.u32(row.identity);_wide(w,row.sender,length=True);_wide(w,row.subject,length=True)
        w.data.extend(struct.pack('<q',row.created));_post_item(w,row.item)
    return _packet(w)


def decode_post_warehouse(packet):
    r=Reader(packet);_header(r,0x75);count=r.u32()
    if count>1000:raise PacketError('Too many post warehouse items')
    rows=tuple(PostWarehouseItem(r.u32(),_read_wide(r,length=True),_read_wide(r,length=True),struct.unpack('<q',r.read(8))[0],_read_post_item(r)) for _ in range(count))
    r.finish();return rows
