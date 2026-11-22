"""Atomic saved-inventory exchange between two fighters of one account."""
from pathlib import Path

from .db_transaction import transaction
from .implant_equipment import limit_health
from .item_exchange import exchange_items
from .item_ids import next_item_id
from .owned_pets import OwnedPetStore
from .protocol.city_item_transfer import decode_transfer
from .warehouse_completion import current_town, exists


def transfer(path: str | Path, account: str, packet: bytes) -> tuple[bytes, ...]:
    request = decode_transfer(packet)
    if not isinstance(account, str) or not account:
        raise ValueError('Owned account required')
    ids = (request.actor_id, request.target_id)
    with transaction(path) as db:
        current_town(db, account)
        for table in ('battle_checkpoint_members', 'battle_settlement_jobs'):
            if exists(db, table) and db.execute('SELECT 1 FROM '+table+' WHERE account=?', (account,)).fetchone():
                raise ValueError('Передача доступна только вне боя')
        rows = {}
        for identity in ids:
            row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                             (account, identity)).fetchone()
            if row is None or OwnedPetStore.validate(row[1], row[2], bool(row[0])) != identity:
                raise ValueError('Оба бойца должны принадлежать вашему персонажу')
            rows[identity] = row
        changes, next_id, _ = exchange_items(
            *(rows[i][2] for i in ids), request, next_item_id(db, account), allow_unequip=True)
        if request.withdrawals or request.deposits:
            for identity, inventory in changes.items():
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                           (inventory, account, identity))
            db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY,next_id INTEGER NOT NULL)')
            db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',
                       (account, next_id))
        return tuple(p for identity in ids for p in (
            changes[identity], limit_health(db, account, identity, bool(rows[identity][0]), rows[identity][1])))
