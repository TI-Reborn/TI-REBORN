"""Atomic city battery recharge paid from the owner's crystal wallet."""
from pathlib import Path

from .db_transaction import transaction
from .implant_power import recharge
from .implants import policy
from .owned_pets import OwnedPetStore
from .protocol.item_action import decode_item_action
from .protocol.item_list import decode_item_list, encode_item_list


def charge(path: str | Path, account: str, packet: bytes) -> tuple[bytes, ...] | None:
    action = decode_item_action(packet)
    if not account:
        raise ValueError('Account required')
    with transaction(path) as db:
        row = db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets '
                         'WHERE account=? AND pet_id=?', (account, action.pet_id)).fetchone()
        if row is None:
            raise ValueError('Боец не принадлежит аккаунту')
        human, raw, inventory = row
        if OwnedPetStore.validate(raw, inventory, bool(human)) != action.pet_id:
            raise ValueError('Invalid battery owner')
        owner, items, flag = decode_item_list(inventory)
        battery = next((i for i in items if i.instance_id == action.instance_id), None)
        if battery is None or battery.template_id != policy()['battery']['template']:
            return None
        if action.option != 255:
            raise ValueError('Батарею нельзя установить в слот')
        from .implant_equipment import limit_health
        limit_health(db, account, owner, bool(human), raw)
        charged, cost = recharge(battery)
        updated = encode_item_list(owner, tuple(charged if i == battery else i for i in items), flag)
        balance = db.execute('SELECT amount FROM crystal_wallets WHERE account=?', (account,)).fetchone()
        if balance is None or balance[0] < cost:
            raise ValueError(f'Для зарядки требуется {cost} спектрокристаллов')
        if db.execute('UPDATE crystal_wallets SET amount=amount-? WHERE account=? AND amount>=?',
                      (cost, account, cost)).rowcount != 1:
            raise ValueError('Недостаточно спектрокристаллов')
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                   (updated, account, owner))
        from .protocol.asset_count import encode_asset_count
        from .wallets import WalletStore
        pet = next(p for identity, p, _ in OwnedPetStore(path).list(account) if identity == owner)
        return updated, pet, encode_asset_count(WalletStore(path).ensure(account))
