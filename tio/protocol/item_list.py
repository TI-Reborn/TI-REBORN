"""Item-list request2F and verified empty ItemList30 response subset.

2F writer99002f writes u16count/u32IDs; C8/2F is a DIFFERENT packet.
30 writer63ce70 and reader63ce00: u32owner,u8unknown,u32count.
"""
from .binary import Reader,Writer,PacketError


def decode_item_list_request(packet):
    r=Reader(packet)
    if r.u8()!=0x2f:raise PacketError('Expected request2F')
    ids=tuple(r.u32() for _ in range(r.u16()))
    r.finish()
    return ids


def encode_empty_item_list(owner_id,unknown_u8=0):
    return Writer().u8(0x30).u32(owner_id).u8(unknown_u8).u32(0).build()


def decode_empty_item_list(packet):
    r=Reader(packet)
    if r.u8()!=0x30:raise PacketError('Expected ItemList30')
    owner,unknown=r.u32(),r.u8()
    if r.u32()!=0:raise PacketError('Nonempty inventory not supported yet')
    r.finish()
    return owner,unknown


from dataclasses import dataclass
from .binary import uint


@dataclass(frozen=True)
class ItemRecord:
    instance_id: int
    template_id: int
    unknown_bytes_01: bytes
    unknown_u32_01: int
    unknown_u8_01: int
    location_raw: int
    unknown_words: tuple[int, int, int]
    unknown_bytes_02: bytes
    optional_u32: int | None
    unknown_bytes_03: bytes

    @property
    def equipped(self):
        """Original getEquipped63c770; preserve byte value."""
        return self.unknown_u8_01

    @property
    def slot(self):
        return self.location_raw

    @property
    def client_slot(self):
        """Original ItemList consumer99083a..9908b4 normalization."""
        return 4 if self.slot in (0x800,0x1000,0x2000) else self.slot

    @property
    def count(self):
        return self.unknown_u32_01


def _write_record(w, item):
    for value,length in ((item.unknown_bytes_01,2),(item.unknown_bytes_02,4),(item.unknown_bytes_03,3)):
        if not isinstance(value,bytes) or len(value)!=length:
            raise PacketError('Incorrect fixed item byte block')
    if len(item.unknown_words)!=3:raise PacketError('Expected3 item words')
    w.u32(item.instance_id).u32(item.template_id)
    w.data.extend(item.unknown_bytes_01)
    w.u32(item.unknown_u32_01).u8(item.unknown_u8_01).u32(item.location_raw)
    for word in item.unknown_words:w.u16(word)
    w.data.extend(item.unknown_bytes_02)
    w.u8(0) # Optional managed name absent; wire format not yet implemented.
    w.u8(int(item.optional_u32 is not None))
    if item.optional_u32 is not None:w.u32(item.optional_u32)
    w.data.extend(item.unknown_bytes_03)
    w.u8(0) # Nested63b934 record absent.


def _read_record(r):
    instance,template=r.u32(),r.u32()
    first=r.read(2)
    unknown,byte,location=r.u32(),r.u8(),r.u32()
    words=tuple(r.u16() for _ in range(3))
    second=r.read(4)
    if r.u8()!=0:raise PacketError('Item name branch not yet implemented')
    flag=r.u8()
    if flag not in (0,1):raise PacketError('Noncanonical optional flag')
    optional=r.u32() if flag else None
    tail=r.read(3)
    if r.u8()!=0:raise PacketError('Nested item branch not yet implemented')
    return ItemRecord(instance,template,first,unknown,byte,location,words,second,optional,tail)


def encode_item_list(owner_id,items,unknown_u8=0):
    w=Writer().u8(0x30).u32(owner_id).u8(unknown_u8).u32(len(items))
    for item in items:_write_record(w,item)
    if len(w.data)>65533:raise PacketError('ItemList exceeds frame payload limit')
    return w.build()


def decode_item_list(packet):
    r=Reader(packet)
    if r.u8()!=0x30:raise PacketError('Expected ItemList30')
    owner,unknown,count=r.u32(),r.u8(),r.u32()
    if count>(len(packet)-r.offset)//35:raise PacketError('Truncated item records')
    items=tuple(_read_record(r) for _ in range(count))
    r.finish()
    return owner,items,unknown
