"""Clan crest IDs for the native battle member list, frozen when a battle starts.

Clan membership and crest changes are refused while a player is in battle, so
the start-time snapshot stays correct and is checkpointed with the battle.
"""
from collections.abc import Iterable
from contextlib import closing

from tio.clan_benefits import account_crests
from tio.db_transaction import connect


def seat_crests(seats: Iterable[tuple]) -> dict[int, int]:
    """Map each human seat owner to its clan crest ID; bots are left out.

    A seat is (owner, side, database path, account, ticket, bot).
    """
    by_path: dict[object, dict[str, int]] = {}
    for owner, _side, path, account, _ticket, bot in seats:
        if not bot:by_path.setdefault(path, {})[account] = owner
    crests = {}
    for path, owners in by_path.items():
        with closing(connect(path)) as db:
            found = account_crests(db, owners)
        crests.update((owners[account], crest) for account, crest in found.items())
    return crests


def member_crest(battle: dict, owner: int) -> int:
    """Checkpoints written before this field existed show no crest."""
    return battle.get('crests', {}).get(owner, 0)
