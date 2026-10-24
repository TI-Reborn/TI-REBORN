"""Retirement gate for persisted shared obligations; never erases save data."""
import sqlite3


class CharacterDeletionRejected(ValueError):
    """A known character retirement rule prevents the requested operation."""


def require_retirable(db: sqlite3.Connection, owner: str, now: float) -> None:
    checks = (
        ('battle_checkpoint_members', 'account=?', (owner,)),
        ('battle_settlement_jobs', 'account=?', (owner,)),
        ('clan_members', 'account=?', (owner,)),
        ('travel_party_members', 'owner=?', (owner,)),
        ('pve_contract_locks', 'owner=?', (owner,)),
        ('world_prison', 'account=? AND remaining>0', (owner,)),
        ('map_journeys', 'account=? AND arrives>?', (owner, now)),
        ('bank_item_marks', "state='active' AND (owner=? OR holder=?)", (owner, owner)),
        ('player_auction_lots', "state='active' AND (seller=? OR bidder=?)", (owner, owner)),
    )
    for table, predicate, parameters in checks:
        if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
            if db.execute('SELECT 1 FROM '+table+' WHERE '+predicate+' LIMIT 1', parameters).fetchone():
                raise CharacterDeletionRejected('Character has an active journey, battle, group, clan or market obligation')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='private_shops'").fetchone():
        for table in ('private_shop_sales', 'private_shop_orders'):
            if db.execute('SELECT 1 FROM '+table+' i JOIN private_shops s ON i.shop=s.id WHERE s.account=? LIMIT 1',
                          (owner,)).fetchone():
                raise CharacterDeletionRejected('Close private shop offers before deleting the character')
