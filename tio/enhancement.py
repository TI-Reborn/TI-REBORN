"""Atomic ordinary Upgrade Kit attempts. Research: ENHANCEMENT.md."""

from .db_transaction import connect, transaction
from contextlib import closing
from dataclasses import dataclass, replace
import json
from pathlib import Path
import secrets
import sqlite3
import xml.etree.ElementTree as ET

from .owned_pets import OwnedPetStore
from .protocol.item_list import ItemRecord, decode_item_list, encode_item_list
from .protocol.enhancement import decode_enhancement_request, encode_enhancement_result
from .item_catalog import items_root
from .protocol.inventory_update import encode_inventory_item_update
from .warehouse_completion import current_town, exists, persist_scope, read_scope

ROOT = Path(__file__).resolve().parents[1]


class EnhancementRules:
    def __init__(self, path=None):
        self.config = json.loads(Path(path or ROOT/'config/enhancement.json').read_text())
        c = self.config
        for key in ('max_level', 'safe_levels', 'armor_success_percent', 'weapon_success_percent',
                    'durability_per_level', 'kit_template_id'):
            if type(c[key]) is not int:
                raise ValueError('Invalid enhancement policy')
        if not (0 <= c['safe_levels'] <= c['max_level'] == 25 and
                0 <= c['armor_success_percent'] <= 100 and 0 <= c['weapon_success_percent'] <= 100 and
                0 < c['durability_per_level'] <= 1000 and c['kit_template_id'] == 30):
            raise ValueError('Invalid enhancement policy')
        from .weapons import WeaponCatalog
        weapons = WeaponCatalog()
        eligible_weapons = {i for i, w in weapons.weapons.items()
                            if i not in (300, 333, 337) and (w.weapon_type != 'Throwing' or i == 316)}
        self.items = {}
        for node in items_root().iter('item'):
            identity = int(node.get('id'))
            values = {v.get('key'): v.get('val') for v in node.findall('value')}
            # Manual p75 explicitly describes upgrading miner armor. The
            # freaks_only flag restricts its wearer, not its enhancement.
            armor = values.get('itype') == 'armor' and identity < 65000
            if not armor and identity not in eligible_weapons:
                continue
            durability = int(values.get('durability', '0'))
            if durability <= 0:
                continue
            self.items[identity] = dict(kind='armor' if armor else 'weapon',
                                       special=values.get('special') == '1', durability=durability)

    def chance(self, level, kind):
        return 100 if level < self.config['safe_levels'] else self.config[kind+'_success_percent']

    def bonus(self, level, *, armor=False):
        safe = min(level, self.config['safe_levels'])
        excess = max(0, level - safe)
        return safe + (excess * 3 // 2 if armor else excess * 2)


@dataclass(frozen=True)
class EnhancementResult:
    outcome: str
    level: int
    chance: int
    replies: tuple[bytes, ...]


def _usable_kit(item: ItemRecord, template: int) -> bool:
    return (item.template_id == template and item.count >= 1 and not item.equipped
            and not any(item.unknown_bytes_03) and not any(item.unknown_bytes_02[2:])
            and item.optional_u32 is None)


class EnhancementStore:
    def __init__(self, path, *, rules=None, randbelow=None):
        self.path = path
        self.rules = rules or EnhancementRules()
        self.randbelow = randbelow or secrets.randbelow
        OwnedPetStore(path)
        with closing(connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')

    def handle(self, account: str, packet: bytes, *, allow_mutation: bool = True) -> EnhancementResult:
        request = decode_enhancement_request(packet)
        if not account or not allow_mutation:
            raise ValueError('Enhancement requires the city')
        with transaction(self.path) as db:
            inventories, located = {}, {}
            for owner, human, pet, inventory in db.execute(
                    'SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=?', (account,)):
                if OwnedPetStore.validate(pet, inventory, bool(human)) != owner:
                    raise ValueError('Invalid inventory owner')
                _, items, unknown = decode_item_list(inventory)
                inventories[owner] = (items, unknown)
                for item in items:
                    if item.instance_id in located:
                        raise ValueError('Ambiguous item ID')
                    located[item.instance_id] = (owner, item)
            if request.instance_id not in located:
                raise ValueError('Owned enhancement item missing')
            owner, item = located[request.instance_id]
            rule = self.rules.items.get(item.template_id)
            kit_template = self.rules.config['kit_template_id']
            stock = {}
            if request.kit_id is None:
                # Like quick repair, the RMB menu prefers personal stock when available.
                if exists(db, 'warehouse_items') and current_town(db, account, required=False) is not None:
                    stock = read_scope(db, account, required=True)
                    if located.keys() & stock.keys():
                        raise ValueError('Ambiguous item ID')
                selected = next(((None, kit) for kit in stock.values() if _usable_kit(kit, kit_template)), None)
                if selected is None:
                    selected = next((entry for _, entry in sorted(located.items())
                                     if _usable_kit(entry[1], kit_template)), None)
                if selected is None:
                    raise ValueError('Upgrade Kit required')
            else:
                selected = located.get(request.kit_id)
                if selected is None:
                    raise ValueError('Owned enhancement item missing')
            kit_owner, kit = selected
            if (rule is None or item.count != 1 or item.instance_id == kit.instance_id or
                    not _usable_kit(kit, kit_template)):
                raise ValueError('Unsupported enhancement item')
            # Marked/rented and other upgrade systems require their own rules.
            if any(item.unknown_bytes_02[2:]) or item.optional_u32 is not None or item.unknown_bytes_03[1]:
                raise ValueError('Unsupported enhancement item')
            level = item.unknown_bytes_03[0]
            if level >= self.rules.config['max_level']:
                raise ValueError('Maximum enhancement reached')
            chance = self.rules.chance(level, rule['kind'])
            roll = None if chance == 100 else self.randbelow(100)
            if roll is not None and (type(roll) is not int or not 0 <= roll < 100):
                raise ValueError('Invalid enhancement random result')
            success = roll is None or roll < chance
            from .durability import special as is_special
            special = is_special(item)
            outcome = 'success' if success else 'reset' if special else 'destroyed'
            new_level = level + 1 if success else 0
            replacement = None
            if outcome != 'destroyed':
                # Manual p56: upgrade restores the theoretical maximum, not
                # the maximum previously reduced by repairs (Tank 50/100->565).
                durability = (rule['durability'] + new_level*self.rules.config['durability_per_level']
                              if success else rule['durability'])
                if durability > 65535:
                    raise ValueError('Enhancement durability overflow')
                words=(durability,)*3
                replacement = replace(item, unknown_words=words,
                    unknown_bytes_02=bytes((new_level,)) + item.unknown_bytes_02[1:],
                    unknown_bytes_03=bytes((new_level,)) + item.unknown_bytes_03[1:])
            from .bank_economy import assert_item_mutation
            assert_item_mutation(db, account, item.instance_id, 'destroy' if outcome == 'destroyed' else 'enhance')
            assert_item_mutation(db, account, kit.instance_id, 'destroy')
            remaining_kit = replace(kit, unknown_u32_01=kit.count - 1) if kit.count > 1 else None
            replies = []
            for changed_owner in sorted({owner, kit_owner} - {None}):
                items, unknown = inventories[changed_owner]
                updated = []
                for current in items:
                    if current.instance_id == item.instance_id:
                        if replacement is not None:
                            updated.append(replacement)
                    elif current.instance_id == kit.instance_id:
                        if remaining_kit is not None:
                            updated.append(remaining_kit)
                    else:
                        updated.append(current)
                inventory = encode_item_list(changed_owner, tuple(updated), unknown)
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                           (inventory, account, changed_owner))
                replies.append(inventory)
            if kit_owner is None:
                from .protocol.asset_count import encode_asset_count
                from .protocol.warehouse import encode_private_warehouse_snapshot
                from .wallets import WalletStore
                updated_stock = dict(stock)
                if remaining_kit is None:
                    del updated_stock[kit.instance_id]
                else:
                    updated_stock[kit.instance_id] = remaining_kit
                persist_scope(db, account, stock, updated_stock.values(), {})
                replies.extend(encode_private_warehouse_snapshot(updated_stock.values()))
                replies.append(encode_asset_count(WalletStore(self.path).ensure(account)))
            # Never reuse consumed IDs, including legacy seeds without a sequence.
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',
                       (account, max(max(located), kit.instance_id)+1))
            if replacement is not None:
                from .enhancement_limits import project_owned_inventory
                projected = project_owned_inventory(self.path, account, encode_item_list(owner, (replacement,)))
                display_item, = decode_item_list(projected)[1]
                replies.append(encode_inventory_item_update(owner, display_item))
            replies.append(encode_enhancement_result(outcome, item.template_id, new_level if success or special else level))
            from .achievements import update,upgraded
            if success and new_level>=3:upgraded(db,account,item.instance_id)
            if outcome=='destroyed' and level>15:update(db,account,add={'destroyed_above15':1})
        return EnhancementResult(outcome, new_level, chance, tuple(replies))
