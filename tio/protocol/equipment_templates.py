"""Original C5 equipment templates (silver.dll 92ec28, 92ee38, 646328).

List/save names use UTF-16Z; the generated view record uses length-prefixed
UTF-8. Gear uses instance IDs, whereas supplies use template IDs and counts.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError

GEAR_SLOTS = {0: 16, 2: 128, 4: 1, 5: 4, 6: 8}


def read_name(r):
    data = bytearray()
    while (part := r.read(2)) != b'\0\0':
        data.extend(part)
        if len(data) > 256:
            raise PacketError('Template name too long')
    return data.decode('utf-16le')


def wide_name(name):
    if not isinstance(name, str) or '\0' in name or len(name.encode('utf-16le')) > 256:
        raise PacketError('Invalid template name')
    return name.encode('utf-16le') + b'\0\0'


@dataclass(frozen=True)
class Element:
    object_id: int = 0
    item_id: int = 0
    count: int = 0
    setting: int = 0
    enhancement: int = 0
    damage: int = 0
    durability: int = 0
    maximum: int = 0


@dataclass(frozen=True)
class Template:
    name: str
    level: int
    npc_type: int
    remove_extra: int
    elements: tuple[Element, ...]


def signed(value):
    return value if value < 128 else value - 256


def decode_request(packet):
    r = Reader(packet)
    if r.u8() != 0xc5:
        raise PacketError('Expected C5')
    sub = r.u8()
    if sub == 1:
        r.finish()
        return None, 0, 0, None
    if sub != 3:
        raise PacketError('Unknown template command')
    action, identity = r.u8(), r.u32()
    pet, template = 0, None
    if action in (0, 4, 5):
        pet = r.u32()
    elif action in (1, 3):
        name, level, kind, remove = read_name(r), r.u8(), r.u8(), r.u8()
        entries = []
        for index in range(7):
            if index in GEAR_SLOTS:
                entries.append(Element(object_id=r.u32(), setting=signed(r.u8())))
            else:
                item, count, damage, setting = r.u32(), r.u32(), r.u8(), signed(r.u8())
                entries.append(Element(item_id=item, count=count, damage=damage, setting=setting))
        for _ in range(r.u8()):
            item, count, damage, setting = r.u32(), r.u32(), r.u8(), signed(r.u8())
            entries.append(Element(item_id=item, count=count, damage=damage, setting=setting))
        template = Template(name, level, kind, remove, tuple(entries))
    elif action != 2:
        raise PacketError('Unknown template action')
    r.finish()
    return action, identity, pet, template


def encode_list(entries):
    w = Writer().u8(0xc5).u8(2).u16(len(entries))
    for identity, t in entries:
        w.u32(identity)
        w.data.extend(wide_name(t.name))
        w.u8(t.level).u8(t.npc_type)
    return w.build()


def encode_view(t):
    if not 7 <= len(t.elements) <= 262:
        raise PacketError('Template requires seven equipment elements')
    name = t.name.encode('utf-8')
    w = Writer().u8(0xc5).u8(8).u16(len(name))
    w.data.extend(name)
    w.u8(t.level).u8(t.npc_type).u8(t.remove_extra).u32(len(t.elements))
    for e in t.elements:
        if not -128 <= e.setting <= 127 or not -128 <= e.enhancement <= 127:
            raise PacketError('Invalid signed template field')
        w.u32(e.object_id).u32(e.item_id).u32(e.count)
        w.u8(e.setting & 255).u8(e.enhancement & 255).u8(e.damage)
        w.u16(e.durability).u16(e.maximum)
    return w.build()


def encode_created(identity):
    return Writer().u8(0xc5).u8(6).u32(identity).build()


def encode_off(pet):
    return Writer().u8(0xc5).u8(4).u32(pet).u32(0).build()
