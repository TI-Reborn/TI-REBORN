"""Implant families, upgrade percentages and powered passive projections."""
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import lru_cache
from fractions import Fraction
from itertools import combinations
import json
from pathlib import Path
from types import MappingProxyType

from .item_catalog import items_root
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .weapon_proficiency import NAMES, SAVED, number, bits, ProficiencyRules

SLOTS = (0x40000, 0x80000, 0x100000, 0x200000)


@lru_cache(maxsize=1)
def policy() -> dict:
    value = json.loads((Path(__file__).resolve().parents[1]/'config/implant_lifecycle.json').read_text())
    if (value['version'] != 1 or value['upgrade']['maximum'] != 25
            or value['extra']['chance_percent'] != 20
            or value['extra']['milestones'] != [5, 10, 15, 20, 25]):
        raise ValueError('Unsupported implant lifecycle policy')
    return value


def family(template: int) -> int:
    if template not in catalog():
        raise ValueError('Unknown implant template')
    return int(_metadata()[template].get('implant_base', template))


def variant(base: int, effect: int) -> int:
    combos = tuple(combo_recipes().values())
    if (base not in (*range(6100, 6111), *combos)
            or str(effect) not in policy()['extra']['effects']):
        raise ValueError('Unknown implant extra effect')
    if base in combos:
        return policy()['combo']['variant_start'] + (base-policy()['combo']['template_start'])*32 + effect
    return 6200+(base-6100)*32+effect


def combo_recipes(rules: Mapping | None = None) -> dict[tuple[int, int], int]:
    rules = policy()['combo'] if rules is None else rules
    return {pair: rules['template_start']+index
            for index, pair in enumerate(combinations(rules['families'], 2))}


def extra_effect(template: int) -> int | None:
    value = _metadata().get(template, {}).get('implant_extra')
    return int(value) if value is not None else None


def is_combined(template: int) -> bool:
    return bool(_metadata().get(template, {}).get('parentIds'))


@lru_cache(maxsize=1)
def _metadata() -> Mapping[int, dict[str, str]]:
    return {int(n.get('id')): {v.get('key'): v.get('val') for v in n.findall('value')}
            for n in items_root() if n.find("value[@key='itype'][@val='implant']") is not None}


def effect_percent(item: ItemRecord, stat: str | None = None) -> Fraction:
    if stat is None:
        stat = catalog()[item.template_id][0]
    if stat not in effect_stats(item.template_id):
        raise ValueError('Unknown implant statistic')
    base, step = policy()['steps_basis_points'][stat]
    level = item.unknown_bytes_03[0]
    if level > policy()['upgrade']['maximum']:
        raise ValueError('Unsupported implant upgrade')
    bonus = (100 if level >= 10 else 0) + (300 if level >= 20 else 0) if stat == 'armor' else 0
    return Fraction(base+step*level+bonus, 100)


@lru_cache(maxsize=1)
def catalog() -> Mapping[int, tuple[str, int]]:
    return MappingProxyType({template: next(iter(effects.items()))
                             for template, effects in _effects().items()})


def effect_stats(template: int) -> Mapping[str, int]:
    return _effects().get(template, MappingProxyType({}))


@lru_cache(maxsize=1)
def _effects() -> Mapping[int, Mapping[str, int]]:
    result = {}
    for node in items_root():
        values = {v.get('key'): v.get('val') for v in node.findall('value')}
        if values.get('itype') != 'implant':
            continue
        effects = {}
        for effect in node.findall('effect'):
            stat = effect.get('stat', values['implant_stat'])
            if stat not in (*NAMES[:6], 'health', 'armor', 'healing', 'carry', 'mining') or stat in effects:
                raise ValueError('Invalid implant effect')
            percent = effect.get('val', '')
            if (not percent.endswith('%') or not percent[:-1].isdigit()
                    or not 1 <= int(percent[:-1]) <= 100):
                raise ValueError('Invalid implant percentage')
            effects[stat] = int(percent[:-1])
        if not effects:
            raise ValueError('Missing implant effects')
        result[int(node.get('id'))] = MappingProxyType(effects)
    return MappingProxyType(result)


def powered(fields: Mapping[str, int], inventory: bytes | None) -> tuple[ItemRecord, ...]:
    """Ignore disabled/broken implants; reject ambiguous installed snapshots."""
    if inventory is None or fields['0x8c446f'] not in (1, 2) or fields['0x8c4aef'] < 4:
        return ()
    from .implant_power import energy
    if not energy(inventory)[0]:
        return ()
    unlocked = SLOTS[:min(4, fields['0x8c4a42'])]
    result, occupied, stats, combined = [], set(), set(), False
    for item in decode_item_list(inventory)[1]:
        rule = catalog().get(item.template_id)
        if rule is None or item.equipped != 1 or item.client_slot not in unlocked:
            continue
        effects = effect_stats(item.template_id)
        combo = is_combined(item.template_id)
        if (item.client_slot in occupied or stats.intersection(effects) or item.count != 1
                or (combo and combined)):
            raise ValueError('Ambiguous installed implants')
        occupied.add(item.client_slot)
        stats.update(effects)
        combined |= combo
        if item.unknown_words[0] > 0:
            result.append(item)
    return tuple(result)


