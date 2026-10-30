"""Miner rules with an explicit manual/legacy-data reconciliation."""
import json
from functools import lru_cache
from pathlib import Path
from dataclasses import replace

MINER_SKILLS = (20, 21, 22, 24)


@lru_cache(maxsize=1)
def rules():
    return json.loads((Path(__file__).resolve().parents[1]/'config/miner_abilities.json').read_text(encoding='utf-8'))


def required_level(ability, rank):
    return rules()['required_levels'][str(ability)][rank-1]


def learning_price(ability,rank,learned):
    from .ability_prices import PricePolicy
    return PricePolicy.from_config(rules()).price(ability,rank,sum(e.level for e in learned))


def catalog_for_play(catalog):
    """Keep the raw legacy import unchanged; override only reconciled skill22."""
    from .abilities import AbilityCatalog
    data=rules(); records=[]
    for row in catalog.records:
        if row.ability_id==22 and row.level is not None:
            row=replace(row,fields={**row.fields,
                'value':str(data['slash_percent'][row.level-1]),
                'Cooldown':str(data['slash_cooldown'])})
        records.append(row)
    return AbilityCatalog(records)


def naked(inventory):
    """Base defense applies without worn armor; a carried piece is harmless."""
    from .equipment import armor_rules
    from .protocol.item_list import decode_item_list
    if inventory is None:return True
    armor=armor_rules()
    return not any(i.equipped and i.template_id in armor for i in decode_item_list(inventory)[1])
