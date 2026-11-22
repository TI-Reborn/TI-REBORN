"""Pure implant upgrade outcomes; inventory transactions live outside."""
from collections.abc import Callable
from dataclasses import replace

from .implants import SLOTS, catalog, extra_effect, family, policy, variant
from .protocol.item_list import ItemRecord


def upgrade(item: ItemRecord, randbelow: Callable[[int], int]) -> tuple[ItemRecord | None, int]:
    rules = policy()['upgrade']
    level = item.unknown_bytes_03[0]
    installed = item.equipped == 1 and item.client_slot in SLOTS
    loose = item.equipped == 0 and item.client_slot == 0
    if (item.template_id not in catalog() or item.count != 1 or not (installed or loose)
            or item.optional_u32 is not None
            or any(item.unknown_bytes_02[1:]) or any(item.unknown_bytes_03[1:])
            or level >= rules['maximum']):
        raise ValueError('Нужен собственный имплант ниже +25')

    def roll(limit: int) -> int:
        value = randbelow(limit)
        if type(value) is not int or not 0 <= value < limit:
            raise ValueError('Invalid implant random result')
        return value

    chance = 100 if level < rules['safe_levels'] else rules['success_percent']
    if chance < 100 and roll(100) >= chance:
        return None, chance
    level += 1
    template = item.template_id
    extra = policy()['extra']
    if (extra_effect(template) is None and level in extra['milestones']
            and roll(100) < extra['chance_percent']):
        effects = tuple(int(key) for key in extra['effects'])
        template = variant(family(template), effects[roll(len(effects))])
    from .durability import definitions
    durability = int(definitions()[family(template)]['durability']) + level*rules['durability_per_level']
    if not 0 < durability <= 65535:
        raise ValueError('Implant durability overflow')
    return replace(item, template_id=template, unknown_words=(durability,)*3,
                   unknown_bytes_02=bytes((level, 0, 0, 0)),
                   unknown_bytes_03=bytes((level, 0, 0))), chance
