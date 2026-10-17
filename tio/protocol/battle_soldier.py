"""BattleSoldierAdd3B read layout (8c5044 through8c5aab).

Resource equipment class is external and must be supplied explicitly. Numeric
fields retain original callsites; float fields preserve their raw32-bit bits.
This packet is not a substitute for city PetInfo66 or full battle initialization.
"""
from dataclasses import dataclass
from .binary import Reader, Writer, PacketError, uint

# Original3B ->98f978 slot masks, not ItemList.location_raw semantics.
HUMAN_EQUIPMENT_FIELDS = {
    1:'0x8c525b', 2:'0x8c5281', 0x10:'0x8c52cf', 0x80:'0x8c52f5',
    4:'0x8c531b', 8:'0x8c5341', 0x400:'0x8c5367', 0x40000:'0x8c538d',
    0x80000:'0x8c53b3', 0x100000:'0x8c53d9', 0x200000:'0x8c53ff',
}


@dataclass(frozen=True)
class BattleSoldier:
    human_equipment: bool | str
    fields: dict[str, int | bytes]

    @property
    def soldier_id(self): return self.fields['0x8c5088']

    @property
    def owner_id(self): return self.fields['0x8c50ea']

    @property
    def level(self): return self.fields['0x8c5134']

    @property
    def position(self): return (self.fields['0x8c519b'], self.fields['0x8c51af'])

    @property
    def equipment_templates(self):
        if self.human_equipment is not True:
            raise PacketError('Equipment projection requires human profile')
        return {mask:self.fields[key] for mask,key in HUMAN_EQUIPMENT_FIELDS.items()}


# (controlling field, exact value); None means any nonzero value.
CONDITIONS = {
    **{key: ('0x6d0203', None) for key in
       ('0x6d0213','0x6d0221','0x6d022e','0x6d023c','0x6d024a','0x6d0258')},
    '0x8c58b8': ('0x8c5898', 1), '0x8c58d7': ('0x8c5898', 1),
    '0x8c5938': ('0x8c5918', 1), '0x8c5957': ('0x8c5918', 1),
    '0x8c59b2': ('0x8c5998', 1), '0x8c59c3': ('0x8c5998', 1),
    '0x8c5a02': ('0x8c59e8', 1), '0x8c5a13': ('0x8c59e8', 1),
    **{key: ('0x8c5831', None) for key in ('0x8c5a41','0x8c5a66','0x8c5a8b')},
}


def _enabled(key, fields):
    if key not in CONDITIONS:
        return True
    control, expected = CONDITIONS[key]
    if control not in fields:
        raise PacketError('Missing soldier branch control: '+control)
    return bool(fields[control]) if expected is None else fields[control] == expected


def _schema(human):
    if type(human) is not bool and human != 'target':
        raise PacketError('Explicit soldier equipment profile required')
    return SCHEMAS[human]


def encode_battle_soldier(soldier):
    w = Writer().u8(0x3b)
    used = set()
    for key, size, reader in _schema(soldier.human_equipment):
        if not _enabled(key, soldier.fields):
            continue
        if key not in soldier.fields:
            raise PacketError('Missing soldier field: '+key)
        value = soldier.fields[key]
        used.add(key)
        if reader == 'CString':
            if not isinstance(value, bytes) or len(value)>255 or b'\0' in value:
                raise PacketError('Expected bounded soldier name')
            w.data.extend(value+b'\0')
        else:
            w.data.extend(uint(value, size*8).to_bytes(size, 'little'))
    if used != set(soldier.fields):
        raise PacketError('Unexpected soldier fields for selected branches')
    return w.build()


def decode_battle_soldier(packet, *, human_equipment):
    schema = _schema(human_equipment)
    r = Reader(packet)
    if r.u8() != 0x3b:
        raise PacketError('Expected BattleSoldierAdd3B')
    fields = {}
    for key, size, reader in schema:
        if not _enabled(key, fields):
            continue
        if reader == 'CString':
            name = bytearray()
            while (char := r.u8()) != 0:
                name.append(char)
                if len(name)>255:
                    raise PacketError('Soldier name too long')
            fields[key] = bytes(name)
        else:
            fields[key] = int.from_bytes(r.read(size), 'little')
    r.finish()
    return BattleSoldier(human_equipment, fields)

