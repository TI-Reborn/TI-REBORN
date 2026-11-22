"""Pure movement of items between two inventories of the same owner."""
from collections.abc import Iterable
from dataclasses import replace

from .implants import catalog as implant_catalog
from .inventory_capacity import INVENTORY_SLOTS, validate_capacity
from .item_stacking import merge_stacks
from .protocol.battle_exchange import BattleExchange
from .protocol.item_list import decode_item_list, encode_item_list


def exchange_items(first: bytes, second: bytes, request: BattleExchange, next_id: int,
                   *, temporary: Iterable[int] = (), limit: int = INVENTORY_SLOTS,
                   allow_unequip: bool = False
                   ) -> tuple[dict[int, bytes], int, set[int]]:
    old = (first, second)
    ids = (request.actor_id, request.target_id)
    bags, flags = [], []
    temporary = set(temporary)
    for identity, packet in zip(ids, old):
        owner, items, flag = decode_item_list(packet)
        bag = {i.instance_id: i for i in items}
        if owner != identity or len(bag) != len(items):
            raise ValueError('Invalid exchange inventory identity')
        bags.append(bag); flags.append(flag)
    if set(bags[0]) & set(bags[1]):
        raise ValueError('Duplicate exchange ownership')
    for selection, source, target in ((request.withdrawals, bags[1], bags[0]),
                                      (request.deposits, bags[0], bags[1])):
        for identity, count in selection:
            item = source.get(identity)
            if item is None or not (0 < count <= item.count or item.template_id == 52 and count == item.count == 0):
                raise ValueError('Предмет или его количество изменились')
            if item.equipped or item.slot:
                if not allow_unequip or item.count != 1 or item.template_id in implant_catalog():
                    raise ValueError('Сначала снимите передаваемое снаряжение')
                item = replace(item, unknown_u8_01=0, location_raw=0)
            if item.template_id == 52 and count != item.count:
                raise ValueError('Бур с кристаллами передаётся целиком')
            if count == item.count:
                source.pop(identity)
            else:
                if next_id > 0xffffffff:
                    raise ValueError('Item identity space exhausted')
                source[identity] = replace(item, unknown_u32_01=item.count-count)
                item = replace(item, instance_id=next_id, unknown_u32_01=count)
                if identity in temporary:
                    temporary.add(next_id)
                next_id += 1
            target[item.instance_id] = item
    changes = {}
    for index, bag in enumerate(bags):
        values = tuple(bag.values())
        merged = (*merge_stacks(i for i in values if i.instance_id not in temporary),
                  *merge_stacks(i for i in values if i.instance_id in temporary))
        validate_capacity(decode_item_list(old[index])[1], merged, limit=limit,
                          error=lambda _: ValueError('В инвентаре бойца недостаточно места'))
        changes[ids[index]] = encode_item_list(ids[index], merged, flags[index])
    return changes, next_id, temporary
