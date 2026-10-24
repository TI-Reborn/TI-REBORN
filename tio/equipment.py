"""Atomic equipment snapshots with explicitly supplied template/slot rules.

Wire action33 routing and automatic slot selection are separate concerns.
Rules must come from recovered compatibility data, not from the option byte.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import sqlite3
from collections.abc import Mapping
from typing import NotRequired, TypedDict

from .owned_pets import OwnedPetStore
from .protocol.item_action import TARGET_MASKS
from .protocol.item_action import decode_item_action
from .protocol.item_list import decode_item_list, encode_item_list
from .item_catalog import items_root
from functools import lru_cache


class EquipmentRejected(ValueError):
    pass


class ArmorRule(TypedDict):
    slot: int
    dog: bool
    level: int
    covers: NotRequired[tuple[int, ...]]
    female: NotRequired[bool]
    miner: NotRequired[bool]


def armor_coverage(template: int, slot: int, rules: Mapping[int, ArmorRule]) -> frozenset[int]:
    """One slot-conflict rule for equipment placement and effective defense."""
    return frozenset(rules.get(template, {}).get('covers', (slot,)))


class EquipmentStore:
    def __init__(self, path, rules, *, armor=None, weapons_only=False):
        self.path = path
        self.armor = armor or {}
        self.weapons_only = weapons_only
        self.rules = {template: frozenset(slots) for template, slots in rules.items()}
        if any(not slots or not slots.issubset(TARGET_MASKS) for slots in self.rules.values()):
            raise ValueError('Equipment rules require recognized target masks')
        OwnedPetStore(path)

    def place(self, pet_packet, human_equipment, items, instance_id, slot, *, toggle=False):
        """Validate/place in memory; caller owns the transaction."""
        if slot is not None and slot not in TARGET_MASKS:
            raise EquipmentRejected("Unknown equipment slot")
        selected = next((i for i in items if i.instance_id == instance_id), None)
        if selected is None:
            raise EquipmentRejected('Owned item missing')
        allowed = self.rules.get(selected.template_id, ())
        if not allowed or (slot is not None and slot not in allowed):
            raise EquipmentRejected('Item is incompatible with slot')
        if selected.count != 1 or any(i.equipped not in (0, 1) for i in items):
            raise EquipmentRejected('Unsupported inventory state')
        if toggle and selected.equipped:
            slot = None
        if slot is not None:
            from .durability import broken
            if broken(selected):raise EquipmentRejected('Сломанный предмет нельзя экипировать')
            from .protocol.pet_info import decode_pet_info
            pet=decode_pet_info(pet_packet,human_equipment=human_equipment).fields
            from .enhancement_limits import equipment_base_levels, required_level
            if selected.template_id in equipment_base_levels() and pet['0x8c4aef'] < required_level(selected):
                raise EquipmentRejected('Equipment requires level '+str(required_level(selected)))
            rule=self.armor.get(selected.template_id)
            if rule:
                dog=pet['0x8c446f'] in (3,4,5) and not human_equipment
                human=pet['0x8c446f'] in (1,2) and bool(human_equipment)
                miner=pet['0x8c446f']==6 and bool(human_equipment)
                if not (miner if rule.get('miner') else dog if rule['dog'] else human):
                    raise EquipmentRejected('Armor is incompatible with this mercenary')
                if rule.get('female') and pet['0x8c446f'] != 2:
                    raise EquipmentRejected('Armor requires a female mercenary')
                if pet['0x8c4aef'] < rule['level']:
                    raise EquipmentRejected('Armor requires level '+str(rule['level']))
            elif self.weapons_only and not human_equipment:
                raise EquipmentRejected('Human weapon cannot be equipped by a dog')
            elif self.weapons_only:
                from .weapons import WeaponCatalog
                source=WeaponCatalog().sources.get(selected.template_id,{})
                if (source.get('freaks_only')=='1') != (pet['0x8c446f']==6):
                    raise EquipmentRejected('Weapon is incompatible with this mercenary')
        updated = []
        if slot is not None and ((selected.template_id==334 and slot==4 and any(i.equipped and i.client_slot==16 for i in items))
                or slot==16 and any(i.equipped and i.template_id==334 and i.client_slot==4 for i in items)):
            raise EquipmentRejected('Для жилета смертника нужно освободить основную руку')
        for item in items:
            if item.instance_id == instance_id:
                item = replace(item, unknown_u8_01=int(slot is not None), location_raw=slot or 0)
            elif slot is not None and item.equipped and (
                armor_coverage(selected.template_id, slot, self.armor) &
                armor_coverage(item.template_id, item.client_slot, self.armor)
            ):
                item = replace(item, unknown_u8_01=0, location_raw=0)
            updated.append(item)
        return tuple(updated)

    def assign(self, account, pet_id, instance_id, slot, *, toggle=False):
        """Assign a resolved slot, or None to return an item to the backpack.