# Original numeric-read traces; regenerate only against the pinned client.
SCHEMAS = {True: (('0x8c5088', 4, '0x605db8'),
        ('0x8c50ea', 4, '0x605db8'),
        ('0x8c50fb', 4, '0x605db8'),
        ('0x8c5116', 1, 'CString'),
        ('0x8c5134', 1, '0x605d68'),
        ('0x8c514b', 4, '0x605db8'),
        ('0x8c515f', 1, '0x605d68'),
        ('0x8c5173', 1, '0x605d68'),
        ('0x8c5187', 1, '0x605d68'),
        ('0x8c519b', 1, '0x605d68'),
        ('0x8c51af', 1, '0x605d68'),
        ('0x6d0203', 1, '0x605d68'),
        ('0x6d0213', 1, '0x605d68'),
        ('0x6d0221', 1, '0x605d68'),
        ('0x6d022e', 1, '0x605d68'),
        ('0x6d023c', 1, '0x605d68'),
        ('0x6d024a', 1, '0x605d68'),
        ('0x6d0258', 1, '0x605d68'),
        ('0x8c525b', 2, '0x605d8c'),
        ('0x8c5281', 2, '0x605d8c'),
        ('0x8c52a7', 2, '0x605d8c'),
        ('0x8c52bb', 2, '0x605d8c'),
        ('0x8c52cf', 2, '0x605d8c'),
        ('0x8c52f5', 2, '0x605d8c'),
        ('0x8c531b', 2, '0x605d8c'),
        ('0x8c5341', 2, '0x605d8c'),
        ('0x8c5367', 2, '0x605d8c'),
        ('0x8c538d', 2, '0x605d8c'),
        ('0x8c53b3', 2, '0x605d8c'),
        ('0x8c53d9', 2, '0x605d8c'),
        ('0x8c53ff', 2, '0x605d8c'),
        ('0x8c54cc', 4, '0x605de4'),
        ('0x8c54e1', 4, '0x605de4'),
        ('0x8c54f6', 4, '0x605de4'),
        ('0x8c550b', 4, '0x605de4'),
        ('0x8c5520', 4, '0x605de4'),
        ('0x8c5535', 4, '0x605de4'),
        ('0x8c554a', 4, '0x605de4'),
        ('0x8c555f', 4, '0x605de4'),
        ('0x8c5574', 4, '0x605de4'),
        ('0x8c5589', 4, '0x605de4'),
        ('0x8c559e', 4, '0x605de4'),
        ('0x8c55b3', 4, '0x605de4'),
        ('0x8c55c8', 4, '0x605de4'),
        ('0x8c55dd', 4, '0x605de4'),
        ('0x8c55f2', 4, '0x605de4'),
        ('0x8c5607', 4, '0x605de4'),
        ('0x8c561c', 4, '0x605da0'),
        ('0x8c5631', 4, '0x605da0'),
        ('0x8c5646', 4, '0x605da0'),
        ('0x8c566a', 2, '0x605d8c'),
        ('0x8c567f', 1, '0x605d68'),
        ('0x8c5694', 1, '0x605d68'),
        ('0x8c56a8', 1, '0x605d68'),
        ('0x8c56b9', 4, '0x605da0'),
        ('0x8c56cd', 4, '0x605da0'),
        ('0x8c56e1', 4, '0x605da0'),
        ('0x8c56f5', 4, '0x605da0'),
        ('0x8c5709', 4, '0x605da0'),
        ('0x8c571d', 1, '0x605d68'),
        ('0x8c5731', 2, '0x605d8c'),
        ('0x8c5748', 2, '0x605d8c'),
        ('0x8c575d', 1, '0x605d68'),
        ('0x8c57bb', 2, '0x605d8c'),
        ('0x8c57d0', 2, '0x605d8c'),
        ('0x8c57e7', 2, '0x605d8c'),
        ('0x8c57fe', 1, '0x605d68'),
        ('0x8c581d', 4, '0x605db8'),
        ('0x8c5831', 1, '0x605d68'),
        ('0x8c5847', 4, '0x605da0'),
        ('0x8c585c', 4, '0x605da0'),
        ('0x8c5870', 4, '0x605da0'),
        ('0x8c5884', 4, '0x605da0'),
        ('0x8c5898', 4, '0x605da0'),
        ('0x8c58b8', 4, '0x605da0'),
        ('0x8c58d7', 4, '0x605db8'),
        ('0x8c5918', 4, '0x605da0'),
        ('0x8c5938', 4, '0x605da0'),
        ('0x8c5957', 4, '0x605db8'),
        ('0x8c5998', 4, '0x605da0'),
        ('0x8c59b2', 4, '0x605da0'),
        ('0x8c59c3', 4, '0x605db8'),
        ('0x8c59e8', 4, '0x605da0'),
        ('0x8c5a02', 4, '0x605da0'),
        ('0x8c5a13', 4, '0x605db8'),
        ('0x8c5a41', 4, '0x605da0'),
        ('0x8c5a66', 4, '0x605da0'),
        ('0x8c5a8b', 4, '0x605de4')),
 False: (('0x8c5088', 4, '0x605db8'),
         ('0x8c50ea', 4, '0x605db8'),
         ('0x8c50fb', 4, '0x605db8'),
         ('0x8c5116', 1, 'CString'),
         ('0x8c5134', 1, '0x605d68'),
         ('0x8c514b', 4, '0x605db8'),
         ('0x8c515f', 1, '0x605d68'),
         ('0x8c5173', 1, '0x605d68'),
         ('0x8c5187', 1, '0x605d68'),
         ('0x8c519b', 1, '0x605d68'),
         ('0x8c51af', 1, '0x605d68'),
         ('0x6d0203', 1, '0x605d68'),
         ('0x6d0213', 1, '0x605d68'),
         ('0x6d0221', 1, '0x605d68'),
         ('0x6d022e', 1, '0x605d68'),
         ('0x6d023c', 1, '0x605d68'),
         ('0x6d024a', 1, '0x605d68'),
         ('0x6d0258', 1, '0x605d68'),
         ('0x8c543f', 2, '0x605d8c'),
         ('0x8c546e', 2, '0x605d8c'),
         ('0x8c549d', 2, '0x605d8c'),
         ('0x8c54cc', 4, '0x605de4'),
         ('0x8c54e1', 4, '0x605de4'),
         ('0x8c54f6', 4, '0x605de4'),
         ('0x8c550b', 4, '0x605de4'),
         ('0x8c5520', 4, '0x605de4'),
         ('0x8c5535', 4, '0x605de4'),
         ('0x8c554a', 4, '0x605de4'),
         ('0x8c555f', 4, '0x605de4'),
         ('0x8c5574', 4, '0x605de4'),
         ('0x8c5589', 4, '0x605de4'),
         ('0x8c559e', 4, '0x605de4'),
         ('0x8c55b3', 4, '0x605de4'),
         ('0x8c55c8', 4, '0x605de4'),
         ('0x8c55dd', 4, '0x605de4'),
         ('0x8c55f2', 4, '0x605de4'),
         ('0x8c5607', 4, '0x605de4'),
         ('0x8c561c', 4, '0x605da0'),
         ('0x8c5631', 4, '0x605da0'),
         ('0x8c5646', 4, '0x605da0'),
         ('0x8c566a', 2, '0x605d8c'),
         ('0x8c567f', 1, '0x605d68'),
         ('0x8c5694', 1, '0x605d68'),
         ('0x8c56a8', 1, '0x605d68'),
         ('0x8c56b9', 4, '0x605da0'),
         ('0x8c56cd', 4, '0x605da0'),
         ('0x8c56e1', 4, '0x605da0'),
         ('0x8c56f5', 4, '0x605da0'),
         ('0x8c5709', 4, '0x605da0'),
         ('0x8c571d', 1, '0x605d68'),
         ('0x8c5731', 2, '0x605d8c'),
         ('0x8c5748', 2, '0x605d8c'),
         ('0x8c575d', 1, '0x605d68'),
         ('0x8c57bb', 2, '0x605d8c'),
         ('0x8c57d0', 2, '0x605d8c'),
         ('0x8c57e7', 2, '0x605d8c'),
         ('0x8c57fe', 1, '0x605d68'),
         ('0x8c581d', 4, '0x605db8'),
         ('0x8c5831', 1, '0x605d68'),
         ('0x8c5847', 4, '0x605da0'),
         ('0x8c585c', 4, '0x605da0'),
         ('0x8c5870', 4, '0x605da0'),
         ('0x8c5884', 4, '0x605da0'),
         ('0x8c5898', 4, '0x605da0'),
         ('0x8c58b8', 4, '0x605da0'),
         ('0x8c58d7', 4, '0x605db8'),
         ('0x8c5918', 4, '0x605da0'),
         ('0x8c5938', 4, '0x605da0'),
         ('0x8c5957', 4, '0x605db8'),
         ('0x8c5998', 4, '0x605da0'),
         ('0x8c59b2', 4, '0x605da0'),
         ('0x8c59c3', 4, '0x605db8'),
         ('0x8c59e8', 4, '0x605da0'),
         ('0x8c5a02', 4, '0x605da0'),
         ('0x8c5a13', 4, '0x605db8'),
         ('0x8c5a41', 4, '0x605da0'),
         ('0x8c5a66', 4, '0x605da0'),
         ('0x8c5a8b', 4, '0x605de4'))}

# 8c542f checks equipment class==1 (animal). Class2 (target) skips
# equipment entirely; it is neither the human nor the animal wire layout.
SCHEMAS['target'] = tuple(row for row in SCHEMAS[False]
                          if row[0] not in ('0x8c543f','0x8c546e','0x8c549d'))
