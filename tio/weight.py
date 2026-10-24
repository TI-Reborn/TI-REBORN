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


def encode_weight(actor_id: int, weight: int, capacity: int | None = None) -> bytes:
    """Original4E carried mass, optionally including battle capacity.

    Unlike initial66/24 word fields this preserves totals above65535.
    City profiles already carry capacity. Native status7 unconditionally
    redraws the shared city/selection scale for nonselected squadmates, while
    status6 checks the selection. Never send redundant city status7 updates.
    """
    attributes = ((6, weight),) if capacity is None else ((7, capacity), (6, weight))
    writer = Writer().u8(0x4e).u32(actor_id).u32(len(attributes))
    for attribute, value in attributes:
        writer.u32(attribute).u32(value)
    return writer.u8(0).build()


def city_weight_update(path: str | Path, account: str, inventory: bytes) -> bytes:
    from contextlib import closing
    owner = decode_item_list(inventory)[0]
    with closing(connect(path)) as db:
        row = db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, owner)).fetchone()
        if row is None:
            raise ValueError('Owned actor required for weight update')
        return _city_weight(owner, inventory)


def city_profile_weight_update(path: str | Path, account: str, packet: bytes) -> bytes | None:
    """Restore native weight UI after PetInfo, using this owner's live bag.

    PetInfo refreshes during healing can reset the open inventory panel.
    Keep its absolute 4E follow-up identical to ordinary ItemList updates.
    """
    from contextlib import closing
    owner = int.from_bytes(packet[1:5], 'little')
    with closing(connect(path)) as db:
        if not db.in_transaction:
            db.execute('BEGIN')
        row = db.execute('SELECT inventory_packet FROM owned_pets '
                         'WHERE account=? AND pet_id=?', (account, owner)).fetchone()
        if row is None:
            return None
        return _city_weight(owner, row[0])


def _city_weight(owner: int, inventory: bytes) -> bytes:
    return encode_weight(owner, min(0xffffffff, inventory_weight(inventory)))
