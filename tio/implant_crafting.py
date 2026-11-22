"""Atomic storage for authenticated implant workshop actions."""
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
import secrets

from .db_transaction import transaction
from .implant_combining import combine, prepare
from .implant_equipment import limit_health
from .implants import place, project_inventory
from .item_ids import next_item_id
from .owned_pets import OwnedPetStore
from .passive_stats import project_saved_pet
from .protocol.implant_crafting import decode_request, encode_result
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.pet_info import decode_pet_info


def craft(path: str | Path, account: str, packet: bytes, *, allow_mutation: bool,
          randbelow: Callable[[int], int] = secrets.randbelow) -> tuple[bytes, ...]:
    identities = decode_request(packet)
    if not account or not allow_mutation:
        raise ValueError('Мастерская имплантов доступна только в городе')
    with transaction(path) as db:
        inventories, located = {}, {}
        for owner, human, raw, inventory in db.execute(
                'SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=?', (account,)):
            if OwnedPetStore.validate(raw, inventory, bool(human)) != owner:
                raise ValueError('Invalid inventory owner')
            _, items, flag = decode_item_list(inventory)
            inventories[owner] = bool(human), raw, items, flag
            for item in items:
                if item.instance_id in located:
                    raise ValueError('Ambiguous inventory item ID')
                located[item.instance_id] = owner, item
        if any(identity not in located for identity in identities):
            raise ValueError('Имплант не принадлежит аккаунту или уже израсходован')
        sources = [located[identity] for identity in identities]
        if len({owner for owner, _ in sources}) != 1:
            raise ValueError('Оба импланта должны находиться у одного бойца')
        installed = [(owner, item) for owner, item in sources if item.equipped]
        if len({owner for owner, _ in installed}) > 1:
            raise ValueError('Установленные исходники должны принадлежать одному бойцу')
        owner = installed[0][0] if installed else sources[0][0]
        human, raw, _, _ = inventories[owner]
        if not human:
            raise ValueError('Импланты доступны только людям')
        from .bank_economy import assert_item_mutation
        for _, item in sources:
            assert_item_mutation(db, account, item.instance_id, 'destroy')
        # Allocate before removing sources so consumed IDs can never be reused.
        identity = next_item_id(db, account)
        if installed:
            preview = replace(prepare(sources[0][1], sources[1][1]), instance_id=identity)
            remaining = tuple(i for i in inventories[owner][2] if i.instance_id not in identities)
            profile = decode_pet_info(project_saved_pet(db, account, owner, raw, human), human_equipment=human)
            place(profile.fields, (*remaining, preview), identity, installed[0][1].client_slot)
        result = combine(sources[0][1], sources[1][1], randbelow)
        replacements = {}
        for changed_owner in {o for o, _ in sources}:
            _, _, items, flag = inventories[changed_owner]
            replacements[changed_owner] = tuple(i for i in items if i.instance_id not in identities)
        if result is not None:
            result = replace(result, instance_id=identity)
            updated = (*replacements[owner], result)
            if installed:
                profile = decode_pet_info(project_saved_pet(db, account, owner, raw, human),
                                          human_equipment=human)
                updated = place(profile.fields, updated, identity, installed[0][1].client_slot)
            from .inventory_capacity import validate_capacity
            validate_capacity(inventories[owner][2], updated)
            replacements[owner] = updated
        db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
        db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                   'DO UPDATE SET next_id=MAX(next_id,excluded.next_id)', (account, identity+1))
        replies = []
        for changed_owner in sorted(replacements):
            human, raw, _, flag = inventories[changed_owner]
            inventory = encode_item_list(changed_owner, replacements[changed_owner], flag)
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (inventory, account, changed_owner))
            profile = limit_health(db, account, changed_owner, human, raw)
            fields = decode_pet_info(profile, human_equipment=human).fields
            replies.extend((project_inventory(inventory, fields), profile))
        replies.append(encode_result(None if result is None else result.template_id,
                                     0 if result is None else result.unknown_bytes_03[0]))
        return tuple(replies)