Replacing an occupied slot returns its previous item to the backpack in the
same transaction. No wallet, item ID, quantity or opaque item fields change.
"""
        if not isinstance(account, str) or not account:
            raise EquipmentRejected('Account required')
        if slot is not None and slot not in TARGET_MASKS:
            raise EquipmentRejected('Unknown equipment slot')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             (account, pet_id)).fetchone()
            if row is None:
                raise EquipmentRejected('Owned pet missing')
            owner = OwnedPetStore.validate(row[1], row[2], bool(row[0]))
            if owner != pet_id:
                raise EquipmentRejected('Stored pet key differs from packet')
            _, items, unknown = decode_item_list(row[2])
            updated = self.place(row[1], bool(row[0]), items, instance_id, slot, toggle=toggle)
            inventory = encode_item_list(owner, tuple(updated), unknown)
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (inventory, account, pet_id))
        return inventory


def equip_primary_weapon(path, account, packet):
    """City equipment33, including native head/chest/legs armor slots."""
    action = decode_item_action(packet)
    from .weapons import WeaponCatalog
    catalog=WeaponCatalog()
    rules={i:(0x10,0x80) for i in catalog.weapons
           if i not in (300,333,337)}
    armor=armor_rules()
    rules.update({i:(r['slot'],) for i,r in armor.items()})
    inventory=OwnedPetStore(path).inventory(account,action.pet_id)
    if inventory is None:raise EquipmentRejected('Owned pet missing')
    selected=next((i for i in decode_item_list(inventory)[1] if i.instance_id==action.instance_id),None)
    if selected is None:raise EquipmentRejected('Owned item missing')
    slot=action.target_mask or armor.get(selected.template_id,{}).get('slot',16)
    return EquipmentStore(path, rules,armor=armor,weapons_only=True).assign(
        account, action.pet_id, action.instance_id, slot, toggle=action.option == 255)


def swap_city_weapons(path, account, packet):
    """Native city hand-to-hand drag sends 6D + pet ID, not action33.

    Exchange both hand slots atomically, including a single weapon/empty hand.
    This only moves already equipped items; no item attributes are rewritten.
    Caller must restrict this route to the city (battle has turn/AP rules).
    """
    from .protocol.binary import Reader
    r=Reader(packet)
    if r.u8()!=0x6d:raise EquipmentRejected('Expected weapon swap6D')
    owner=r.u32();r.finish()
    if not isinstance(account,str) or not account:raise EquipmentRejected('Account required')
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                       (account,owner)).fetchone()
        if row is None:raise EquipmentRejected('Owned pet missing')
        if OwnedPetStore.validate(row[1],row[2],bool(row[0]))!=owner:
            raise EquipmentRejected('Stored pet key differs from packet')
        _,items,unknown=decode_item_list(row[2])
        hands=[i for i in items if i.equipped and i.client_slot in (16,128)]
        if any(i.count!=1 or i.equipped!=1 for i in hands) or len({i.client_slot for i in hands})!=len(hands):
            raise EquipmentRejected('Unsupported inventory state')
        updated=tuple(replace(i,location_raw=128 if i.client_slot==16 else 16)
                      if i in hands else i for i in items)
        inventory=encode_item_list(owner,updated,unknown)
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                   (inventory,account,owner))
    return inventory


def armor_rules() -> dict[int, ArmorRule]:
    """Fresh copy of the cached armor rules (callers and snapshots may own it)."""
    return {identity: dict(rule) for identity, rule in _armor_rules().items()}


@lru_cache(maxsize=1)
def _armor_rules() -> dict[int, ArmorRule]:
    """Use the same client-derived catalog delivered to the game, not item names.

    Female Exo and Tank cover head/chest/legs. Both use chest4.
    Other complex armor remains unsupported; default body meshes are not clothing.
    Native target masks: head1, chest4, legs8; dog chest also4.
    """
    result={}
    for item in items_root().iter('item'):
        values={v.get('key'):v.get('val') for v in item.findall('value')}
        identity=int(item.get('id'))
        slot={'head':1,'chest':4,'legs':8}.get(values.get('bodypart'))
        female_exo=identity in (263,264) and values.get('bodypart')=='complexarmor' and values.get('woman_only')=='1'
        tank=identity in (254,256) and values.get('bodypart')=='complexarmor'
        if female_exo or tank:slot=4
        if values.get('itype')!='armor' or not slot or identity>=65500:continue
        result[identity]={'slot':slot,'dog':values.get('dogs_only')=='1','level':int(values.get('level_required','0'))}
        if values.get('freaks_only')=='1':result[identity]['miner']=True
        if values.get('woman_only')=='1':result[identity]['female']=True
        if female_exo or tank:result[identity]['covers']=(1,4,8)
    return result
