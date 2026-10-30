"""Boss equipment uses ordinary backpack packets and journaled battle state."""
from random import Random

from .battle_state import BattleField
from .protocol.item_list import ItemRecord

# Percentages for +0 through +10; weapon selection is uniform in the level pool.
UPGRADE_WEIGHTS = (30, 20, 15, 10, 8, 6, 4, 3, 2, 1, 1)


def roll_upgrade(roll: int) -> int:
    if type(roll) is not int or not 0 <= roll < 100:
        raise ValueError('Invalid boss loot roll')
    for level, weight in enumerate(UPGRADE_WEIGHTS):
        if roll < weight:
            return level
        roll -= weight
    raise ValueError('Invalid boss loot probability table')


def stage_boss_loot(field: BattleField) -> bool:
    """Called inside the battle journal; return whether boss equipment remains."""
    metadata = field.contract_metadata
    boss = metadata.get('boss')
    if boss is None:
        return False
    if not field.actor(boss).health and 'boss_item' not in metadata:
        from .enhancement import EnhancementRules
        rules = EnhancementRules()
        loot = field.loot
        candidates = [i for i in loot.weapons if i in rules.items]
        if not candidates:
            raise ValueError('No eligible boss weapons')
        rng = Random(metadata['seed'] ^ 0x424F5353)
        weapon = rng.choice(candidates)
        level = roll_upgrade(rng.randrange(100))
        durability = rules.items[weapon]['durability'] + level * rules.config['durability_per_level']
        loot.next_id = loot.allocation_floor()
        item = ItemRecord(loot._allocate(), weapon, bytes(2), 1, 0, 0,
                          (durability,) * 3, bytes((level, 0, 0, 0)), None, bytes((level, 0, 0)))
        actor = field.actor(boss)
        position = (actor.x, actor.y)
        loot.boxes[position] = (*(loot.boxes.get(position) or ()), item)
        loot.ground.add(position)
        metadata['boss_item'] = item.instance_id
        metadata['boss_position'] = position
    identity = metadata.get('boss_item')
    return identity is not None and any(
        item.instance_id == identity for items in field.loot.boxes.values() for item in (items or ()))
