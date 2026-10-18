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
from . import warehouse_completion as completion


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
            db.execute('BEGIN') if not db.in_transaction else None
            completion.schema(db)

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
            db.execute('BEGIN')
            return tuple(completion.read_scope(db, account).values())

    def exchange(self, account, pet_id, *, deposits=(), withdrawals=()):
        """Atomically exchange item quantities; reject unavailable quantities.

        Returns the updated pet inventory and private warehouse items. Caller
        chooses protocol responses only after this transaction has committed.
        """
        self._account(account)
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            try:
                return completion.exchange(db, account, pet_id, deposits=deposits, withdrawals=withdrawals)
            except ValueError as exc:
                raise WarehouseRejected(str(exc)) from exc
