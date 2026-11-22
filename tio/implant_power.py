"""Pure battery charge, debit and native energy projections."""
from dataclasses import replace
from fractions import Fraction
import math

from .implants import policy
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info, encode_pet_info


def batteries(inventory: bytes | None) -> tuple[ItemRecord, ...]:
    if inventory is None:
        return ()
    result = tuple(i for i in decode_item_list(inventory)[1]
                   if i.template_id == policy()['battery']['template'] and not i.equipped)
    for item in result:
        current, maximum, limit = item.unknown_words
        if item.count != 1 or not 0 <= current <= maximum <= limit <= 65535:
            raise ValueError('Invalid battery state')
    return result


def energy(inventory: bytes | None) -> tuple[int, int]:
    cells = batteries(inventory)
    return (min(65535, sum(i.unknown_words[0] for i in cells)),
            min(65535, sum(i.unknown_words[1] for i in cells)))


def project_energy(packet: bytes, human: bool, inventory: bytes | None) -> bytes:
    pet = decode_pet_info(packet, human_equipment=human)
    current, maximum = energy(inventory)
    if pet.fields['0x8c446f'] not in (1, 2):
        current = maximum = 0
    fields = {**pet.fields, '0x8c4b2b': maximum, '0x8c4b41': current}
    return encode_pet_info(replace(pet, fields=fields))


def spend(inventory: bytes, count: int, seconds: float,
          remainder: Fraction) -> tuple[bytes, Fraction]:
    if (type(count) is not int or not 0 <= count <= 4 or not math.isfinite(seconds)
            or not 0 <= seconds <= 3600 or not 0 <= remainder < 1):
        raise ValueError('Invalid battery debit')
    debt = Fraction(str(seconds))*count+remainder
    whole = int(debt)
    owner, items, flag = decode_item_list(inventory)
    updated = {item.instance_id: item for item in items}
    for battery in sorted(batteries(inventory), key=lambda i: i.instance_id):
        current, maximum, limit = battery.unknown_words
        taken = min(current, whole)
        whole -= taken
        updated[battery.instance_id] = replace(battery, unknown_words=(current-taken, maximum, limit))
    return encode_item_list(owner, tuple(updated.values()), flag), debt-int(debt)


def recharge(battery: ItemRecord) -> tuple[ItemRecord, int]:
    batteries(encode_item_list(0, (battery,)))
    if battery.template_id != policy()['battery']['template'] or battery.equipped:
        raise ValueError('Нужна собственная батарея')
    current, maximum, limit = battery.unknown_words
    if current >= maximum:
        raise ValueError('Зарядка батареи не требуется')
    loss = ((maximum-current)*policy()['battery']['capacity_loss_percent']+99)//100
    capacity = max(current, maximum-loss)
    if capacity <= current:
        raise ValueError('Ресурс батареи исчерпан')
    return (replace(battery, unknown_words=(capacity, capacity, limit)),
            (capacity-current)*policy()['battery']['crystals_per_point'])
