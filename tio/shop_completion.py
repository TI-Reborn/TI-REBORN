"""Manual shop completion; uncertain numeric rules are explicit versioned policy.

Stock is shared by city/offer/currency, never account. Helpers join the caller's
authoritative transaction. Catalog reads calculate due replenishment without
writes; only accepted purchases persist it. No hosted inventories are reseeded.
Native SC B4 fields are established ABI; availability65535 projects unlimited
stock and is not a claim about the historical sentinel. Native packets have no
nonce: optional operation identities must come from the server, not guessed
from an identical-looking later purchase.
"""
from contextlib import closing
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path
import json
import math
import time
import xml.etree.ElementTree as ET

from .db_transaction import connect
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.sc_shop import SCOffer, decode_sc_request, encode_sc_catalog, encode_sc_basket
from .protocol.asset_count import AssetCount, encode_asset_count
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .warehouse import WarehouseStore

ROOT = Path(__file__).resolve().parents[1]
WEEK = 604800
MONDAY = 345600  # 1970-01-05 UTC.


def _transaction(db):
    if not db.in_transaction:
        raise ValueError('Shop helper requires the authoritative transaction')


def _identity(identity):
    if identity is not None and (not isinstance(identity, str) or not 1 <= len(identity) <= 160
                                or any(ord(c) < 32 for c in identity)):
        raise ValueError('Invalid server shop operation identity')


