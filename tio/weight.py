"""Carried mass and overload; equipped items are included exactly once."""

from .db_transaction import connect
from functools import lru_cache
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .protocol.item_list import decode_item_list
from .protocol.pet_info import decode_pet_info, encode_pet_info, PetInfo
from .protocol.binary import Writer

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT/'config/weight.json').read_text(encoding='utf-8'))
CAPACITIES = {int(k): v for k, v in POLICY['base_capacity'].items()}
PENALTIES = tuple(POLICY['ap_penalties'])
if (len(PENALTIES) != 5 or PENALTIES[0] != 0
        or any(type(v) is not int or v < 0 for v in (*PENALTIES, *CAPACITIES.values(), POLICY['capacity_per_level']))):
    raise ValueError('Invalid weight policy')


@lru_cache(maxsize=1)
def item_weights():
    """Native item metadata+65C: source weight, default0 if absent.

    containedItemId is a native container's payload type (not ammo_id).
    The mine drill uses this native container rule for its crystal payload.
    """
    result = {}
    for node in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot():
        values = {v.get('key'): v.get('val') for v in node.findall('value')}
        identity = int(node.get('id'))
        weight, contained = int(values.get('weight', '0')), int(values.get('containedItemId', '0'))
        if identity in result or not 0 <= weight <= 65535:
            raise ValueError('Invalid item weight metadata')
        result[identity] = (weight, contained)
    if any(child and child not in result for _, child in result.values()):
        raise ValueError('Unknown contained item weight')
    return result


def inventory_weight(packet):
    catalog = item_weights()
    total = 0
    for item in decode_item_list(packet)[1]:
        if (item.count < 1 and not (item.template_id == 52 and item.count == 0)) or item.template_id not in catalog:
            raise ValueError('Unknown item or invalid quantity in weight calculation')
        mass, child = catalog[item.template_id]
        total += mass + catalog[child][0]*item.count if child else mass*item.count
    return total


def base_capacity(resource, level):
    if resource not in CAPACITIES or not 1 <= level <= 255:
        raise ValueError('Unsupported actor capacity')
    return CAPACITIES[resource] + (level-1)*POLICY['capacity_per_level']


def overload_stage(weight, capacity):
    if weight < 0 or capacity <= 0:
        raise ValueError('Invalid carried weight/capacity')
    # Literal0.666 in original x87 constants, NOT the fraction2/3.
    return sum(weight*1000 >= capacity*threshold for threshold in (500, 666, 800, 1000))


def overload_penalty(weight, capacity):
    return PENALTIES[overload_stage(weight, capacity)]


def turn_ap(maximum, weight, capacity):
    return max(0, maximum-overload_penalty(weight, capacity))


def project_base_weight(packet, human, inventory):
    pet = decode_pet_info(packet, human_equipment=human)
    fields = dict(pet.fields)
    fields['0x8c4b57'] = base_capacity(fields['0x8c446f'], fields['0x8c4aef'])
    if inventory is not None:
        fields['0x8c4b6d'] = min(65535, inventory_weight(inventory))
    return encode_pet_info(PetInfo(human, fields))


def project_carried_weight(packet: bytes, human: bool, inventory: bytes) -> bytes:
    """Update carried mass without reapplying passive capacity/armor bonuses."""
    pet = decode_pet_info(packet, human_equipment=human)
    fields = {**pet.fields, '0x8c4b6d': min(65535, inventory_weight(inventory))}
    return encode_pet_info(PetInfo(human, fields))


def encode_weight(actor_id, weight, capacity):
    """Original4E attributes7(maximum) and6(carried), both native u32 stores.

    Unlike initial66/24 word fields this preserves totals above65535.
    """
    return (Writer().u8(0x4e).u32(actor_id).u32(2)
            .u32(7).u32(capacity).u32(6).u32(weight).u8(0).build())


def city_weight_update(path, account, inventory):
    from contextlib import closing
    import sqlite3
    from .passive_stats import project_saved_pet
    owner = decode_item_list(inventory)[0]
    with closing(connect(path)) as db:
        row = db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, owner)).fetchone()
        if row is None:
            raise ValueError('Owned actor required for weight update')
        pet = project_saved_pet(db, account, owner, row[1], bool(row[0]))
    fields = decode_pet_info(pet, human_equipment=bool(row[0])).fields
    return encode_weight(owner, min(0xffffffff, inventory_weight(inventory)), fields['0x8c4b57'])
