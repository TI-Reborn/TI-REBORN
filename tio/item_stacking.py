"""User-selected stack policy; merge only identical, loose item instances.

Counts are units, never shop packs. Location, ownership and item metadata remain
separate. The first instance survives, so existing destination IDs stay usable.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import sqlite3

from .protocol.item_list import decode_item_list, encode_item_list

# Original items.cfg ammunition IDs, excluding Missile8 by user request.
AMMUNITION = frozenset((3, 4, 5, 6, 7, 12, 13, 14, 15, 36, 37))
MEDICAL = frozenset((9, 34))  # Bandages, Candies only.
ENCOUNTER_MATERIALS = frozenset((65487,65488))
STACKABLE = AMMUNITION | MEDICAL | ENCOUNTER_MATERIALS
# Native UI calculations use signed Delphi integers. Leave another stack when
# combining would exceed their positive range; never truncate quantities.
MAX_STACK = 0x7fffffff


def stack_key(item):
    if (item.template_id not in STACKABLE or item.equipped or item.slot
            or item.count < 1 or item.optional_u32 is not None
            or any(item.unknown_bytes_02[2:])):
        return None
    return replace(item, instance_id=0, unknown_u32_01=0)


def merge_stacks(items):
    result, groups, seen = [], {}, set()
    for item in items:
        if item.instance_id in seen:
            raise ValueError('Duplicate item instance ID')
        seen.add(item.instance_id)
        key = stack_key(item)
        remaining = item.count
        if key is not None:
            for index in groups.get(key, ()):
                old = result[index]
                moved = min(remaining, max(0, MAX_STACK - old.count))
                if moved:
                    result[index] = replace(old, unknown_u32_01=old.count + moved)
                    remaining -= moved
                if not remaining:
                    break
        if remaining or key is None:
            if key is not None:
                groups.setdefault(key, []).append(len(result))
            result.append(replace(item, unknown_u32_01=remaining))
    return tuple(result)


def compact_saved_items(path, account):
    """Login-only migration, before any IDs are sent to a client/battle.

    Preserve old snapshots in the same transaction for recovery. Reserve ALL
    prior IDs, including absorbed ones, so stale actions cannot target new goods.
    Never combine locations or accounts. Repeated login is a no-op.
    """
    from .warehouse import WarehouseStore
    from .owned_pets import OwnedPetStore
    WarehouseStore._account(account)
    WarehouseStore(path)
    with closing(connect(path)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets '
                          'WHERE account=? ORDER BY pet_id', (account,)).fetchall()
        warehouse = WarehouseStore._read(db, account)
        seen = set(warehouse)
        updates = []
        for owner, human, pet, packet in rows:
            if OwnedPetStore.validate(pet, packet, bool(human)) != owner:
                raise ValueError('Invalid owned inventory')
            _, items, flag = decode_item_list(packet)
            for item in items:
                if item.instance_id in seen:
                    raise ValueError('Item ID exists in multiple locations')
                seen.add(item.instance_id)
            merged = merge_stacks(items)
            if merged != items:
                updates.append((owner, packet, encode_item_list(owner, merged, flag)))
        merged_warehouse = merge_stacks(warehouse.values())
        changed_warehouse = merged_warehouse != tuple(warehouse.values())
        if not updates and not changed_warehouse:
            return {'inventories': 0, 'warehouse': False}
        from .protocol.warehouse import encode_private_warehouse_snapshot
        encode_private_warehouse_snapshot(merged_warehouse)
        db.execute('CREATE TABLE IF NOT EXISTS item_stack_backups '
                   '(account TEXT NOT NULL, location TEXT NOT NULL, owner_id INTEGER NOT NULL, '
                   'packet BLOB NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
        for owner, before, after in updates:
            db.execute('INSERT INTO item_stack_backups(account,location,owner_id,packet) VALUES (?,?,?,?)',
                       (account, 'inventory', owner, before))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (after, account, owner))
        if changed_warehouse:
            for identity, item in warehouse.items():
                db.execute('INSERT INTO item_stack_backups(account,location,owner_id,packet) VALUES (?,?,?,?)',
                           (account, 'warehouse', identity, encode_item_list(0, (item,))))
            db.execute('DELETE FROM warehouse_items WHERE account=?', (account,))
            db.executemany('INSERT INTO warehouse_items VALUES (?,?,?)',
                           ((account, i.instance_id, encode_item_list(0, (i,))) for i in merged_warehouse))
        db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                   'DO UPDATE SET next_id=MAX(next_id,excluded.next_id)', (account, max(seen, default=0)+1))
        return {'inventories': len(updates), 'warehouse': changed_warehouse}
