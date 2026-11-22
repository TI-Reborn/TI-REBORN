"""Atomic city implant installation/removal for an authenticated owner."""
from dataclasses import replace
from pathlib import Path
import sqlite3

from .db_transaction import transaction
from .owned_pets import OwnedPetStore
from .passive_stats import project_saved_pet
from .protocol.binary import Reader
from .protocol.item_action import ItemAction
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .implants import SLOTS, catalog, place, policy


def _save(db: sqlite3.Connection, account: str, owner: int, human: bool,
          raw: bytes, inventory: bytes) -> bytes:
    from .item_ids import next_item_id
    next_id = next_item_id(db, account)
    db.execute('CREATE TABLE IF NOT EXISTS item_sequences '
               '(account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
               'DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',
               (account, next_id))
    db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
               (inventory, account, owner))
    limit_health(db, account, owner, human, raw)
    return inventory


def limit_health(db: sqlite3.Connection, account: str, owner: int, human: bool,
                 raw: bytes) -> bytes:
    """Removing implant power/capacity must not retain hidden recoverable HP."""
    projected = decode_pet_info(project_saved_pet(db, account, owner, raw, human),
                                human_equipment=human)
    saved = decode_pet_info(raw, human_equipment=human)
    if saved.fields['0x8c4ab1'] > projected.fields['0x8c4a07']:
        saved.fields['0x8c4ab1'] = projected.fields['0x8c4a07']
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',
                   (encode_pet_info(saved), account, owner))
        projected.fields['0x8c4ab1'] = saved.fields['0x8c4ab1']
    return encode_pet_info(projected)


def city_profile(path: str | Path, account: str, inventory: bytes) -> bytes | None:
    """Refresh installed implant stats after buying/transferring/repairing power."""
    owner, items, _ = decode_item_list(inventory)
    if not any(i.equipped and i.template_id in catalog() for i in items):
        return None
    with transaction(path) as db:
        row = db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=?',
                         (account, owner)).fetchone()
        if row is None:
            raise ValueError('Боец не принадлежит аккаунту')
        return limit_health(db, account, owner, bool(row[0]), row[1])


def install(path: str | Path, account: str, action: ItemAction) -> bytes:
    if not isinstance(account, str) or not account:
        raise ValueError('Account required')
    with transaction(path) as db:
        row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets '
                         'WHERE account=? AND pet_id=?',
                         (account, action.pet_id)).fetchone()
        if row is None:
            raise ValueError('Боец не принадлежит вашему отряду')
        human, raw, inventory = bool(row[0]), row[1], row[2]
        owner = OwnedPetStore.validate(raw, inventory, human)
        if owner != action.pet_id:
            raise ValueError('Stored pet key differs from packet')
        pet = decode_pet_info(project_saved_pet(db, account, owner, raw, human),
                              human_equipment=human)
        _, items, flag = decode_item_list(inventory)
        changed = place(pet.fields, items, action.instance_id, action.target_mask)
        from .bank_economy import assert_item_mutation
        for item in items:
            if item not in changed and item.instance_id != action.instance_id:
                assert_item_mutation(db, account, item.instance_id, 'destroy')
        return _save(db, account, owner, human, raw, encode_item_list(owner, changed, flag))


def destroy(path: str | Path, account: str, packet: bytes) -> bytes:
    """Legacy API: C8/49 extracts an item with one owned Implant Extractor."""
    reader = Reader(packet)
    if reader.read(2) != b'\xc8\x49':
        raise ValueError('Expected implant removal C849')
    instance = reader.u32()
    reader.finish()
    return _remove_installed(path, account, instance)


def discard(path: str | Path, account: str, packet: bytes) -> bytes:
    """Native 32 destroys one installed implant without using an extractor."""
    reader = Reader(packet)
    if reader.u8() != 0x32:
        raise ValueError('Expected item discard 32')
    pet_id, instance, count = reader.u32(), reader.u32(), reader.u32()
    reader.finish()
    if not pet_id or count != 1:
        raise ValueError('Можно уничтожить один установленный имплант')
    return _remove_installed(path, account, instance, discard_from=pet_id)


def _remove_installed(path: str | Path, account: str, instance: int, *,
                      discard_from: int | None = None) -> bytes:
    if not isinstance(account, str) or not account or not instance:
        raise ValueError('Owned implant required')
    with transaction(path) as db:
        matches = []
        for owner, human, raw, inventory in db.execute(
                'SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets '
                'WHERE account=? AND (? IS NULL OR pet_id=?)', (account, discard_from, discard_from)):
            _, items, flag = decode_item_list(inventory)
            selected = next((item for item in items if item.instance_id == instance), None)
            if selected is not None:
                matches.append((owner, bool(human), raw, items, flag, selected))
        if len(matches) != 1:
            raise ValueError('Установленный имплант отсутствует')
        owner, human, raw, items, flag, selected = matches[0]
        if OwnedPetStore.validate(raw, encode_item_list(owner, items, flag), human) != owner:
            raise ValueError('Stored pet key differs from packet')
        if (not human or selected.template_id not in catalog() or selected.equipped != 1
                or selected.count != 1 or selected.client_slot not in SLOTS):
            raise ValueError('Можно снять только установленный имплант')
        from .bank_economy import assert_item_mutation
        if discard_from is not None:
            assert_item_mutation(db, account, instance, 'destroy')
            kept = tuple(item for item in items if item != selected)
            return _save(db, account, owner, human, raw, encode_item_list(owner, kept, flag))
        assert_item_mutation(db, account, instance, 'equip')
        extractor = next((item for item in items
                          if item.template_id == policy()['extraction']['template']
                          and item.count == 1 and not item.equipped and not item.slot
                          and item.unknown_words[0] > 0
                          and item.optional_u32 is None
                          and not any(item.unknown_bytes_02)
                          and not any(item.unknown_bytes_03)), None)
        if extractor is None:
            raise ValueError('Для извлечения нужен Implant Extractor в рюкзаке бойца')
        assert_item_mutation(db, account, extractor.instance_id, 'destroy')
        inventory = encode_item_list(owner, tuple(
            replace(item, unknown_u8_01=0, location_raw=0) if item == selected else item
            for item in items if item != extractor), flag)
        return _save(db, account, owner, human, raw, inventory)
