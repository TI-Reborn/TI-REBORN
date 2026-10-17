"""Effects with complete legacy item/ability definitions.

Circular blast/LOS and uniform damage retain the emulator's existing policy.
Missing legacy special-item values are explicit server policy in
config/special_items.json, never inferred from a name or client input.
"""
from .protocol.abilities import AbilityEntry

THROWN = frozenset((317,319))
BLAST = frozenset((316,317,319,323,340))
DIRECT_TYPES = frozenset(('Bullet','None','Minigun'))


def battle_skills(learned,inventory,human):
    from .protocol.item_list import decode_item_list
    entries=tuple(e for e in learned if e.ability_id!=27)
    if human and any(i.template_id==339 and i.equipped and i.client_slot==16
                     for i in decode_item_list(inventory)[1]):
        entries+=(AbilityEntry(27,1,0,1),)
    return entries
