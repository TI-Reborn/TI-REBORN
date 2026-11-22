"""Weighted permanent contract rewards, using existing items and containers."""
from random import Random

from .battle_state import BattleField
from .battle_loot import BattleLoot
from .protocol.item_list import ItemRecord

# Weights per 10,000 equipment drops: 90% plain, +10 once in 10,000.
UPGRADE_WEIGHTS = (9000, 500, 250, 120, 65, 35, 15, 8, 4, 2, 1)
EQUIPMENT_WEIGHTS = (
    (301, 100), (302, 80), (303, 80), (304, 60), (305, 90), (306, 45),
    (307, 45), (308, 20), (309, 45), (310, 60), (311, 35), (312, 10),
    (313, 15), (326, 100), (327, 70), (329, 80), (330, 30), (331, 80),
    (332, 35), (338, 20), (339, 15), (5013, 5),
    (210, 70), (211, 80), (212, 80), (213, 50), (214, 50), (215, 50),
    (216, 50), (217, 50), (218, 50), (219, 35), (220, 35), (221, 35),
    (229, 70), (230, 80), (231, 80), (232, 50), (233, 50), (234, 50),
    (239, 20), (240, 20), (241, 20), (242, 15), (243, 15), (244, 15),
    (245, 20), (246, 20), (247, 20), (254, 3), (263, 4),
)
AMMO_WEIGHTS = ((3, 25), (4, 15), (5, 20), (6, 10), (7, 20),
                (12, 5), (13, 10), (14, 3), (15, 10), (36, 5), (37, 3))
MATERIAL_WEIGHTS = ((65487, 60), (65488, 40))


def weighted_pick(entries: tuple[tuple[int, int], ...], roll: int) -> int:
    if not entries or any(type(weight) is not int or weight <= 0 for _, weight in entries):
        raise ValueError('Positive loot weights required')
    if type(roll) is not int or not 0 <= roll < sum(weight for _, weight in entries):
        raise ValueError('Invalid loot roll')
    for identity, weight in entries:
        if roll < weight:
            return identity
        roll -= weight
    raise ValueError('Invalid loot probability table')


def roll_upgrade(roll: int) -> int:
    return weighted_pick(tuple(enumerate(UPGRADE_WEIGHTS)), roll)


def _choose(entries: tuple[tuple[int, int], ...], rng: Random) -> int:
    return weighted_pick(entries, rng.randrange(sum(weight for _, weight in entries)))


def _item(loot: BattleLoot, template: int, count: int = 1, *, level: int = 0,
          durability: int | None = None) -> ItemRecord:
    if durability is None:
        durability = int(loot.metadata[template].get('durability', 0))
    return ItemRecord(loot._allocate(), template, bytes(2), count, 0, 0,
                      (durability,) * 3, bytes((level, 0, 0, 0)), None, bytes((level, 0, 0)))


def roll_equipment(loot: BattleLoot, rng: Random) -> ItemRecord:
    from .rule_catalogs import enhancement_rules
    rules = enhancement_rules()
    eligible = set(loot.weapons) | set(loot.armors)
    entries = tuple((i, weight) for i, weight in EQUIPMENT_WEIGHTS if i in eligible and i in rules.items)
    if not entries:
        raise ValueError('No eligible contract equipment')
    template = _choose(entries, rng)
    level = roll_upgrade(rng.randrange(sum(UPGRADE_WEIGHTS)))
    durability = rules.items[template]['durability'] + level * rules.config['durability_per_level']
    loot.next_id = loot.allocation_floor()
    return _item(loot, template, level=level, durability=durability)


def populate_crates(loot: BattleLoot) -> None:
    """Roll each physical chest once; permanent supplies use normal pickup CAS."""
    loot.next_id = loot.allocation_floor()
    for position in sorted(loot.boxes):
        if loot.boxes[position] is not None:
            continue
        ammo = _choose(AMMO_WEIGHTS, loot.rng)
        material = _choose(MATERIAL_WEIGHTS, loot.rng)
        items = [_item(loot, ammo, int(loot.metadata[ammo]['packamount'])),
                 _item(loot, material, loot.rng.randint(1, 3))]
        if loot.rng.randrange(100) < 25:
            items.append(_item(loot, _choose(((9, 80), (34, 20)), loot.rng), loot.rng.randint(1, 2)))
        loot.boxes[position] = tuple(items)


def remaining_loot(field: BattleField) -> bool:
    return any(items for items in field.loot.boxes.values())


def stage_boss_loot(field: BattleField) -> bool:
    """Called inside the battle journal; return whether boss equipment remains."""
    metadata = field.contract_metadata
    boss = metadata.get('boss')
    if boss is None:
        return False
    if not field.actor(boss).health and 'boss_item' not in metadata:
        loot = field.loot
        rng = Random(metadata['seed'] ^ 0x424F5353)
        item = roll_equipment(loot, rng)
        actor = field.actor(boss)
        position = (actor.x, actor.y)
        loot.boxes[position] = (*(loot.boxes.get(position) or ()), item)
        loot.ground.add(position)
        metadata['boss_item'] = item.instance_id
        metadata['boss_position'] = position
    identity = metadata.get('boss_item')
    return identity is not None and any(
        item.instance_id == identity for items in field.loot.boxes.values() for item in (items or ()))
