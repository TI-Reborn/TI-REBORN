"""Real upgrades persist; only effective equipment bonuses follow the owner's level.

Bracket caps: original manual p14. Equip gates: native A7C500/A7B480.
This is per-mercenary scaling, not the full cross-bracket TrueSkill system.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
from functools import lru_cache
import sqlite3
import xml.etree.ElementTree as ET

from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info


def enhancement_cap(level):
    if type(level) is not int or level < 1:
        raise ValueError('Positive mercenary level required for equipment scaling')
    return 3 if level <= 3 else 10 if level <= 6 else 15 if level <= 10 else 20 if level <= 15 else 25


@lru_cache(maxsize=1)
def equipment_base_levels():
    from .enhancement import EnhancementRules, ROOT
    eligible = EnhancementRules().items
    return {int(n.get('id')): int(next((v.get('val') for v in n if v.get('key') == 'level_required'), '1'))
            for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot() if int(n.get('id')) in eligible}


def required_level(item):
    base = equipment_base_levels().get(item.template_id, 1)
    real = item.unknown_bytes_03[0]
    if real >= 20:
        return base
    gate = 1 if real <= 3 else 4 if real <= 10 else 7 if real <= 15 else 11
    return max(base, gate)


def project_inventory(packet, cap, *, high_only=False):
    if cap not in (3, 10, 15, 20, 25):
        raise ValueError('Invalid equipment enhancement cap')
    owner, items, unknown = decode_item_list(packet)
    eligible = equipment_base_levels()
    projected = tuple(replace(i, unknown_bytes_02=bytes((min(i.unknown_bytes_03[0], cap),))+i.unknown_bytes_02[1:])
                      if i.template_id in eligible and (not high_only or i.unknown_bytes_03[0] >= 20)
                      else i for i in items)
    return packet if projected == items else encode_item_list(owner, projected, unknown)


def pet_cap(packet, human):
    return enhancement_cap(decode_pet_info(packet, human_equipment=human).fields['0x8c4aef'])


def project_owned_inventory(path, account, packet):
    """Wire-only city projection. Database snapshots remain valid for transactions/CAS."""
    owner, _, _ = decode_item_list(packet)
    with closing(connect(path)) as db:
        row = db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?', (account, owner)).fetchone()
    # Sub20 retains its native equip requirement (e.g. +10 needs level4).
    # High upgrades may be worn by a lower-level mercenary and are scaled.
    return packet if row is None else project_inventory(packet, pet_cap(row[1], bool(row[0])), high_only=True)
