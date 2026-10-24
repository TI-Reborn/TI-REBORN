"""Native warehouse header: available Upgrade Kits and remaining repair power.

Only the selected character's shared personal warehouse contributes.
Mercenary bags, other characters, clan/mail stores and sale escrow are separate.
All reads join the caller's authoritative snapshot; no schema or item writes.
"""
from dataclasses import replace

from .durability import KITS
from .warehouse_completion import exists


def counts(db, account):
    from .warehouse import WarehouseStore
    WarehouseStore._account(account)
    if not exists(db, 'warehouse_items'):
        return 0, 0
    repair = upgrades = 0
    for identity, item in WarehouseStore._read(db, account).items():
        if item.template_id == 30:
            upgrades += item.count
        elif item.template_id in KITS:
            # Durability word0 is the remaining resource, not catalog capacity.
            # Keep legacy identical-item stacks meaningful without merging kits.
            repair += item.count * item.unknown_words[0]
    # The wire has two u32 fields; this is a display bound, never an item debit.
    return min(repair, 0xffffffff), min(upgrades, 0xffffffff)


def project_assets(db, account, assets):
    repair, upgrades = counts(db, account)
    return replace(assets, unknown_u32_08=repair, unknown_u32_09=upgrades)
