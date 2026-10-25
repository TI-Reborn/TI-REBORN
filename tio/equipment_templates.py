"""Persistent C5 templates; owned-instance gear and counted supplies.

Application is one transaction across the recipient, personal warehouse and
template association. No gear is conjured or taken from another mercenary.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import asdict, replace
import json
import sqlite3

from .equipment import EquipmentStore, armor_rules
from .item_stacking import merge_stacks
from .owned_pets import OwnedPetStore
from .protocol.equipment_templates import (
    Element, Template, GEAR_SLOTS, decode_request, encode_list, encode_view,
    encode_created, encode_off, wide_name,
)
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .protocol.warehouse import encode_private_warehouse_snapshot
from .warehouse import WarehouseStore
from . import warehouse_completion as completion
from .weapons import WeaponCatalog
from .item_ids import next_item_id


def npc_type(pet):
    resource = pet.fields['0x8c446f']
    if resource in (1, 2): return 0
    if resource in (3, 4, 5): return 1
    if resource == 6: return 6
    raise ValueError('Неизвестный тип бойца')


def element(item, setting=0):
    return Element(item.instance_id, item.template_id, item.count, setting,
                   item.unknown_bytes_03[0], item.unknown_bytes_03[1],
                   item.unknown_words[0], item.unknown_words[1])


class EquipmentTemplateStore:
    def __init__(self, path, *, capacity=3000):
        self.path, self.capacity = path, capacity
        WarehouseStore(path)
        armor = armor_rules()
        rules = {i: (16, 128) for i in WeaponCatalog().weapons if i not in (300, 333, 337)}
        rules.update({i: (r['slot'],) for i, r in armor.items()})
        self.equipment = EquipmentStore(path, rules, armor=armor, weapons_only=True)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS equipment_templates '
                       '(id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, body TEXT NOT NULL)')

    @staticmethod
    def _templates(db, account):
        result = {}
        for identity, body in db.execute('SELECT id,body FROM equipment_templates WHERE account=? ORDER BY id', (account,)):
            data = json.loads(body)
            data['elements'] = tuple(Element(**e) for e in data['elements'])
            result[identity] = Template(**data)
        return result

    @staticmethod
    def _roster(db, account):
        result = {}
        for owner, human, pet, inv in db.execute(
                'SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=?', (account,)):
            if OwnedPetStore.validate(pet, inv, bool(human)) != owner:
                raise ValueError('Повреждён инвентарь бойца')
            result[owner] = (decode_pet_info(pet, human_equipment=bool(human)), decode_item_list(inv))
        return result

    @staticmethod
    def _all_items(roster, warehouse):
        owned = dict(warehouse)
        for _, (_, items, _) in roster.values():
            for item in items:
                if item.instance_id in owned:
                    raise ValueError('Повторный идентификатор вещи')
                owned[item.instance_id] = item
        return owned

    def _resolve(self, t, owned):
        wide_name(t.name)
        if not t.name.strip() or not 1 <= t.level <= 255 or t.npc_type not in (0, 1, 6) or t.remove_extra not in (0, 1):
            raise ValueError('Некорректное имя, уровень или тип шаблона')
        entries, seen = [], set()
        for index, e in enumerate(t.elements):
            if e.setting not in (0, 1, 2, 3):
                raise ValueError('Неизвестная настройка обслуживания вещи')
            if index in GEAR_SLOTS:
                if e.object_id:
                    item = owned.get(e.object_id)
                    if item is None or e.object_id in seen:
                        raise ValueError('Предмет экипировки отсутствует или выбран дважды')
                    if item.count != 1 or GEAR_SLOTS[index] not in self.equipment.rules.get(item.template_id, ()):
                        raise ValueError('Предмет не подходит для выбранного слота')
                    seen.add(e.object_id)
                    e = element(item, e.setting)
                else:
                    e = Element(setting=e.setting)
            elif e.item_id:
                if not 1 <= e.count <= 100000:
                    raise ValueError('Некорректное количество припасов')
                # Only client-derived items are accepted; no arbitrary catalog IDs.
                if not any(i.template_id == e.item_id for i in owned.values()):
                    raise ValueError('Предмет для шаблона не найден среди ваших вещей')
                e = replace(e, object_id=0)
            else:
                e = Element(setting=e.setting)
            entries.append(e)
        t = replace(t, name=t.name.strip(), elements=tuple(entries))
        encode_view(t)
        return t

    @staticmethod
    def _snapshot(t, pet, items):
        entries = [Element() for _ in range(7)]
        inverse = {slot: index for index, slot in GEAR_SLOTS.items()}
        supplies = {}
        for item in items:
            if item.equipped:
                if item.client_slot in inverse:
                    entries[inverse[item.client_slot]] = element(item)
            else:
                key = (item.template_id, item.unknown_bytes_03[1])
                supplies[key] = supplies.get(key, 0) + item.count
        entries.extend(Element(item_id=key[0], count=count, damage=key[1]) for key, count in supplies.items())
        return Template(t.name, pet.fields['0x8c4aef'], npc_type(pet), t.remove_extra, tuple(entries))

    @staticmethod
    def _associate(db, account, owner, pet, identity, name=''):
        fields = dict(pet.fields)
        fields['0x8c4f74'] = identity
        fields.pop('0x8c4f9c', None)
        if identity:
            fields['0x8c4f9c'] = name
        packet = encode_pet_info(replace(pet, fields=fields))
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?', (packet, account, owner))
        from .passive_stats import project_saved_pet
        return project_saved_pet(db, account, owner, packet, pet.human_equipment)

    def _apply(self, db, account, owner, identity, t, roster, warehouse, owned):
        pet, (_, original, flag) = roster[owner]
        if npc_type(pet) != t.npc_type or pet.fields['0x8c4aef'] < t.level:
            raise ValueError('Шаблон не подходит по типу или уровню бойца')
        local = {i.instance_id: i for i in original}
        pool = {**warehouse, **local}
        next_id = next_item_id(db, account, owned)
        selected = []
        reserved = {e.object_id for n, e in enumerate(t.elements) if n in GEAR_SLOTS and e.object_id}

        def take(key, count):
            nonlocal next_id
            item = pool[key]
            if count == item.count:
                del pool[key]
            else:
                pool[key] = replace(item, unknown_u32_01=item.count - count)
                item = replace(item, instance_id=next_id, unknown_u32_01=count)
                next_id += 1
            return replace(item, unknown_u8_01=0, location_raw=0)

        for index, e in enumerate(t.elements):
            if index in GEAR_SLOTS:
                if not e.object_id: continue
                if e.object_id not in pool:
                    raise ValueError('Вещь отсутствует на складе и у этого бойца (возможно, она у другого бойца)')
                item = pool[e.object_id]
                if e.setting in (1, 2) and item.unknown_words[0] < item.unknown_words[1]:
                    raise ValueError('Ремонт через шаблон пока недоступен: сначала почините вещь или отключите ремонт в шаблоне')
                selected.append(take(e.object_id, 1))
            elif e.item_id:
                missing = e.count
                # Prefer recipient's items; do not replace them unnecessarily.
                candidates = sorted(pool, key=lambda key: key not in local)
                for key in candidates:
                    item = pool[key]
                    if key in reserved or item.equipped or item.template_id != e.item_id or item.unknown_bytes_03[1] != e.damage:
                        continue
                    count = min(missing, item.count)
                    selected.append(take(key, count))
                    missing -= count
                    if not missing: break
                if missing:
                    if e.setting == 3:
                        raise ValueError('Автозакупка через шаблон пока недоступна: купите недостающие припасы в магазине')
                    raise ValueError(f'Недостаточно припасов: предмет {e.item_id}, не хватает {missing}')
        # The fixed slots describe a complete outfit. Implant slots are outside
        # this UI and remain attached to the recipient.
        extras, stored = [], []
        for key, item in pool.items():
            if key in local:
                if item.equipped and item.client_slot not in GEAR_SLOTS.values():
                    extras.append(item)
                    continue
                item = replace(item, unknown_u8_01=0, location_raw=0)
                if not t.remove_extra:
                    extras.append(item)
                    continue
            stored.append(item)
        result = tuple(selected + extras)
        for index, slot in GEAR_SLOTS.items():
            e = t.elements[index]
            if e.object_id:
                result = self.equipment.place(encode_pet_info(pet), pet.human_equipment, result, e.object_id, slot)
        # An overlapping complex-armor combination must not silently displace a
        # requested item after validation of another slot.
        for index, slot in GEAR_SLOTS.items():
            e = t.elements[index]
            if e.object_id and not any(i.instance_id == e.object_id and i.equipped and i.client_slot == slot for i in result):
                raise ValueError('Предметы шаблона занимают пересекающиеся слоты')
        result = merge_stacks(result)
        stored, assignments = completion.merge_scope(db, account, stored, warehouse, limit=self.capacity)
        from .inventory_capacity import validate_capacity
        validate_capacity(original,result)
        # City capacity and inherited overflow were checked by merge_scope.
        inventory = encode_item_list(owner, result, flag)
        warehouse_packets = encode_private_warehouse_snapshot(stored)
        completion.persist_scope(db, account, warehouse, stored, assignments)
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (inventory, account, owner))
        db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id', (account, next_id))
        pet_packet = self._associate(db, account, owner, pet, identity, t.name)
        return (inventory, *warehouse_packets, pet_packet)

    def handle(self, account, packet, *, allow_mutation=True):
        WarehouseStore._account(account)
        action, identity, owner, t = decode_request(packet)
        if action not in (None, 0) and not allow_mutation:
            raise ValueError('Шаблоны можно изменять и применять только вне боя и заявки')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            templates = self._templates(db, account)
            if action is None:
                return (encode_list(tuple(templates.items())),)
            if action != 3 and not (action == 4 and identity == 0) and identity not in templates:
                raise ValueError('Шаблон не найден')
            roster = self._roster(db, account)
            if action in (0, 4, 5) and owner not in roster:
                raise ValueError('Ваш боец не найден')
            warehouse = WarehouseStore._read(db, account)
            owned = self._all_items(roster, warehouse)
            if action == 0:
                original = templates[identity]
                entries = tuple(element(owned[e.object_id], e.setting)
                                if n in GEAR_SLOTS and e.object_id in owned else e
                                for n, e in enumerate(original.elements))
                return (encode_view(replace(original, elements=entries)),)
            if action == 4:
                if identity == 0:
                    pet_packet = self._associate(db, account, owner, roster[owner][0], 0)
                    return (encode_off(owner), pet_packet)
                return self._apply(db, account, owner, identity, templates[identity], roster, completion.read_scope(db, account, warehouse, required=True), owned)
            if action == 2:
                db.execute('DELETE FROM equipment_templates WHERE id=? AND account=?', (identity, account))
                del templates[identity]
                replies = []
                for pet_id, (pet, _) in roster.items():
                    if pet.fields['0x8c4f74'] == identity:
                        replies.extend((encode_off(pet_id), self._associate(db, account, pet_id, pet, 0)))
                # Reset the open editor too: the native list reader replaces
                # its data but does not clear the previously selected row.
                blank = Template('', 20, 0, 0, (Element(),)*7)
                return (*replies, encode_list(tuple(templates.items())), encode_created(0), encode_view(blank))
            if action == 5:
                pet, (_, items, _) = roster[owner]
                t = self._snapshot(templates[identity], pet, items)
            t = self._resolve(t, owned)
            body = json.dumps(asdict(t), ensure_ascii=False)
            if action == 3:
                if identity != 0 or len(templates) >= 200:
                    raise ValueError('Нельзя создать новый шаблон (лимит: 200)')
                identity = db.execute('INSERT INTO equipment_templates(account,body) VALUES (?,?)', (account, body)).lastrowid
            else:
                db.execute('UPDATE equipment_templates SET body=? WHERE account=? AND id=?', (body, account, identity))
            templates[identity] = t
            replies = []
            for pet_id, (pet, _) in roster.items():
                if pet.fields['0x8c4f74'] == identity:
                    replies.append(self._associate(db, account, pet_id, pet, identity, t.name))
            return (encode_list(tuple(templates.items())), encode_created(identity), encode_view(t), *replies)
