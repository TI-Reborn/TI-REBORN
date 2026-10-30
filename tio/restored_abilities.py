"""Perks the client knows (locale, icons, readers) but the legacy CFG lacks.

The raw ability.cfg import in config/abilities.json stays a faithful copy;
restored definitions are an explicit, sourced overlay in
config/restored_abilities.json.
"""
from functools import lru_cache
import json
from pathlib import Path

from .abilities import AbilityCatalog, AbilityLevel


@lru_cache(maxsize=1)
def rules() -> dict:
    path = Path(__file__).resolve().parents[1]/'config/restored_abilities.json'
    data = json.loads(path.read_text(encoding='utf-8'))['abilities']
    for key, rule in data.items():
        ranks = len(rule['values'])
        if (not key.isdigit() or ranks == 0 or len(rule['required_levels']) != ranks
                or any(type(v) is not int or v < 0 for v in rule['values'] + rule['required_levels'])):
            raise ValueError('Invalid restored ability rule')
    return data


def restored_ids() -> frozenset[int]:
    return frozenset(int(key) for key in rules())


def records(ability: int) -> tuple[AbilityLevel, ...]:
    rule = rules()[str(ability)]
    ranks = len(rule['values'])
    return tuple(AbilityLevel(ability, rank, {
        'id': str(ability), 'name': rule['name'], 'levels': str(ranks), 'level': str(rank),
        'value': str(value), 'effect_text': rule['effect_text']})
        for rank, value in enumerate(rule['values'], 1))


def catalog_with_restored(catalog: AbilityCatalog) -> AbilityCatalog:
    """Add restored perks; a catalog that already carries them is returned as is.

    Battle and learning paths both apply the overlay, so it must be idempotent,
    but a different definition under a restored ID is a conflict.
    """
    expected = [row for ability in sorted(restored_ids()) for row in records(ability)]
    present = [row for row in catalog.records if row.ability_id in restored_ids()]
    if present == expected:
        return catalog
    if present:
        raise ValueError('Restored ability already defined differently')
    return AbilityCatalog((*catalog.records, *expected))


def required_level(ability: int, rank: int) -> int:
    return rules()[str(ability)]['required_levels'][rank-1]
