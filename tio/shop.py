"""Atomic native item shop purchases/sales on the shared account database."""

from .db_transaction import connect
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from functools import partial
import sqlite3
import json
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .warehouse import WarehouseStore
from . import warehouse_completion as completion
from .protocol.asset_count import AssetCount, encode_asset_count
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.shop_purchase import encode_shop_purchase
from .protocol.shop_sale import encode_sale_request
from .protocol.warehouse import encode_private_warehouse_snapshot
from .item_stacking import merge_stacks, stack_key
from .inventory_capacity import validate_capacity
from .shop_completion import ShopCompletion
from .item_ids import next_item_id

# The A2 shop sends owner 0 for "buy to warehouse"; mercenary IDs start at 1.
WAREHOUSE = 0


class PurchaseRejected(ValueError):
    pass


@dataclass(frozen=True)
class PurchaseResult:
    inventory: bytes
    assets: AssetCount
    charged_credits: int
    charged_gold: int = 0
    operation_id: str | None = None

    def packets(self) -> tuple[bytes, ...]:
        return (self.inventory, encode_asset_count(self.assets))


@dataclass(frozen=True)
class WarehousePurchaseResult:
    warehouse: tuple[ItemRecord, ...]
    assets: AssetCount
    charged_credits: int
    charged_gold: int = 0
    operation_id: str | None = None

    def packets(self) -> tuple[bytes, ...]:
        return (*encode_private_warehouse_snapshot(self.warehouse), encode_asset_count(self.assets))


