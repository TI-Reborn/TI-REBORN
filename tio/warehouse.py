"""Persistent private warehouse; explicit server operations, not wire6B routing.

Item instances retain original ItemList data. Partial transfers keep the source
ID and allocate a new destination ID. Capacity is an explicit local policy.
"""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import sqlite3
from .owned_pets import OwnedPetStore
from .protocol.item_list import encode_item_list, decode_item_list
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity


class WarehouseRejected(ValueError):
    pass


class WarehouseStore:
    def __init__(self, path, *, capacity=None):
        if capacity is not None and (type(capacity) is not int or capacity < 1):
            raise WarehouseRejected('Positive server capacity required')
        self.path, self.capacity = path, capacity
        OwnedPetStore(path)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS warehouse_items '
                       '(account TEXT NOT NULL, instance_id INTEGER NOT NULL, '
                       'item_packet BLOB NOT NULL, PRIMARY KEY(account,instance_id))')
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')

    @staticmethod
    def _account(account):
        if not isinstance(account, str) or not account:
            raise WarehouseRejected('Account required')

    @staticmethod
    def _read(db, account):
        result = {}
        for key, packet in db.execute('SELECT instance_id,item_packet FROM warehouse_items '
                                      'WHERE account=? ORDER BY instance_id', (account,)):
            owner, items, _ = decode_item_list(packet)
            if owner != 0 or len(items) != 1 or items[0].instance_id != key:
                raise WarehouseRejected('Invalid stored warehouse item')
            item = items[0]
            if item.equipped or item.slot or item.count < 1:
                raise WarehouseRejected('Invalid warehouse item state')
            result[key] = item
        return result

    def items(self, account):
        self._account(account)
        with closing(connect(self.path)) as db:
            return tuple(self._read(db, account).values())

    def exchange(self, account, pet_id, *, deposits=(), withdrawals=()):
        """Atomically exchange item quantities; reject unavailable quantities.

        Returns the updated pet inventory and private warehouse items. Caller
        chooses protocol responses only after this transaction has committed.
        """
        self._account(account)
        if self.capacity is None:
            raise WarehouseRejected('Explicit capacity required for warehouse mutations')
        selections = []
        for pairs in (deposits, withdrawals):
            selection = {}
            for instance_id, count in pairs:
                if (type(instance_id) is not int or not 0 < instance_id <= 0xffffffff
                        or type(count) is not int or not 0 < count <= 0xffffffff
                        or instance_id in selection):
                    raise WarehouseRejected('Invalid or repeated item selection')
                selection[instance_id] = count
            selections.append(selection)
        deposits, withdrawals = selections
        if deposits.keys() & withdrawals.keys():
            raise WarehouseRejected('An item cannot move both ways')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets '
                             'WHERE account=? AND pet_id=?', (account, pet_id)).fetchone()
            if row is None or OwnedPetStore.validate(row[1], row[2], bool(row[0])) != pet_id:
                raise WarehouseRejected('Owned mercenary required')
            _, items, unknown = decode_item_list(row[2])
            inventory = {i.instance_id: i for i in items}
            if len(inventory) != len(items):
                raise WarehouseRejected('Duplicate inventory item IDs')
            warehouse = self._read(db, account)
            original_warehouse_ids = set(warehouse)
            # Existing duplication must never be legitimized by a transfer.
            seen = set(warehouse)
            for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
                for item in decode_item_list(packet)[1]:
                    if item.instance_id in seen:
                        raise WarehouseRejected('Item ID exists in multiple locations')
                    seen.add(item.instance_id)
            for selection, source in ((deposits, inventory), (withdrawals, warehouse)):
                for instance_id, count in selection.items():
                    item = source.get(instance_id)
                    if item is None:
                        raise WarehouseRejected('Selected item is not in the owned source')
                    if count > item.count:
                        raise WarehouseRejected('Insufficient item quantity')
                    if (item.equipped or item.slot) and count != item.count:
                        raise WarehouseRejected('Unequip item before transferring')
            sequence = db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
            next_id = max(max(seen,default=0)+1, sequence[0] if sequence else 1)
            def move(selection, source, destination):
                nonlocal next_id
                for key,count in selection.items():
                    item=source[key]
                    if source is inventory:
                        # Native equipment context menu sends a direct6B deposit.
                        # Clear placement atomically, after all validation succeeds.
                        item=replace(item,unknown_u8_01=0,location_raw=0)
                    if count == item.count:
                        source.pop(key)
                        destination[key]=item
                    else:
                        if next_id > 0xffffffff:
                            raise WarehouseRejected('Item ID space exhausted')
                        source[key]=replace(item,unknown_u32_01=item.count-count)
                        destination[next_id]=replace(item,instance_id=next_id,unknown_u32_01=count)
                        next_id+=1
            move(withdrawals,warehouse,inventory)
            move(deposits,inventory,warehouse)
            # Validate selected IDs before merging; fit quantities into existing
            # destination stacks before counting occupied warehouse slots.
            inventory = {i.instance_id: i for i in merge_stacks(inventory.values())}
            warehouse = {i.instance_id: i for i in merge_stacks(warehouse.values())}
            from .services import power
            if len(warehouse) > max(len(original_warehouse_ids),self.capacity+power(db,account,1)):
                raise WarehouseRejected('Warehouse capacity exceeded')
            validate_capacity(items,inventory,error=WarehouseRejected)
            updated = encode_item_list(pet_id, tuple(inventory.values()), unknown)
            # Validate the client snapshot before committing either location.
            from .protocol.warehouse import encode_private_warehouse_snapshot
            encode_private_warehouse_snapshot(warehouse.values())
            stored = {key: encode_item_list(0, (item,)) for key,item in warehouse.items()}
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (updated, account, pet_id))
            for key in original_warehouse_ids - warehouse.keys():
                db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?', (account, key))
            for key, packet in stored.items():
                db.execute('INSERT INTO warehouse_items VALUES (?,?,?) ON CONFLICT(account,instance_id) '
                           'DO UPDATE SET item_packet=excluded.item_packet', (account, key, packet))
            # Whole deposits also reserve their IDs from later shop purchases.
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                       'DO UPDATE SET next_id=excluded.next_id',(account,next_id))
        return updated, tuple(warehouse[key] for key in sorted(warehouse))
