"""Pure combo selection and random outcomes; ownership is checked by storage."""
from collections.abc import Callable
from dataclasses import replace

from .implants import SLOTS, combo_recipes, extra_effect, family, policy, variant
from .protocol.item_list import ItemRecord


def prepare(first: ItemRecord, second: ItemRecord) -> ItemRecord:
    rules = policy()['combo']
    if first.instance_id == second.instance_id:
        raise ValueError('Нужны два разных импланта')
    parents = tuple(sorted((family(first.template_id), family(second.template_id))))
    template = combo_recipes().get(parents)
    if template is None:
        raise ValueError('Нужны два разных базовых импланта')
    levels = (first.unknown_bytes_03[0], second.unknown_bytes_03[0])
    if levels[0] != levels[1] or not rules['minimum_level'] <= levels[0] <= policy()['upgrade']['maximum']:
        raise ValueError('Нужен одинаковый апгрейд от +5 до +25')
    for item in (first, second):
        installed = item.equipped == 1 and item.client_slot in SLOTS
        loose = item.equipped == 0 and item.client_slot == 0
        if (item.count != 1 or not (installed or loose) or item.unknown_words[0] <= 0
                or item.optional_u32 is not None or any(item.unknown_bytes_01)
                or any(item.unknown_bytes_02[1:]) or any(item.unknown_bytes_03[1:])):
            raise ValueError('Нужны исправные собственные импланты без ограничений')

    from .durability import definitions
    resource = int(definitions()[template]['durability']) + levels[0]*policy()['upgrade']['durability_per_level']
    if not 0 < resource <= 65535:
        raise ValueError('Implant durability overflow')
    return replace(first, template_id=template, unknown_u8_01=0, location_raw=0,
                   unknown_words=(resource,)*3)


def combine(first: ItemRecord, second: ItemRecord,
            randbelow: Callable[[int], int]) -> ItemRecord | None:
    result = prepare(first, second)
    rules = policy()['combo']

    def roll(limit: int) -> int:
        value = randbelow(limit)
        if type(value) is not int or not 0 <= value < limit:
            raise ValueError('Invalid implant random result')
        return value

    if roll(100) >= rules['success_percent']:
        return None
    effects = sorted({e for i in (first, second) if (e := extra_effect(i.template_id)) is not None})
    if not effects and roll(100) < rules['new_extra_percent']:
        effects = [int(key) for key in policy()['extra']['effects']]
    if effects:
        effect = effects[roll(len(effects))] if len(effects) > 1 else effects[0]
        result = replace(result, template_id=variant(result.template_id, effect))
    return result
