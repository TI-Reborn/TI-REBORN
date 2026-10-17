"""TI city catalog wire layouts, verified against original x86 readers.

Field names containing unknown/offset preserve unresolved semantics.
PetShopList 62 -> 8c3e2c; ItemShopList 74 -> 991b34;
ServiceShopList B1/03 -> 84e320. No purchase success is inferred here.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError, uint


@dataclass(frozen=True)
class ShopItem:
    unknown_u32_01: int
    unknown_u32_02: int
    item_id: int
    unknown_u32_03: int
    durability: int
    unknown_u8: int


def encode_item_shop(category: int, items: tuple[ShopItem, ...]) -> bytes:
    w = Writer().u8(0x74).u8(category).u16(len(items))
    for item in items:
        w.u32(item.unknown_u32_01).u32(item.unknown_u32_02).u16(item.item_id)
        w.u32(item.unknown_u32_03).u16(item.durability).u8(item.unknown_u8)
    return w.build()


def decode_item_shop(packet: bytes):
    r = Reader(packet)
    if r.u8() != 0x74:
        raise PacketError('Expected ItemShopList74')
    category = r.u8()
    items = tuple(ShopItem(r.u32(), r.u32(), r.u16(), r.u32(), r.u16(), r.u8())
                  for _ in range(r.u16()))
    r.finish()
    return category, items


@dataclass(frozen=True)
class HireCandidate:
    unknown_u32_01: int
    unknown_u32_02: int
    name: bytes
    unknown_u8: int
    optional_bytes: bytes | None
    stat_float_bits: tuple[int, ...]
    unknown_u16_01: int
    unknown_u8_02: int
    unknown_u8_03: int
    unknown_u16_02: int
    unknown_u16_03: int
    unknown_u32_03: int

    @property
    def candidate_id(self):
        """Reader+100 -> UI column0 -> selected ID passed to request63."""
        return self.unknown_u32_01

    @property
    def resource_type(self):
        """Reader+104 -> localization pe0N (male/female/dog type). Not price."""
        return self.unknown_u32_02

    @property
    def price_credits(self):
        """Reader+194 -> column7; constructor8ac118 labels it m248 (Price)."""
        return self.unknown_u32_03


def encode_pet_shop(candidates: tuple[HireCandidate, ...]) -> bytes:
    w = Writer().u8(0x62).u16(len(candidates))
    for c in candidates:
        if not isinstance(c.name, bytes) or b'\0' in c.name or len(c.name) > 255:
            raise PacketError('Expected CString name up to255 bytes')
        if len(c.stat_float_bits) != 16:
            raise PacketError('Expected16 raw float32 fields')
        if c.optional_bytes is not None and (not isinstance(c.optional_bytes, bytes) or len(c.optional_bytes) != 6):
            raise PacketError('Optional branch contains6 bytes')
        w.u32(c.unknown_u32_01).u32(c.unknown_u32_02)
        w.data.extend(c.name + b'\0')
        w.u8(c.unknown_u8).u8(int(c.optional_bytes is not None))
        if c.optional_bytes is not None:
            w.data.extend(c.optional_bytes)
        for bits in c.stat_float_bits:
            w.u32(bits)
        w.u16(c.unknown_u16_01).u8(c.unknown_u8_02).u8(c.unknown_u8_03)
        w.u16(c.unknown_u16_02).u16(c.unknown_u16_03).u32(c.unknown_u32_03)
    return w.build()


def decode_pet_shop(packet: bytes):
    r = Reader(packet)
    if r.u8() != 0x62:
        raise PacketError('Expected PetShopList62')
    candidates = []
    for _ in range(r.u16()):
        first, second = r.u32(), r.u32()
        name = bytearray()
        while (char := r.u8()) != 0:
            name.append(char)
            if len(name) > 255:
                raise PacketError('Name exceeds native shortstring limit')
        kind = r.u8()
        present = r.u8()
        if present not in (0, 1):
            raise PacketError('Noncanonical optional flag')
        optional = r.read(6) if present else None
        candidates.append(HireCandidate(first, second, bytes(name), kind, optional,
            tuple(r.u32() for _ in range(16)), r.u16(), r.u8(), r.u8(),
            r.u16(), r.u16(), r.u32()))
    r.finish()
    return tuple(candidates)


@dataclass(frozen=True)
class ServiceOption:
    unknown_u8: int
    unknown_u64: int
    unknown_u32: int


@dataclass(frozen=True)
class ServiceOffer:
    unknown_u32: int
    unknown_u8: int
    options: tuple[ServiceOption, ...]


def encode_service_shop(offers: tuple[ServiceOffer, ...]) -> bytes:
    w = Writer().u8(0xb1).u8(3).u8(len(offers))
    for offer in offers:
        if not offer.options:
            raise PacketError('Zero-option offer has no native record body')
        w.u8(len(offer.options)).u32(offer.unknown_u32).u8(offer.unknown_u8)
        for option in offer.options:
            w.u8(option.unknown_u8)
            w.data.extend(uint(option.unknown_u64, 64).to_bytes(8, 'little'))
            w.u32(option.unknown_u32)
    return w.build()


def decode_service_shop(packet: bytes):
    r = Reader(packet)
    if (r.u8(), r.u8()) != (0xb1, 3):
        raise PacketError('Expected ServiceShopListB103')
    offers = []
    for _ in range(r.u8()):
        count = r.u8()
        if not count:
            raise PacketError('Zero-option entry unsupported')
        first, second = r.u32(), r.u8()
        options = tuple(ServiceOption(r.u8(), int.from_bytes(r.read(8), 'little'), r.u32())
                        for _ in range(count))
        offers.append(ServiceOffer(first, second, options))
    r.finish()
    return tuple(offers)
