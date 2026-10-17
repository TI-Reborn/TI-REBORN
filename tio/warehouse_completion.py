"""City warehouses without altering or reseeding any legacy item row.

The original warehouse_items triplet and WarehouseStore._read remain global
authority for IDs and lifecycle work. A sidecar names only new accepted item
locations. Untagged old rows remain accessible legacy overflow in every city.
Durable awards/refunds get explicit overflow when 32 city slots cannot fit them.
No automatic migration, triggers, FK cascades, destructive list rewrite, or
global SQL filter is used. Clan prices and powers +8/+16: manual printed page22;
IDs/target=selfclan: original services.cfg. Clan base32 and personal payer are
explicit server policy; the late original client private default is3000.
"""
from contextlib import closing
from dataclasses import replace
import json

from .db_transaction import connect
from .protocol.item_list import decode_item_list, encode_item_list
from .protocol.warehouse import encode_private_warehouse_snapshot
from .item_stacking import merge_stacks
from .inventory_capacity import validate_capacity

BASE = 32
CLAN_OFFERS = {3: ((8, 15000), (16, 45000)), 4: ((8, 15000), (16, 45000))}


def write(db):
    if not db.in_transaction: raise ValueError('Warehouse completion requires authoritative transaction')


def schema(db):
    write(db)
    db.execute('''CREATE TABLE IF NOT EXISTS warehouse_places (
        account TEXT NOT NULL,instance_id INTEGER NOT NULL,bucket TEXT NOT NULL CHECK(bucket IN ('city','overflow')),
        town INTEGER NOT NULL,origin TEXT NOT NULL,PRIMARY KEY(account,instance_id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS clan_paid_services (
        clan_id INTEGER NOT NULL,service INTEGER NOT NULL CHECK(service IN (3,4)),level INTEGER NOT NULL CHECK(level BETWEEN 1 AND 2),
        PRIMARY KEY(clan_id,service))''')
    db.execute('''CREATE TABLE IF NOT EXISTS warehouse_service_receipts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,account TEXT NOT NULL,identity TEXT NOT NULL,request TEXT NOT NULL,
        result TEXT NOT NULL,UNIQUE(account,identity))''')
    # No trigger touches old player/item tables. Only accepted new receipts are immutable.
    for operation in ('UPDATE', 'DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS warehouse_service_receipts_no_{operation.lower()} BEFORE {operation} ON warehouse_service_receipts BEGIN SELECT RAISE(ABORT,'Warehouse service receipts are immutable'); END")


def exists(db, table):
    return bool(db.execute('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)).fetchone())


def current_town(db, account, *, required=True):
    from .cities import CITIES
    row = db.execute('SELECT town_id FROM character_locations WHERE account=?', (account,)).fetchone() if exists(db, 'character_locations') else None
    town = row[0] if row else 3
    travelling = exists(db, 'map_journeys') and db.execute('SELECT 1 FROM map_journeys WHERE account=?', (account,)).fetchone()
    if type(town) is not int or town not in (*CITIES, 9) or travelling:
        if required: raise ValueError('Склад доступен только в городе')
        return None
    return town


def places(db, account):
    if not exists(db, 'warehouse_places'): return {}
    result = {}
    for key, bucket, town, origin in db.execute('SELECT instance_id,bucket,town,origin FROM warehouse_places WHERE account=?', (account,)):
        if (type(key) is not int or not 0 < key <= 0xffffffff or bucket not in ('city', 'overflow')
                or type(town) is not int or not 1 <= town <= 65535 or not isinstance(origin, str) or not origin):
            raise ValueError('Invalid authoritative warehouse placement')
        result[key] = (bucket, town, origin)
    return result


def read_scope(db, account, all_items=None, *, required=False):
    """Current city + legacy/overflow; never use for global ID allocation."""
    write(db)
    from .warehouse import WarehouseStore
    WarehouseStore._account(account)
    if all_items is None: all_items = WarehouseStore._read(db, account)
    town, tagged = current_town(db, account, required=required), places(db, account)
    return {key: item for key, item in all_items.items()
            if key not in tagged or tagged[key][0] == 'overflow' or tagged[key][1] == town}


def capacity(db, account):
    from .services import power
    return BASE + power(db, account, 1)


def city_count(db, account, items=None, *, town=None):
    from .warehouse import WarehouseStore
    town = current_town(db, account) if town is None else town
    items = WarehouseStore._read(db, account) if items is None else items
    tagged = places(db, account)
    return sum(key in tagged and tagged[key][:2] == ('city', town) for key in items)


def merge_scope(db, account, items, before, *, origin='player-deposit', limit=None):
    """Keep city/overflow/legacy stacks apart and old legacy rows uncombined."""
    town = current_town(db, account)
    tagged, groups = places(db, account), {}
    for item in items:
        group = tagged.get(item.instance_id, ('legacy', 0, 'legacy')) if item.instance_id in before else ('city', town, origin)
        # Origin is receipt provenance, not a separate playable warehouse.
        groups.setdefault(group[:2], []).append((item, group))
    merged, assignments = [], {}
    for (bucket, place), entries in groups.items():
        members = tuple(item for item, _ in entries)
        output = members if bucket == 'legacy' else merge_stacks(members)
        lookup = dict((i.instance_id, group) for i, group in entries)
        merged.extend(output)
        for item in output:
            if bucket != 'legacy': assignments[item.instance_id] = lookup[item.instance_id]
    used = sum(group[0] == 'city' and group[1] == town for group in assignments.values())
    ceiling = capacity(db, account)
    if limit is not None:
        if type(limit) is not int or limit < 0: raise ValueError('Invalid delivery capacity limit')
        ceiling = min(ceiling, limit)
    if used > max(city_count(db, account, before, town=town), ceiling):
        raise ValueError('Недостаточно места на складе')
    return tuple(merged), assignments


def persist_scope(db, account, before, after, assignments):
    """Update only touched visible rows; other cities and legacy packets persist."""
    write(db)
    after = {i.instance_id: i for i in after}
    for key in before.keys() - after.keys():
        db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?', (account, key))
    for key, item in after.items():
        if before.get(key) != item:
            db.execute('INSERT INTO warehouse_items VALUES (?,?,?) ON CONFLICT(account,instance_id) DO UPDATE SET item_packet=excluded.item_packet', (account, key, encode_item_list(0, (item,))))
        if key in assignments:
            bucket, town, origin = assignments[key]
            db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?) ON CONFLICT(account,instance_id) DO UPDATE SET bucket=excluded.bucket,town=excluded.town,origin=excluded.origin', (account, key, bucket, town, origin))


def stash(db, account, items, *, origin, overflow=True):
    """Durable server deliveries keep IDs/metadata; a full city cannot erase them."""
    write(db);schema(db)
    from .warehouse import WarehouseStore
    before = WarehouseStore._read(db, account)
    items = tuple(items)
    owned_ids = set(before)
    for packet, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
        for item in decode_item_list(packet)[1]:
            if item.instance_id in owned_ids: raise ValueError('Duplicate authoritative item identity')
            owned_ids.add(item.instance_id)
    if not isinstance(origin, str) or not 1 <= len(origin) <= 200: raise ValueError('Warehouse delivery origin required')
    if len({i.instance_id for i in items}) != len(items) or any(type(i.instance_id) is not int or not 0 < i.instance_id <= 0xffffffff
            or i.instance_id in owned_ids or i.count < 1 or i.equipped or i.slot for i in items):
        raise ValueError('Duplicate or invalid warehouse delivery')
    encoded = {i.instance_id: encode_item_list(0, (i,)) for i in items}
    town = current_town(db, account, required=False)
    used = city_count(db, account, before, town=town) if town is not None else BASE
    if not overflow and (town is None or used+len(items) > capacity(db, account)):
        raise ValueError('Недостаточно места на складе')
    for item in items:
        bucket = 'city' if town is not None and used < capacity(db, account) else 'overflow'
        if bucket == 'overflow' and not overflow: raise ValueError('Недостаточно места на складе')
        db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', (account, item.instance_id, encoded[item.instance_id]))
        db.execute('INSERT INTO warehouse_places VALUES (?,?,?,?,?) ON CONFLICT(account,instance_id) DO UPDATE SET bucket=excluded.bucket,town=excluded.town,origin=excluded.origin', (account, item.instance_id, bucket, town or 3, origin))
        if bucket == 'city': used += 1
    return items


def restore_escrow(db, account, item):
    """A durable return keeps its old location/ID; unknown old origin is overflow."""
    write(db);schema(db)
    prior = places(db, account).get(item.instance_id)
    if prior:
        db.execute('INSERT INTO warehouse_items VALUES (?,?,?)', (account, item.instance_id, encode_item_list(0, (item,))))
        return item
    stash(db, account, (item,), origin='escrow-return')
    return item


def compact_all(db, account, items):
    """Login compaction cannot merge another city's stacks or rewrite legacy IDs."""
    tagged, groups = places(db, account), {}
    for item in items:
        group = tagged.get(item.instance_id, ('legacy', 0, 'legacy'))[:2]
        groups.setdefault(group, []).append(item)
    result = []
    for group, members in groups.items():
        result.extend(members if group[0] == 'legacy' else merge_stacks(members))
    return tuple(sorted(result, key=lambda i: i.instance_id))


def status(db, account):
    write(db)
    from .warehouse import WarehouseStore
    all_items = WarehouseStore._read(db, account)
    tagged, town = places(db, account), current_town(db, account, required=False)
    visible = read_scope(db, account, all_items)
    return dict(version=1, town=town, capacity=capacity(db, account), used=city_count(db, account, all_items, town=town) if town else 0,
                legacy=sum(k not in tagged for k in all_items), overflow=sum(k in tagged and tagged[k][0] == 'overflow' for k in all_items),
                accessible=len(visible), stored_total=len(all_items), city_capacities={str(t): capacity(db, account) for t in sorted({p[1] for p in tagged.values() if p[0] == 'city'})},
                policy='legacy_and_durable_overflow_preserved')


def exchange(db, account, pet_id, *, deposits=(), withdrawals=()):
    write(db);schema(db)
    from .warehouse import WarehouseStore, WarehouseRejected
    from .owned_pets import OwnedPetStore
    current_town(db, account)
    chosen = []
    for pairs in (deposits, withdrawals):
        selection = {}
        for key, count in pairs:
            if type(key) is not int or not 0 < key <= 0xffffffff or type(count) is not int or not 0 < count <= 0xffffffff or key in selection:
                raise WarehouseRejected('Invalid or repeated item selection')
            selection[key] = count
        chosen.append(selection)
    deposits, withdrawals = chosen
    if deposits.keys() & withdrawals.keys(): raise WarehouseRejected('An item cannot move both ways')
    row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?', (account, pet_id)).fetchone()
    if row is None or OwnedPetStore.validate(row[1], row[2], bool(row[0])) != pet_id: raise WarehouseRejected('Owned mercenary required')
    _, original, flag = decode_item_list(row[2])
    inventory = {i.instance_id: i for i in original}
    all_items = WarehouseStore._read(db, account)
    warehouse = read_scope(db, account, all_items, required=True)
    before = dict(warehouse)
    seen = set(all_items)
    for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
        for item in decode_item_list(raw)[1]:
            if item.instance_id in seen: raise WarehouseRejected('Item ID exists in multiple locations')
            seen.add(item.instance_id)
    for selection, source in ((deposits, inventory), (withdrawals, warehouse)):
        for key, count in selection.items():
            item = source.get(key)
            if item is None: raise WarehouseRejected('Selected item is not in the owned source')
            if count > item.count: raise WarehouseRejected('Insufficient item quantity')
            if (item.equipped or item.slot) and count != item.count: raise WarehouseRejected('Unequip item before transferring')
    sequence = db.execute('SELECT next_id FROM item_sequences WHERE account=?', (account,)).fetchone()
    next_id = max(max(seen, default=0)+1, sequence[0] if sequence else 1)
    for selection, source, destination in ((withdrawals, warehouse, inventory), (deposits, inventory, warehouse)):
        for key, count in selection.items():
            item = source[key]
            if source is inventory: item = replace(item, unknown_u8_01=0, location_raw=0)
            if count == item.count:
                del source[key];destination[key] = item
            else:
                if next_id > 0xffffffff: raise WarehouseRejected('Item ID space exhausted')
                source[key] = replace(item, unknown_u32_01=item.count-count)
                destination[next_id] = replace(item, instance_id=next_id, unknown_u32_01=count)
                next_id += 1
    inventory = merge_stacks(inventory.values())
    stored, assignments = merge_scope(db, account, warehouse.values(), before)
    validate_capacity(original, inventory, error=WarehouseRejected)
    packet = encode_item_list(pet_id, inventory, flag)
    encode_private_warehouse_snapshot(stored)
    db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?', (packet, account, pet_id))
    persist_scope(db, account, before, stored, assignments)
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)', (account, next_id))
    return packet, tuple(sorted(stored, key=lambda i: i.instance_id))


class WarehouseCompletionStore:
    def __init__(self, path, *, capacity=None):
        from .warehouse import WarehouseStore
        self.path = path
        WarehouseStore(path)
        with closing(connect(path)) as db, db:
            db.execute('BEGIN IMMEDIATE');schema(db)

    def items(self, account):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN');return tuple(read_scope(db, account).values())

    def exchange(self, account, pet_id, **kwargs):
        with closing(connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE');return exchange(db, account, pet_id, **kwargs)


def clan_level(db, clan, service):
    if service not in CLAN_OFFERS: raise ValueError('Unknown clan warehouse service')
    if not exists(db, 'clan_paid_services'): return 0
    row = db.execute('SELECT level FROM clan_paid_services WHERE clan_id=? AND service=?', (clan, service)).fetchone()
    return row[0] if row else 0


def clan_capacity(db, clan, kind):
    service = 3 if kind == 1 else 4 if kind == 2 else None
    level = clan_level(db, clan, service)
    return BASE + (CLAN_OFFERS[service][level-1][0] if level else 0)


def clan_status(db, account):
    write(db)
    from .clans import membership, UPGRADE
    clan = membership(db, account)
    if clan is None: raise ValueError('Для расширения склада нужен клан')
    wallet = db.execute('SELECT credits FROM wallets WHERE account=?', (account,)).fetchone()
    if wallet is None: raise ValueError('Кошелёк игрока не найден')
    rows = []
    for service, kind in ((3, 1), (4, 2)):
        level = clan_level(db, clan['id'], service)
        count = db.execute('SELECT COUNT(*) FROM clan_items WHERE clan_id=? AND kind=?', (clan['id'], kind)).fetchone()[0]
        rows.append(dict(service=service, kind=kind, level=level, capacity=clan_capacity(db, clan['id'], kind), used=count,
                         next_level=level+1 if level < 2 else None, price=CLAN_OFFERS[service][level][1] if level < 2 else None))
    return dict(version=1, clan=dict(id=clan['id'], name=clan['name'].decode('cp1251')), player_credits=wallet[0],
                can_upgrade=clan['leader']==account or clan['permissions'] & UPGRADE == UPGRADE,
                payer='player_credits', services=rows, permanent=True)


def clan_purchase(db, account, service, wanted, *, expected_clan, identity):
    write(db);schema(db)
    from .clans import require, UPGRADE, record
    if type(service) is not int or service not in CLAN_OFFERS or type(wanted) is not int or not 1 <= wanted <= 2 or type(expected_clan) is not int:
        raise ValueError('Недоступное расширение склада')
    if not isinstance(identity, str) or not 1 <= len(identity) <= 160 or any(ord(c) < 32 for c in identity):
        raise ValueError('Invalid warehouse operation identity')
    clan = require(db, account, UPGRADE)
    if clan['id'] != expected_clan: raise ValueError('Клан изменился; обновите страницу')
    current_town(db, account)
    request = json.dumps(dict(clan=expected_clan, service=service, level=wanted), sort_keys=True)
    prior = db.execute('SELECT request,result FROM warehouse_service_receipts WHERE account=? AND identity=?', (account, identity)).fetchone()
    if prior:
        if prior[0] != request: raise ValueError('Conflicting warehouse service retry')
        return dict(json.loads(prior[1]), replayed=True, status=clan_status(db, account))
    owned = clan_level(db, expected_clan, service)
    if wanted != owned+1: raise ValueError('Сначала оплатите предыдущий уровень сервиса')
    price = CLAN_OFFERS[service][wanted-1][1]
    if db.execute('UPDATE wallets SET credits=credits-? WHERE account=? AND credits>=?', (price, account, price)).rowcount != 1:
        raise ValueError('Недостаточно кредитов')
    db.execute('INSERT INTO clan_paid_services VALUES (?,?,?) ON CONFLICT(clan_id,service) DO UPDATE SET level=excluded.level', (expected_clan, service, wanted))
    record(db, expected_clan, account, 'warehouse_service', f'{service}:{wanted}:{price}:player_credits')
    result = dict(service=service, level=wanted, clan_id=expected_clan, charged_credits=price, payer='player_credits')
    db.execute('INSERT INTO warehouse_service_receipts(account,identity,request,result) VALUES (?,?,?,?)', (account, identity, request, json.dumps(result, sort_keys=True)))
    return dict(result, replayed=False, status=clan_status(db, account))
