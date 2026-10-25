"""The one rule for new account-local item IDs.

A new item must not reuse any ID the account's client may still know: every
mercenary's bag, the personal warehouse, active rental leases and the
account's item_sequences high-water mark. The native client resolves an item
by its ID across all of the player's mercenaries, so a reused ID makes it pick
the wrong owner (the dim TrueSkill loan weapon, PR #32).

Battle-created items use the separate match namespace instead
(tio.battle_loot.match_id_floor).
"""
from .protocol.item_list import decode_item_list


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def taken_item_ids(db, account):
    taken = set()
    for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?', (account,)):
        taken.update(item.instance_id for item in decode_item_list(bytes(raw))[1])
    if _table(db, 'warehouse_items'):
        taken.update(key for key, in db.execute('SELECT instance_id FROM warehouse_items WHERE account=?', (account,)))
    if _table(db, 'rentals'):
        taken.update(key for key, in db.execute('SELECT instance_id FROM rentals WHERE account=?', (account,)))
    return taken


def next_item_id(db, account, extra=()):
    """First free ID; callers may add IDs they are about to place (extra)."""
    highest = max(max(taken_item_ids(db, account) | set(extra), default=0), 0)
    sequence = (db.execute('SELECT next_id FROM item_sequences WHERE account=?', (account,)).fetchone()
                if _table(db, 'item_sequences') else None)
    return max(highest + 1, sequence[0] if sequence else 1)
