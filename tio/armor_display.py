"""Absolute shield readout; never write equipment totals into base pet storage.

City66 and battle3B both store ArmorClass at native actor+6010. Original4E
attribute9 refreshes it after inventory changes. This module changes display,
not the combat mitigation formula.
"""

from .db_transaction import connect
from contextlib import closing
from functools import lru_cache
import sqlite3

from .armor import ArmorCatalog
from .enhancement_limits import pet_cap, project_inventory
from .protocol.binary import Writer, PacketError
from .protocol.pet_info import decode_pet_info, encode_pet_info


@lru_cache(maxsize=1)
def catalog():
    return ArmorCatalog()


def total(base, inventory, human, cap):
    worn = catalog().defense(project_inventory(inventory, cap), human=human)
    return min(65535, base + worn)


def encode_armor(owner, armor):
    if type(armor) is not int or not 0 <= armor <= 65535:
        raise PacketError('Armor must fit initial native word field')
    return Writer().u8(0x4e).u32(owner).u32(1).u32(9).u32(armor).u8(0).build()


def city_armor(path, account, owner):
    from .passive_stats import project_saved_pet
    with closing(connect(path)) as db:
        row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets '
                         'WHERE account=? AND pet_id=?', (account, owner)).fetchone()
        if row is None:
            raise ValueError('Owned actor required for armor display')
        human, raw, inventory = row
        projected = project_saved_pet(db, account, owner, raw, bool(human))
    base = decode_pet_info(projected, human_equipment=bool(human)).fields['0x8c4ac5']
    return total(base, inventory, bool(human), pet_cap(raw, bool(human)))


def project_city_pet(path, account, packet):
    owner = int.from_bytes(packet[1:5], 'little')
    with closing(connect(path)) as db:
        row = db.execute('SELECT human FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, owner)).fetchone()
    if row is None:return packet
    pet = decode_pet_info(packet, human_equipment=bool(row[0]))
    pet.fields['0x8c4ac5'] = city_armor(path, account, owner)
    return encode_pet_info(pet)
