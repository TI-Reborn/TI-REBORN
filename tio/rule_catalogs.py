"""Process-wide read-only rule catalogues shared by every battle.

They are derived only from config/*.json and evidence/items_diagnostic.xml,
which rules_digest pins for every battle snapshot. Nothing mutates them after
construction; battle snapshots store them by reference (see battle_snapshot).
The weapon catalogue is deliberately not shared: callers own their copy.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def armor_catalog():
    from .armor import ArmorCatalog
    return ArmorCatalog()


@lru_cache(maxsize=1)
def enhancement_rules():
    from .enhancement import EnhancementRules
    return EnhancementRules()


@lru_cache(maxsize=1)
def proficiency_rules():
    from .weapon_proficiency import ProficiencyRules
    return ProficiencyRules()