def active(fields: Mapping[str, int], inventory: bytes | None) -> dict[str, Fraction]:
    return {stat: effect_percent(item, stat) for item in powered(fields, inventory)
            for stat in effect_stats(item.template_id)}


def project_inventory(packet: bytes, fields: Mapping[str, int] | None) -> bytes:
    """Native63c9b8 -> TSItem+13 is implant power, never saved as a base flag."""
    owner, items, flag = decode_item_list(packet)
    enabled = {i.instance_id for i in powered(fields, packet)} if fields is not None else set()
    projected = tuple(replace(i, unknown_bytes_02=bytes((i.unknown_bytes_02[0],
        int(i.instance_id in enabled), *i.unknown_bytes_02[2:]))) if i.template_id in catalog() else i for i in items)
    return packet if projected == items else encode_item_list(owner, projected, flag)


def health_maximum(fields: Mapping[str, int], base: int, percent: Fraction,
                   health_bonus: int = 0) -> int:
    from .level_progression import RULES
    maximum = (RULES['initial_hp'][str(fields['0x8c446f'])]
               + (bracket_top(fields['0x8c4aef'])-1)*RULES['hp_per_level'] + health_bonus)
    return min(65535, max(base, min(maximum*105//100, base*(100+percent)//100)))


def place(fields: Mapping[str, int], items: Sequence[ItemRecord], instance: int,
          slot: int | None) -> tuple[ItemRecord, ...]:
    selected = next((item for item in items if item.instance_id == instance), None)
    if selected is None or selected.template_id not in catalog() or selected.count != 1:
        raise ValueError('Нужен собственный отдельный имплант')
    if fields['0x8c446f'] not in (1, 2) or fields['0x8c4aef'] < 4:
        raise ValueError('Импланты доступны людям с 4 уровня')
    if selected.equipped:
        if slot == selected.client_slot:
            return tuple(items)
        raise ValueError('Установленный имплант можно только уничтожить')
    if (selected.unknown_words[0] <= 0 or any(selected.unknown_bytes_02[1:])
            or any(selected.unknown_bytes_03[1:])):
        raise ValueError('Нужен исправный имплант')
    for stat in effect_stats(selected.template_id):
        effect_percent(selected, stat)
    unlocked = SLOTS[:min(4, fields['0x8c4a42'])]
    installed = [item for item in items if item.equipped and item.client_slot in SLOTS]
    if slot is None:
        slot = next((s for s in unlocked if all(item.client_slot != s for item in installed)), None)
    if slot not in unlocked:
        raise ValueError('Нет свободного слота: изучите Кибернетику')
    stats = set(effect_stats(selected.template_id))
    if any(stats.intersection(effect_stats(item.template_id))
           for item in installed if item.client_slot != slot):
        raise ValueError('Нельзя устанавливать импланты с одинаковым эффектом')
    if is_combined(selected.template_id) and any(is_combined(item.template_id)
            for item in installed if item.client_slot != slot):
        raise ValueError('Нельзя установить несколько комбо-имплантов')
    return tuple(
        replace(item, unknown_u8_01=1, location_raw=slot) if item == selected else item
        for item in items
        if item == selected or not (item.equipped and item.client_slot == slot))


def bracket_top(level: int) -> int:
    return next((top for top in (3, 6, 10, 15, 20) if level <= top), 20)


def skill_value(value: float, percent: int, level: int) -> float:
    cap = ProficiencyRules().caps(bracket_top(level), True)[0]
    return max(value, min(cap, value * (100 + percent) / 100))


def project_skills(packet: bytes, human: bool, inventory: bytes | None) -> bytes:
    from .implant_power import project_energy
    packet = project_energy(packet, human, inventory)
    pet = decode_pet_info(packet, human_equipment=human)
    fields = dict(pet.fields)
    effects = active(fields, inventory) if human else {}
    if not effects:
        return packet
    for index, stat in enumerate(NAMES[:6]):
        if stat in effects:
            fields[SAVED[index]] = bits(skill_value(
                number(fields[SAVED[index]]), effects[stat], fields['0x8c4aef']))
    return encode_pet_info(replace(pet, fields=fields))


def project_stats(packet: bytes, human: bool, inventory: bytes | None, *,
                  health_bonus: int = 0) -> bytes:
    pet = decode_pet_info(packet, human_equipment=human)
    fields = dict(pet.fields)
    effects = active(fields, inventory) if human else {}
    if not effects:
        return packet
    if 'health' in effects:
        base = fields['0x8c4a07']
        fields['0x8c4a07'] = health_maximum(fields, base, effects['health'], health_bonus)
    if 'carry' in effects:
        fields['0x8c4b57'] = min(65535, fields['0x8c4b57']*(100+effects['carry'])//100)
    return encode_pet_info(replace(pet, fields=fields))


def armor_bonus(fields: Mapping[str, int], inventory: bytes | None) -> int:
    return fields['0x8c4ac5'] * active(fields, inventory).get('armor', 0) // 100