class ShopStore:
    def __init__(self, path, catalogs):
        self.path = path
        self.catalogs = catalogs
        self.completion = ShopCompletion(path, catalogs)
        OwnedPetStore(path)
        WalletStore(path)
        WarehouseStore(path)
        with closing(connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS shop_receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL,operation TEXT NOT NULL,
                identity TEXT,request TEXT NOT NULL,inventory BLOB,credits INTEGER,gold INTEGER,
                charged_credits INTEGER,charged_gold INTEGER,UNIQUE(account,identity))''')
            for operation in ('UPDATE','DELETE'):
                db.execute(f'''CREATE TRIGGER IF NOT EXISTS shop_receipts_no_{operation.lower()}
                    BEFORE {operation} ON shop_receipts WHEN OLD.inventory IS NOT NULL
                    BEGIN SELECT RAISE(ABORT,'Shop receipts are immutable'); END''')

    def _completed(self, method, *args, **kwargs):
        try:
            return getattr(self.completion, method)(*args, **kwargs)
        except ValueError as exc:
            raise PurchaseRejected(str(exc)) from exc

    def catalog(self, account, category, *, gold=False, discounted=False):
        return self._completed('catalog', account, category, gold=gold, discounted=discounted)

    @staticmethod
    def _identity(identity):
        if identity is not None and (not isinstance(identity,str) or not 1<=len(identity)<=160
                                    or any(ord(c)<32 for c in identity)):
            raise PurchaseRejected('Invalid server shop operation identity')

    @classmethod
    def _prior(cls,db,account,operation,identity,request,owner):
        cls._identity(identity)
        if identity is None:return None
        row=db.execute('''SELECT id,request,inventory,credits,gold,charged_credits,charged_gold,operation
            FROM shop_receipts WHERE account=? AND identity=?''',(account,identity)).fetchone()
        if row is None:return None
        if row[7]!=operation or row[1]!=request:raise PurchaseRejected('Conflicting shop operation retry')
        if row[2] is None:raise PurchaseRejected('Incomplete shop receipt')
        if operation=='purchase' and owner==WAREHOUSE:
            wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            if wallet is None:raise PurchaseRejected('Shop recipient no longer exists')
            stored=tuple(completion.read_scope(db,account).values())
            return WarehousePurchaseResult(stored,AssetCount(*wallet),row[5],row[6],f'shop:{row[0]}')
        current=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
        if current is None or wallet is None:raise PurchaseRejected('Shop recipient no longer exists')
        # Return the current private snapshot after intervening actions, while
        # preserving the original charge/operation identity. Never restore saves.
        return PurchaseResult(bytes(current[0]),AssetCount(*wallet),row[5],row[6],f'shop:{row[0]}')

    @staticmethod
    def _begin(db,account,operation,identity,request):
        # Original native shop packets have no transaction nonce. A new legacy
        # call is a distinct accepted order; optional identity is server-owned.
        return db.execute('INSERT INTO shop_receipts(account,operation,identity,request) VALUES (?,?,?,?)',
                          (account,operation,identity,request)).lastrowid

    @staticmethod
    def _finish(db,receipt_id,inventory,balances,charged_credits,charged_gold=0,*,result=None):
        db.execute('''UPDATE shop_receipts SET inventory=?,credits=?,gold=?,charged_credits=?,charged_gold=?
            WHERE id=? AND inventory IS NULL''',(inventory,*balances,charged_credits,charged_gold,receipt_id))
        make=result or partial(PurchaseResult,inventory)
        return make(AssetCount(*balances),charged_credits,charged_gold,f'shop:{receipt_id}')

    @staticmethod
    def _sale_town(db,account,town):
        if town is not None and (type(town) is not int or not 0<=town<=0xffffffff):
            raise PurchaseRejected('Invalid authoritative sale town')
        row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='character_locations'").fetchone() else None
        if row is not None:
            if type(row[0]) is not int or row[0]<0:raise PurchaseRejected('Shop sales require the city')
            if town is not None and town!=row[0]:raise PurchaseRejected('Sale town changed')
            return row[0]
        return 0 if town is None else town  # Legacy saves without city state retain untaxed sales.

    def sell(self, account, request, *, quote=False,identity=None,town=None):
        if not isinstance(account, str) or not account:
            raise PurchaseRejected('Account required')
        encode_sale_request(request)
        if request.quantity < 1:
            raise PurchaseRejected('Positive sale quantity required')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            payload=json.dumps(dict(packet=encode_sale_request(request).hex(),town=town),sort_keys=True)
            if not quote:
                prior=self._prior(db,account,'sale',identity,payload,request.owner_id)
                if prior is not None:return prior
            self._completed('town',db,account)
            sale_town=self._sale_town(db,account,town)
            wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             (account, request.owner_id)).fetchone()
            if wallet is None or row is None:
                raise PurchaseRejected('Wallet or owned recipient missing')
            OwnedPetStore.validate(row[1], row[2], bool(row[0]))
            owner, items, unknown = decode_item_list(row[2])
            item = next((i for i in items if i.instance_id == request.instance_id), None)
            if item is None:
                raise PurchaseRejected('Sale item missing or unsupported')
            from .bank_economy import assert_item_mutation
            assert_item_mutation(db,account,item.instance_id,'sell')
            from .item_boosters import nontransferable
            if nontransferable(item.template_id):raise PurchaseRejected('Предметный бустер нельзя продать')
            if request.quantity > item.count or (stack_key(item) is None and (item.count != 1 or request.quantity != 1)):
                raise PurchaseRejected('Invalid sale quantity')
            offers = [o for group in self.catalogs.items.values() for o in group if o.item_id == item.template_id]
            from .encounter_loot import material_sale
            material_proceeds=material_sale(item,request.quantity)
            if material_proceeds is None and len(offers) != 1:
                raise PurchaseRejected('Ambiguous sale price')
            gross = (material_proceeds if material_proceeds is not None else
                     self._completed('sale_gross', item, request.quantity, offers[0]))
            from .clan_benefits import sales_quote,sales_tax
            if quote:
                return sales_quote(db,sale_town,gross)['net']
            updated = tuple(replace(i, unknown_u32_01=i.count-request.quantity) if i == item else i
                            for i in items if i != item or i.count > request.quantity)
            inventory = encode_item_list(owner, updated, unknown)
            receipt_id=self._begin(db,account,'sale',identity,payload)
            proceeds=sales_tax(db,account,f'shop:{receipt_id}',sale_town,gross)['net']
            if wallet[0] + proceeds > 0xffffffff:
                raise PurchaseRejected('Credit balance overflow')
            # Preserve the deleted ID even when this is a legacy inventory seed.
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',
                       (account, item.instance_id+1))
            db.execute('UPDATE wallets SET credits=? WHERE account=?', (wallet[0]+proceeds, account))
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                       (inventory, account, owner))
            from .achievements import update
            update(db,account,maximum={'credits_peak':wallet[0]+proceeds})
            result=self._finish(db,receipt_id,inventory,(wallet[0]+proceeds,wallet[1]),-proceeds)
        return result

    def purchase_premium(self, account, packet, *, identity=None):
        from .protocol.premium_shop import decode_premium_purchase
        from .protocol.shop_purchase import ShopPurchase
        owner, category, offer, quantity, revision = decode_premium_purchase(packet)
        if category not in (0, 1):
            raise PurchaseRejected('Premium catalog changed; reopen shop')
        return self.purchase(account, ShopPurchase(owner, category, offer, quantity), _gold=True,
                             identity=identity,_premium_revision=revision)

    def purchase(self, account, request, *, _gold=False,identity=None,_premium_revision=None):
        if not isinstance(account, str) or not account:
            raise PurchaseRejected('Account required')
        encode_shop_purchase(request)  # Reject invalid widths before any mutation.
        if not 1 <= request.quantity <= 1000:
            raise PurchaseRejected('Quantity must be 1..1000 (local policy)')
        if _gold and request.owner_id == WAREHOUSE:
            raise PurchaseRejected('Premium purchases require a mercenary')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            operation='premium' if _gold else 'purchase'
            payload=json.dumps(dict(packet=encode_shop_purchase(request).hex(),revision=_premium_revision),sort_keys=True)
            prior=self._prior(db,account,operation,identity,payload,request.owner_id)
            if prior is not None:return prior
            if _gold:
                if _premium_revision is not None and _premium_revision!=self.catalogs.price_revision:
                    raise PurchaseRejected('Premium catalog changed; reopen shop')
                from .protocol.city_catalogs import ShopItem
                offers = [ShopItem(o.offer_id, o.pack_count, o.item_id, o.gold, o.durability, 0)
                          for o in self._completed('offers',db,account,request.category,gold=True) if o.offer_id == request.offer_id]
            else:
                offers = [o for o in self._completed('offers',db,account,request.category)
                          if o.unknown_u32_01 == request.offer_id]
            if len(offers) != 1:raise PurchaseRejected('Unknown or ambiguous offer')
            offer = offers[0]
            wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            if wallet is None:
                raise PurchaseRejected('Wallet or owned recipient missing')
            currency = 0  # both native shop tabs debit credits
            from .premium import discount
            # Discount each displayed pack, rounding up in the indivisible currency.
            cost=discount(db,account,offer.unknown_u32_03)*request.quantity
            if wallet[currency] < cost:
                raise PurchaseRejected('Insufficient credits')
            # IDs are unique across this account's pets, warehouse and sequence.
            highest = next_item_id(db, account) - 1
            additions, next_id = self._completed('additions',offer.item_id,offer.unknown_u32_02,
                                                   offer.durability,request.quantity,highest+1)
            # Serialization/capacity errors happen before either balance or inventory changes.
            deliver = _to_warehouse if request.owner_id == WAREHOUSE else _to_soldier
            delivery = deliver(db, account, request.owner_id, additions)
            self._completed('consume',db,account,offer,request.quantity,gold=_gold)
            receipt_id=self._begin(db,account,operation,identity,payload)
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',
                       (account, next_id))
            balances = list(wallet)
            balances[currency] -= cost
            db.execute('UPDATE wallets SET credits=?,gold=? WHERE account=?', (*balances, account))
            delivery.persist()
            from .achievements import update,event,influence_received
            if _gold:
                from .clan_benefits import premium_gold_spent
                contribution=premium_gold_spent(db,account,f'shop:{receipt_id}',cost//100)
                influence_received(db,account,f'gold:shop:{receipt_id}',contribution['amount'])
            event(db,account,f'shop:{receipt_id}',add={'premium_purchase' if _gold else 'shop_purchase':1})
            update(db,account,maximum={'credits_peak':wallet[0]})
            result=self._finish(db,receipt_id,delivery.receipt,balances,cost,0,result=delivery.result)
        return result


@dataclass(frozen=True)
class _Delivery:
    """Validated destination change; persisted only after the charge is recorded."""
    receipt: bytes
    persist: Callable[[], None]
    result: Callable[..., 'PurchaseResult | WarehousePurchaseResult']


def _to_soldier(db, account: str, owner: int, additions) -> _Delivery:
    row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                     (account, owner)).fetchone()
    if row is None:
        raise PurchaseRejected('Wallet or owned recipient missing')
    OwnedPetStore.validate(row[1], row[2], bool(row[0]))
    pet, items, unknown = decode_item_list(row[2])
    merged = merge_stacks(items + additions)
    validate_capacity(items, merged, error=PurchaseRejected)
    inventory = encode_item_list(pet, merged, unknown)

    def persist():
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (inventory, account, pet))
    return _Delivery(inventory, persist, partial(PurchaseResult, inventory))


def _to_warehouse(db, account: str, owner: int, additions) -> _Delivery:
    try:
        before = completion.read_scope(db, account, required=True)
        stored, assignments = completion.merge_scope(db, account, (*before.values(), *additions), before,
                                                     origin='shop-purchase')
        stored = tuple(sorted(stored, key=lambda item: item.instance_id))
        encode_private_warehouse_snapshot(stored)
    except ValueError as exc:
        raise PurchaseRejected(str(exc)) from exc

    def persist():
        completion.persist_scope(db, account, before, stored, assignments)
    return _Delivery(encode_item_list(WAREHOUSE, stored), persist, partial(WarehousePurchaseResult, stored))
