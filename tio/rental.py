"""Timed rentals. Absolute UTC deadlines are authoritative; wire time is seconds left."""

from .db_transaction import connect
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import time

from .enhancement import EnhancementRules, ROOT
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .warehouse import WarehouseStore
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.rental import RentalOffer, encode_rental_catalog, decode_rental_request
from .protocol.asset_count import AssetCount, encode_asset_count
from .protocol.warehouse import encode_private_warehouse_snapshot


def eligible_rental_items(rules):
    """Manual p31: durable weapons/armor, including dog and miner equipment.

    Natural attacks, body models and ordinary consumables are already absent
    from enhancement equipment. Suicide Jacket is also armor, but its suicide
    attack is consumable equipment rather than a reusable rental weapon.
    """
    from .weapons import WeaponCatalog
    sources=WeaponCatalog().sources
    return {identity:rule for identity,rule in rules.items.items()
            if sources.get(identity,{}).get('weaponAttack')!='Suicide'}


def rental_tax_units(inventory):
    """Manual: 22.5% per worn rental, full-body armor counts as three."""
    import xml.etree.ElementTree as ET
    complex_armor = {int(n.get('id')) for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot()
                     if any(v.get('key') == 'bodypart' and v.get('val') == 'complexarmor' for v in n)}
    return min(4, sum(3 if i.template_id in complex_armor else 1
                      for i in decode_item_list(inventory)[1] if i.equipped and i.unknown_bytes_02[3]))


def training_rental_tax(gross, units):
    """Local fixed team reward: equal shares per mercenary, floor once at the end."""
    units = tuple(units)
    return gross * 225 * sum(units) // (1000 * len(units)) if units else 0


class RentalStore:
    def __init__(self, path, catalog_path=ROOT/'config/rental_catalog.json', *, clock=time.time):
        self.path, self.clock = path, clock
        self.rules = EnhancementRules()
        eligible=eligible_rental_items(self.rules)
        data = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
        self.offers = {}
        for template in data['items']:
            if type(template) is not int or template not in eligible:
                raise ValueError('Rental template must be eligible equipment')
            for level, prices in data['credits_by_level_and_hours'].items():
                level = int(level)
                if level not in (10, 15, 20):
                    raise ValueError('Unsupported rental enhancement')
                for hours, gold in prices.items():
                    hours = int(hours)
                    if hours not in (3, 4, 8, 24) or type(gold) is not int or not 0 < gold <= 0xffffffff:
                        raise ValueError('Invalid rental duration or Gold price')
                    lot = 300000 + template * 100 + level
                    key = (lot, hours)
                    if key in self.offers:
                        raise ValueError('Duplicate rental offer')
                    self.offers[key] = RentalOffer(lot, template, level, hours, gold, 0)
        self.catalog = encode_rental_catalog(tuple(self.offers.values()))
        OwnedPetStore(path)
        WalletStore(path)
        WarehouseStore(path)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS rentals (account TEXT NOT NULL, instance_id INTEGER NOT NULL, '
                       'lot_id INTEGER NOT NULL, expires_at INTEGER NOT NULL, PRIMARY KEY(account,instance_id))')

    def handle(self, account, packet, *, allow_mutation=True):
        WarehouseStore._account(account)
        action, fields = decode_rental_request(packet)
        if action == 14:
            return (self.catalog,)
        if not allow_mutation:
            raise ValueError('Rental purchases require the city')
        lot, hours, recipient, currency = fields
        offer = self.offers.get((lot, hours))
        if offer is None:
            raise ValueError('Unknown rental offer or duration')
        if currency != 1:
            raise ValueError('Rental catalog accepts credits only')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             (account, recipient)).fetchone()
            if wallet is None or row is None:
                raise ValueError('Wallet or owned rental recipient missing')
            if wallet[0] < offer.credits:
                raise ValueError('Insufficient credits')
            if OwnedPetStore.validate(row[1], row[2], bool(row[0])) != recipient:
                raise ValueError('Invalid rental recipient inventory')
            owner, items, unknown = decode_item_list(row[2])
            seen = set(WarehouseStore._read(db, account))
            for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
                for item in decode_item_list(packet)[1]:
                    if item.instance_id in seen:
                        raise ValueError('Duplicate item ID across inventories')
                    seen.add(item.instance_id)
            # Also reserve leases whose items may have been removed by a future subsystem.
            seen.update(i for i, in db.execute('SELECT instance_id FROM rentals WHERE account=?', (account,)))
            sequence = db.execute('SELECT next_id FROM item_sequences WHERE account=?', (account,)).fetchone()
            identity = max(max(seen, default=0)+1, sequence[0] if sequence else 1)
            rule = self.rules.items[offer.item_id]
            durability = rule['durability'] + offer.enhancement * self.rules.config['durability_per_level']
            item = ItemRecord(identity, offer.item_id, bytes(2), 1, 0, 0, (durability,)*3,
                              bytes((offer.enhancement, 0, 0, 1)), hours*3600,
                              bytes((offer.enhancement, 0, int(rule['special']))))
            from .inventory_capacity import validate_capacity
            validate_capacity(items,items+(item,))
            inventory = encode_item_list(owner, items+(item,), unknown)
            assets = encode_asset_count(AssetCount(wallet[0]-offer.credits, wallet[1]))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (inventory, account, owner))
            db.execute('UPDATE wallets SET credits=credits-? WHERE account=?', (offer.credits, account))
            db.execute('INSERT INTO rentals VALUES (?,?,?,?)', (account, identity, lot, int(self.clock())+hours*3600))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) '
                       'DO UPDATE SET next_id=excluded.next_id', (account, identity+1))
            return (inventory, assets)

    def refresh(self, account, *, in_battle=False):
        """Refresh stored countdowns; publish removals. Never alter a battle CAS snapshot.

        Called at login and before city work/timed matchmaking, including idle ticks.
        An expired lease remains usable until the battle has settled.
        """
        if in_battle:
            return ()
        now = int(self.clock())
        replies = []
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            deadlines = dict(db.execute('SELECT instance_id,expires_at FROM rentals WHERE account=?', (account,)))
            if not deadlines:
                return ()
            def project(item):
                if item.instance_id not in deadlines:
                    return item
                remaining = deadlines[item.instance_id]-now
                return replace(item, optional_u32=remaining) if remaining > 0 else None
            for owner, packet in db.execute('SELECT pet_id,inventory_packet FROM owned_pets WHERE account=?', (account,)).fetchall():
                _, items, unknown = decode_item_list(packet)
                updated = tuple(p for i in items if (p := project(i)) is not None)
                if updated != items:
                    reply = encode_item_list(owner, updated, unknown)
                    db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (reply, account, owner))
                    if len(updated) != len(items):
                        replies.append(reply)
            warehouse = WarehouseStore._read(db, account)
            removed = False
            for identity, item in tuple(warehouse.items()):
                updated = project(item)
                if updated is None:
                    db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?', (account, identity))
                    del warehouse[identity]
                    removed = True
                elif updated != item:
                    warehouse[identity] = updated
                    db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',
                               (encode_item_list(0, (updated,)), account, identity))
            if removed:
                from .warehouse_completion import read_scope
                replies.extend(encode_private_warehouse_snapshot(read_scope(db,account,warehouse).values()))
            db.execute('DELETE FROM rentals WHERE account=? AND expires_at<=?', (account, now))
        return tuple(replies)
