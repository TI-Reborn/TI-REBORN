"""Provisional Gold SC store with atomic inventory, stock and cart persistence."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

from .protocol.binary import uint
from .protocol.sc_shop import SCOffer, encode_sc_catalog, encode_sc_basket, decode_sc_request
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.asset_count import AssetCount, encode_asset_count
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity
from .warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]


class SCShopStore:
    def __init__(self, path, catalog_path=ROOT / 'config/sc_catalog.json'):
        self.path = path
        data = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
        templates = {int(i.get('id')) for i in ET.parse(ROOT / 'evidence/items_diagnostic.xml').getroot()}
        self.offers, self.packs = {}, {}
        for row in data['offers']:
            lot, item = row['lot_id'], row['item_id']
            if lot in self.offers or not lot or item not in templates:
                raise ValueError('Duplicate SC lot or unknown item template')
            gold, stock, pack = row['gold'], row['stock_per_account'], row['pack_count']
            if not uint(gold, 32) or not uint(stock, 16) or not uint(pack, 32):
                raise ValueError('SC price, stock and pack must be positive')
            self.offers[lot] = SCOffer(lot, item, 0, stock, 0, gold, 0, gold, 0, row['durability'])
            self.packs[lot] = pack
        encode_sc_catalog(tuple(self.offers.values()))
        OwnedPetStore(path)
        WalletStore(path)
        WarehouseStore(path)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS sc_cart (account TEXT NOT NULL, lot_id INTEGER NOT NULL, '
                       'quantity INTEGER NOT NULL, PRIMARY KEY(account,lot_id))')
            db.execute('CREATE TABLE IF NOT EXISTS sc_sold (account TEXT NOT NULL, lot_id INTEGER NOT NULL, '
                       'quantity INTEGER NOT NULL, PRIMARY KEY(account,lot_id))')

    def _offers(self, db, account):
        sold = dict(db.execute('SELECT lot_id,quantity FROM sc_sold WHERE account=?', (account,)))
        return {lot: replace(o, available=max(0, o.available - sold.get(lot, 0)))
                for lot, o in self.offers.items()}

    def _cart(self, db, account, offers):
        rows = []
        for lot, n in db.execute('SELECT lot_id,quantity FROM sc_cart WHERE account=? ORDER BY lot_id', (account,)):
            if lot not in offers or not 1 <= n <= min(1000, offers[lot].available):
                raise ValueError('SC cart contains unavailable goods; remove them before checkout')
            rows.append((offers[lot], n))
        return tuple(rows)

    def handle(self, account, packet, *, allow_mutation=True):
        if not isinstance(account, str) or not account:
            raise ValueError('Account required')
        action, fields = decode_sc_request(packet)
        if action not in (4, 7, 12) and not allow_mutation:
            raise ValueError('SC purchases require the city and an owned recipient')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE' if action not in (4, 7, 12) else 'BEGIN')
            offers = self._offers(db, account)
            if action == 4:
                return (encode_sc_catalog(tuple(offers.values())),)
            if action == 7:
                return (encode_sc_basket(self._cart(db, account, offers)),)
            if action == 12:
                # Original B40D auxiliary option list; business semantics unrecovered.
                return (b'\xb4\x0d\x00\x00',)
            if action in (9, 10):
                lot, = fields
                if action == 9 and lot not in offers:
                    raise ValueError('Unknown SC offer')
                row = db.execute('SELECT quantity FROM sc_cart WHERE account=? AND lot_id=?', (account, lot)).fetchone()
                count = (row[0] if row else 0) + (1 if action == 9 else -1)
                if action == 9 and count > min(1000, offers[lot].available):
                    raise ValueError('SC stock or cart quantity limit exceeded')
                if count <= 0:
                    db.execute('DELETE FROM sc_cart WHERE account=? AND lot_id=?', (account, lot))
                else:
                    db.execute('INSERT INTO sc_cart VALUES (?,?,?) ON CONFLICT(account,lot_id) '
                               'DO UPDATE SET quantity=excluded.quantity', (account, lot, count))
                return (encode_sc_basket(self._cart(db, account, offers)),)
            if action == 6:
                lot, recipient, currency = fields
                if lot not in offers:
                    raise ValueError('Unknown SC offer')
                selection = ((offers[lot], 1),)
            else:  # B40B: checkout cart, recipient then payment mode.
                recipient, currency = fields
                selection = self._cart(db, account, offers)
            if currency != 2:
                raise ValueError('SC local catalog accepts Gold only')
            if not selection or sum(n for _, n in selection) > 1000:
                raise ValueError('Empty or oversized SC purchase')
            if any(n > o.available for o, n in selection):
                raise ValueError('SC stock exhausted')
            wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             (account, recipient)).fetchone()
            if wallet is None or row is None:
                raise ValueError('Wallet or owned SC recipient missing')
            cost = sum(o.gold * n for o, n in selection)
            if wallet[1] < cost:
                raise ValueError('Insufficient gold')
            if OwnedPetStore.validate(row[1], row[2], bool(row[0])) != recipient:
                raise ValueError('Invalid SC recipient inventory')
            owner, items, unknown = decode_item_list(row[2])
            seen = set(WarehouseStore._read(db, account))
            for snapshot, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
                for item in decode_item_list(snapshot)[1]:
                    if item.instance_id in seen:
                        raise ValueError('Duplicate item ID across owned inventories')
                    seen.add(item.instance_id)
            sequence = db.execute('SELECT next_id FROM item_sequences WHERE account=?', (account,)).fetchone()
            next_id = max(max(seen, default=0) + 1, sequence[0] if sequence else 1)
            additions = []
            for offer, quantity in selection:
                for _ in range(quantity):
                    additions.append(ItemRecord(next_id, offer.item_id, b'\0\0', self.packs[offer.lot_id],
                                                0, 0, (offer.durability,) * 3, bytes(4), None, bytes(3)))
                    next_id += 1
            merged=merge_stacks(items + tuple(additions))
            validate_capacity(items,merged)
            inventory = encode_item_list(owner, merged, unknown)
            assets = encode_asset_count(AssetCount(wallet[0], wallet[1] - cost))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (inventory, account, owner))
            db.execute('UPDATE wallets SET gold=? WHERE account=?', (wallet[1] - cost, account))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                       'DO UPDATE SET next_id=excluded.next_id', (account, next_id))
            for offer, quantity in selection:
                db.execute('INSERT INTO sc_sold VALUES (?,?,?) ON CONFLICT(account,lot_id) '
                           'DO UPDATE SET quantity=quantity+excluded.quantity', (account, offer.lot_id, quantity))
            if action == 11:
                db.execute('DELETE FROM sc_cart WHERE account=?', (account,))
            # Direct purchases can reduce the availability of an already carted lot.
            offers = self._offers(db, account)
            for lot, offer in offers.items():
                db.execute('UPDATE sc_cart SET quantity=MIN(quantity,?) WHERE account=? AND lot_id=?',
                           (offer.available, account, lot))
            db.execute('DELETE FROM sc_cart WHERE account=? AND quantity<=0', (account,))
            # Serialize every response before committing; failed serialization rolls back all changes.
            from .achievements import update
            update(db,account,add={'sc_purchase':1})
            return (inventory, assets, encode_sc_catalog(tuple(offers.values())),
                    encode_sc_basket(self._cart(db, account, offers)))