class ShopCompletion:
    def __init__(self, path, catalogs=None, *, policy_path=None, clock=None):
        self.path, self.catalogs = path, catalogs
        self.clock = clock or time.time
        self.policy = json.loads(Path(policy_path or ROOT/'config/shop_completion.json').read_text(encoding='utf-8'))
        p = self.policy
        if (type(p['version']) is not int or not 1 <= p['version'] <= 127
                or p['sale'] != dict(percent=65, depreciation='current_over_theoretical', upgrade_kit_id=30)
                or p['sc']['enhancements'] != [0, 10, 15, 20, 25]
                or p['sc']['quantity_limit'] != 1000 or p['sc']['wire_unlimited'] != 65535
                or p['sc']['price'] != 'expected_self_upgrade_with_ready_premium'
                or p['sc']['retain_legacy_cart_terms'] is not True
                or p['sc']['retain_non_enhanceable_legacy_offers'] is not True):
            raise ValueError('Unsupported shop completion policy')
        self.towns = {int(k): v for k, v in p['town_max_level'].items()}
        if not self.towns or any(type(v) is not int or not 1 <= v <= 20 for v in self.towns.values()):
            raise ValueError('Invalid shop city band')
        for rule in p['stock'].values():
            if rule['mode'] == 'infinite':
                if set(rule) != {'mode'}: raise ValueError('Invalid infinite stock rule')
            elif rule['mode'] == 'weekly':
                if set(rule) != {'mode', 'capacity'}: raise ValueError('Invalid weekly stock rule')
            elif rule['mode'] == 'threshold':
                if (set(rule) != {'mode', 'capacity', 'threshold', 'delay_seconds'}
                        or type(rule['threshold']) is not int or not 0 <= rule['threshold'] < rule['capacity']
                        or type(rule['delay_seconds']) is not int or not 1 <= rule['delay_seconds'] <= WEEK):
                    raise ValueError('Invalid threshold stock rule')
            else: raise ValueError('Unknown stock replenishment mode')
            if rule['mode'] != 'infinite' and (type(rule['capacity']) is not int or not 1 <= rule['capacity'] <= 1000000):
                raise ValueError('Invalid stock capacity')
        self.prices = {r['item_id']: r for r in json.loads((ROOT/'config/original_shop_prices.json').read_text(encoding='utf-8'))['items']}
        from .credit_economy import item_prices
        for identity,p in item_prices().items():
            self.prices[identity]=dict(item_id=identity,credits=p['credits'],credit_pack=p['pack_count'],gold=None,gold_pack=None)
        self.values = {int(n.get('id')): {v.get('key'): v.get('val') for v in n.findall('value')}
                       for n in ET.parse(ROOT/'evidence/items_diagnostic.xml').getroot().iter('item')}
        for row in json.loads((ROOT/'config/battle_item_catalog_extension.json').read_text())['items']:
            self.values.setdefault(row['id'],{}).update(row['fields'])
        from .enhancement import EnhancementRules
        from .weapons import WeaponCatalog
        self.enhancement = EnhancementRules()
        from .sc_pricing import ReadySCPrices
        self.ready_prices = ReadySCPrices(self.policy['sc']['ready_price'], self.enhancement.config, self.policy['sc']['enhancements'])
        self.weapons = WeaponCatalog().weapons
        kit = self.prices[30]
        if (kit['credits'], kit['credit_pack']) != (1050, 1):
            raise ValueError('Documented kit valuation changed')
        with closing(connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS shop_global_stock (
                version INTEGER NOT NULL,town INTEGER NOT NULL,currency INTEGER NOT NULL,offer_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,week INTEGER NOT NULL,refill_at INTEGER,
                PRIMARY KEY(version,town,currency,offer_id))''')

    def stamp(self):
        now = self.clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now <= 2**53:
            raise ValueError('Invalid shop clock')
        return int(now)

    def town(self, db, account):
        _transaction(db)
        if not isinstance(account, str) or not account:
            raise ValueError('Account required')
        # Legacy saves without location rows retain their original Reservation
        # catalog. Travel/unknown locations never gain that fallback.
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='character_locations'").fetchone()
        row = db.execute('SELECT town_id FROM character_locations WHERE account=?', (account,)).fetchone() if exists else None
        town = row[0] if row else 3
        if type(town) is not int or town not in self.towns:
            raise ValueError('Магазин доступен только в городе')
        return town

    def allowed(self, template, town, *, gold=False):
        values = self.values.get(template)
        if values is None: return False
        return int(values.get('level_required', '1')) <= self.towns[town]

    def rule(self, template, gold):
        values = self.values[template]
        kind = ('premium' if gold else 'armor' if values.get('itype') == 'armor'
                else 'weapon' if template in self.weapons else 'ammo' if values.get('itype') == 'ammo' else 'supply')
        return self.policy['stock'][kind]

    def stock(self, db, town, currency, offer, template, *, now=None):
        """Return a pure stock projection; exhausted rows are hidden, not repacked."""
        _transaction(db)
        rule = self.rule(template, bool(currency))
        if rule['mode'] == 'infinite': return None
        now = self.stamp() if now is None else now
        week = MONDAY + ((now - MONDAY) // WEEK) * WEEK
        row = db.execute('SELECT quantity,week,refill_at FROM shop_global_stock WHERE version=? AND town=? AND currency=? AND offer_id=?',
                         (self.policy['version'], town, currency, offer)).fetchone()
        if row is None: return rule['capacity'], week, None
        quantity, prior_week, refill_at = row
        if (type(quantity) is not int or not 0 <= quantity <= rule['capacity'] or type(prior_week) is not int
                or (refill_at is not None and type(refill_at) is not int)):
            raise ValueError('Invalid authoritative shop stock')
        if ((rule['mode'] == 'weekly' and week > prior_week)
                or (rule['mode'] == 'threshold' and refill_at is not None and now >= refill_at)):
            return rule['capacity'], max(week, prior_week), None
        return quantity, prior_week, refill_at

    def consume(self, db, account, offer, quantity, *, gold=False):
        _transaction(db)
        town = self.town(db, account)
        if not self.allowed(offer.item_id, town, gold=gold):
            raise ValueError('Товар недоступен в этом городе')
        now = self.stamp()
        state = self.stock(db, town, int(gold), offer.unknown_u32_01, offer.item_id, now=now)
        if state is None: return
        remaining, week, refill_at = state
        if not 1 <= quantity <= remaining: raise ValueError('Товар закончился; обновите магазин')
        remaining -= quantity
        rule = self.rule(offer.item_id, gold)
        if rule['mode'] == 'threshold' and remaining < rule['threshold'] and refill_at is None:
            refill_at = now + rule['delay_seconds']
        db.execute('''INSERT INTO shop_global_stock VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(version,town,currency,offer_id) DO UPDATE SET quantity=excluded.quantity,week=excluded.week,refill_at=excluded.refill_at''',
                   (self.policy['version'], town, int(gold), offer.unknown_u32_01, remaining, week, refill_at))

    def offers(self, db, account, category, *, gold=False):
        _transaction(db)
        town = self.town(db, account)
        if self.catalogs is None: raise ValueError('City catalog required')
        offers = self.catalogs.premium_items if gold and category in (0, 1) else () if gold else self.catalogs.items.get(category, ())
        now = self.stamp()
        result = []
        for offer in offers:
            if not self.allowed(offer.item_id, town, gold=gold): continue
            identity = offer.offer_id if gold else offer.unknown_u32_01
            stock = self.stock(db, town, int(gold), identity, offer.item_id, now=now)
            if stock is None or stock[0] > 0: result.append(offer)
        return tuple(result)

    def catalog(self, account, category, *, gold=False, discounted=False):
        from .protocol.city_catalogs import encode_item_shop
        from .protocol.premium_shop import encode_premium_shop
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN')
            offers = self.offers(db, account, category, gold=gold)
            if gold:
                if discounted: offers = tuple(replace(o, gold=(o.gold*4+4)//5) for o in offers)
                return encode_premium_shop(category, self.catalogs.price_revision, offers)
            if discounted: offers = tuple(replace(o, unknown_u32_03=(o.unknown_u32_03*4+4)//5) for o in offers)
            return encode_item_shop(category, offers)

    def additions(self, template, pack, durability, quantity, first_id, *, enhancement=0):
        """One ammunition box per weapon; throwing weapons without ammo get none."""
        if type(quantity) is not int or not 1 <= quantity <= 1000: raise ValueError('Invalid purchase quantity')
        rule = self.enhancement.items.get(template)
        if enhancement and (rule is None or enhancement not in self.policy['sc']['enhancements']):
            raise ValueError('Unsupported SC enhancement')
        # Original B4 consumer writes the supplied durability to current/max;
        # enhanced offers therefore advertise the full value, not the +0 base.
        actual_durability = durability
        if enhancement and durability != rule['durability'] + enhancement*self.enhancement.config['durability_per_level']:
            raise ValueError('SC advertised durability differs from enhancement rules')
        ammo = self.weapons.get(template)
        ammo_id = ammo.ammo_id if ammo else None
        ammo_pack = None
        if ammo_id is not None:
            values = self.values[ammo_id]
            documented = self.prices.get(ammo_id)
            ammo_pack = (documented['credit_pack'] if documented and documented['credit_pack'] else int(values['packamount']))
            if not 1 <= ammo_pack <= 0xffffffff: raise ValueError('Invalid ammunition box')
        records = []
        next_id = first_id
        for _ in range(quantity):
            records.append(ItemRecord(next_id, template, bytes(2), pack, 0, 0, (actual_durability,)*3,
                                      bytes((enhancement, 0, 0, 0)), None,
                                      bytes((enhancement, 0, int(self.values[template].get('special') == '1') if enhancement else 0))))
            next_id += 1
            if ammo_id is not None:
                d = int(self.values[ammo_id].get('durability', '1'))
                records.append(ItemRecord(next_id, ammo_id, bytes(2), ammo_pack, 0, 0, (d,)*3, bytes(4), None, bytes(3)))
                next_id += 1
        if next_id > 0x100000000 or actual_durability > 65535: raise ValueError('Purchased item ID or durability overflow')
        return tuple(records), next_id

    def sale_gross(self, item, quantity, offer):
        """Documented65%, policylinear depreciation and kit value per real AP."""
        if (item.equipped or item.client_slot or any(item.unknown_bytes_01) or item.optional_u32 is not None
                or any(item.unknown_bytes_02[1:]) or item.unknown_bytes_03[1]
                or item.unknown_bytes_03[2] not in (0, 1)):
            raise ValueError('Экипированный, меченый, арендованный или неизвестно изменённый предмет нельзя продать')
        level = item.unknown_bytes_03[0]
        eligible = self.enhancement.items.get(item.template_id)
        if (level > 25 or item.unknown_bytes_02[0] > level
                or (level and eligible is None)
                or (item.unknown_bytes_03[2] and not self.values[item.template_id].get('special') == '1')):
            raise ValueError('Неизвестное улучшение предмета')
        expected = offer.durability + level*self.enhancement.config['durability_per_level']
        current, maximum, theoretical = item.unknown_words
        if theoretical != expected or not 0 <= current <= maximum <= expected or expected <= 0:
            raise ValueError('Некорректная прочность предмета')
        value = Fraction(offer.unknown_u32_03, offer.unknown_u32_02) + level*self.prices[30]['credits']
        return int(value * quantity * Fraction(65, 100) * Fraction(current, expected))

    def enhanced_offers(self):
        rows = {}
        for identity, rule in sorted(self.enhancement.items.items()):
            price = self.prices.get(identity)
            if price is None or not price['credits'] or price['credit_pack'] != 1: continue
            for level in self.policy['sc']['enhancements']:
                lot = 0x20000000 + self.ready_prices.revision*0x1000000 + level*65536 + identity
                credits = self.ready_prices.quote(price['credits'], self.prices[30]['credits'], level,
                                                 kind=rule['kind'], special=rule['special'])
                durability = rule['durability'] + level*self.enhancement.config['durability_per_level']
                rows[lot] = SCOffer(lot, identity, level, 65535, credits, 0, credits, 0, 0, durability)
        encode_sc_catalog(tuple(rows.values()))
        return rows


class CompletedSCShopStore:
    """Credit-only ready equipment with explicit, current basket prices."""
    def __init__(self, path, catalog_path=None, *, policy_path=None, clock=None):
        self.path = path
        self.completion = ShopCompletion(path, policy_path=policy_path, clock=clock)
        self.offers = self.completion.enhanced_offers()
        self.packs = {lot: 1 for lot in self.offers}
        legacy = json.loads(Path(catalog_path or ROOT/'config/sc_catalog.json').read_text(encoding='utf-8'))
        self.legacy = {r['lot_id']: (SCOffer(r['lot_id'], r['item_id'], 0, r['stock_per_account'], r['credits'], 0, r['credits'], 0, 0, r['durability']), r['pack_count']) for r in legacy['offers']}
        if set(self.legacy) & set(self.offers): raise ValueError('SC lot partition collision')
        # Preserve existing non-enhanceable +0 supplies and their explicit
        # provisional prices. A durability field alone never makes an item
        # eligible for an enhancement. Their old per-account sales are history.
        for lot, (offer, pack) in self.legacy.items():
            if offer.item_id not in self.completion.enhancement.items:
                self.offers[lot] = replace(offer, available=65535)
                self.packs[lot] = pack
        encode_sc_catalog(tuple(self.offers.values()))
        OwnedPetStore(path)
        WalletStore(path)
        WarehouseStore(path)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS sc_cart (account TEXT NOT NULL,lot_id INTEGER NOT NULL,quantity INTEGER NOT NULL,PRIMARY KEY(account,lot_id))')
            db.execute('CREATE TABLE IF NOT EXISTS sc_sold (account TEXT NOT NULL,lot_id INTEGER NOT NULL,quantity INTEGER NOT NULL,PRIMARY KEY(account,lot_id))')
            db.execute('CREATE TABLE IF NOT EXISTS sc_cart_terms (account TEXT NOT NULL,lot_id INTEGER NOT NULL,offer TEXT NOT NULL,pack INTEGER NOT NULL,PRIMARY KEY(account,lot_id))')
            db.execute('''CREATE TABLE IF NOT EXISTS sc_receipts (id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL,
                identity TEXT,packet TEXT NOT NULL,recipient INTEGER,selection TEXT,cost INTEGER,accepted INTEGER NOT NULL DEFAULT 0,
                UNIQUE(account,identity))''')
            db.execute("CREATE TRIGGER IF NOT EXISTS sc_cart_terms_no_update BEFORE UPDATE ON sc_cart_terms BEGIN SELECT RAISE(ABORT,'SC cart terms are frozen'); END")
            for operation in ('UPDATE', 'DELETE'):
                db.execute(f"CREATE TRIGGER IF NOT EXISTS sc_receipts_no_{operation.lower()} BEFORE {operation} ON sc_receipts WHEN OLD.accepted=1 BEGIN SELECT RAISE(ABORT,'SC receipts are immutable'); END")

    def _visible(self, db, account):
        town = self.completion.town(db, account)
        return {lot: offer for lot, offer in self.offers.items() if self.completion.allowed(offer.item_id, town, gold=True)}

    def _cart(self, db, account):
        rows, packs = [], {}
        for lot, count in db.execute('SELECT lot_id,quantity FROM sc_cart WHERE account=? ORDER BY lot_id', (account,)):
            term = db.execute('SELECT offer,pack FROM sc_cart_terms WHERE account=? AND lot_id=?', (account, lot)).fetchone()
            if term:
                offer, pack = SCOffer(**json.loads(term[0])), term[1]
                allowed_pack = self.packs.get(lot)
                if (offer.gold or offer.base_gold or offer.credits<=0 or offer.lot_id != lot or offer.enhancement not in (0, 10, 15, 20, 25)
                        or pack != allowed_pack or offer.available != 65535
                        or lot not in self.offers or offer.credits != self.offers[lot].credits):
                    raise ValueError('Invalid frozen SC cart terms')
            elif lot in self.legacy:
                offer, pack = self.legacy[lot]
                sold = db.execute('SELECT quantity FROM sc_sold WHERE account=? AND lot_id=?', (account, lot)).fetchone()
                offer = replace(offer, available=max(0, offer.available - (sold[0] if sold else 0)))
            else: raise ValueError('Неизвестный товар в корзине; удалите его')
            if not 1 <= count <= min(1000, offer.available): raise ValueError('Товар в корзине недоступен')
            rows.append((offer, count))
            packs[lot] = pack
        if sum(n for _, n in rows) > 1000: raise ValueError('Корзина превышает 1000 товаров')
        if sum(o.credits*n for o,n in rows) > self.completion.ready_prices.native_max:
            raise ValueError('Стоимость корзины превышает предел кредитов клиента')
        encode_sc_basket(tuple(rows))
        return tuple(rows), packs

    def _responses(self, db, account, action, recipient=None):
        catalog = encode_sc_catalog(tuple(self._visible(db, account).values()))
        basket = encode_sc_basket(self._cart(db, account)[0])
        if action in (9, 10): return (basket,)
        row = db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?', (account, recipient)).fetchone()
        wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
        if row is None or wallet is None: raise ValueError('SC recipient no longer exists')
        return bytes(row[0]), encode_asset_count(AssetCount(*wallet)), catalog, basket

    def handle(self, account, packet, *, allow_mutation=True, identity=None):
        action, fields = decode_sc_request(packet)
        _identity(identity)
        if not isinstance(account, str) or not account: raise ValueError('Account required')
        if action not in (4, 7, 12) and not allow_mutation:
            raise ValueError('SC purchases require the city and an owned recipient')
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN' if action in (4, 7, 12) else 'BEGIN IMMEDIATE')
            offers = self._visible(db, account)
            if action == 4: return (encode_sc_catalog(tuple(offers.values())),)
            if action == 7: return (encode_sc_basket(self._cart(db, account)[0]),)
            if action == 12: return (b'\xb4\x0d\0\0',)
            if identity is not None:
                prior = db.execute('SELECT packet,recipient,accepted FROM sc_receipts WHERE account=? AND identity=?', (account, identity)).fetchone()
                if prior:
                    if prior[0] != packet.hex() or prior[2] != 1: raise ValueError('Conflicting or incomplete SC operation retry')
                    return self._responses(db, account, action, prior[1])
            # The clear-cart button uses the existing remove writer with lot0,
            # a reserved value that cannot identify a real SC offer. Delete
            # before reading terms so stale/unavailable quotes can be cleared.
            if action == 10 and fields == (0,):
                db.execute('DELETE FROM sc_cart WHERE account=?', (account,))
                db.execute('DELETE FROM sc_cart_terms WHERE account=?', (account,))
                response = encode_sc_basket(())
                db.execute('INSERT INTO sc_receipts(account,identity,packet,accepted) VALUES (?,?,?,1)',
                           (account, identity, packet.hex()))
                return (response,)
            if action in (9, 10):
                lot, = fields
                row = db.execute('SELECT quantity FROM sc_cart WHERE account=? AND lot_id=?', (account, lot)).fetchone()
                if action == 9 and lot not in offers: raise ValueError('Unknown SC offer')
                count = (row[0] if row else 0) + (1 if action == 9 else -1)
                if count > 1000: raise ValueError('SC cart quantity limit exceeded')
                if count <= 0:
                    db.execute('DELETE FROM sc_cart WHERE account=? AND lot_id=?', (account, lot))
                    db.execute('DELETE FROM sc_cart_terms WHERE account=? AND lot_id=?', (account, lot))
                else:
                    if action == 9:
                        offer = offers[lot]
                        db.execute('INSERT OR IGNORE INTO sc_cart_terms VALUES (?,?,?,?)', (account, lot, json.dumps(asdict(offer), sort_keys=True), self.packs[lot]))
                    db.execute('INSERT INTO sc_cart VALUES (?,?,?) ON CONFLICT(account,lot_id) DO UPDATE SET quantity=excluded.quantity', (account, lot, count))
                responses = self._responses(db, account, action)
                db.execute('INSERT INTO sc_receipts(account,identity,packet,accepted) VALUES (?,?,?,1)', (account, identity, packet.hex()))
                return responses
            if action == 6:
                lot, recipient, currency = fields
                if lot not in offers: raise ValueError('Unknown SC offer')
                selection, packs = ((offers[lot], 1),), {lot: self.packs[lot]}
            else:
                recipient, currency = fields
                selection, packs = self._cart(db, account)
            if currency != 1: raise ValueError('SC accepts credits only')
            if not selection or sum(n for _, n in selection) > 1000: raise ValueError('Empty or oversized SC purchase')
            wallet = db.execute('SELECT credits,gold FROM wallets WHERE account=?', (account,)).fetchone()
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?', (account, recipient)).fetchone()
            if wallet is None or row is None: raise ValueError('Wallet or owned SC recipient missing')
            cost = sum(offer.credits*quantity for offer, quantity in selection)
            if wallet[0] < cost: raise ValueError('Insufficient credits')
            if OwnedPetStore.validate(row[1], row[2], bool(row[0])) != recipient: raise ValueError('Invalid SC recipient')
            owner, items, unknown = decode_item_list(row[2])
            seen = set(WarehouseStore._read(db, account))
            for snapshot, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
                for item in decode_item_list(snapshot)[1]:
                    if item.instance_id in seen: raise ValueError('Duplicate item ID across owned inventories')
                    seen.add(item.instance_id)
            sequence = db.execute('SELECT next_id FROM item_sequences WHERE account=?', (account,)).fetchone()
            next_id = max(max(seen, default=0) + 1, sequence[0] if sequence else 1)
            additions = ()
            for offer, quantity in selection:
                records, next_id = self.completion.additions(offer.item_id, packs[offer.lot_id], offer.durability, quantity, next_id, enhancement=offer.enhancement)
                additions += records
            merged = merge_stacks(items + additions)
            validate_capacity(items, merged)
            inventory = encode_item_list(owner, merged, unknown)
            encode_asset_count(AssetCount(wallet[0]-cost, wallet[1]))
            receipt = db.execute('INSERT INTO sc_receipts(account,identity,packet,recipient,selection,cost) VALUES (?,?,?,?,?,?)',
                                 (account, identity, packet.hex(), recipient, json.dumps([(asdict(o), n, packs[o.lot_id]) for o, n in selection], sort_keys=True), cost)).lastrowid
            db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (inventory, account, owner))
            db.execute('UPDATE wallets SET credits=? WHERE account=?', (wallet[0]-cost, account))
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id', (account, next_id))
            for offer, quantity in selection:
                if offer.lot_id in self.legacy and offer.available != 65535:
                    db.execute('INSERT INTO sc_sold VALUES (?,?,?) ON CONFLICT(account,lot_id) DO UPDATE SET quantity=quantity+excluded.quantity', (account, offer.lot_id, quantity))
            if action == 11:
                db.execute('DELETE FROM sc_cart WHERE account=?', (account,))
                db.execute('DELETE FROM sc_cart_terms WHERE account=?', (account,))
            from .achievements import event
            event(db, account, f'sc:{receipt}', add={'sc_purchase': 1})
            responses = self._responses(db, account, action, recipient)
            db.execute('UPDATE sc_receipts SET accepted=1 WHERE id=?', (receipt,))
            return responses
