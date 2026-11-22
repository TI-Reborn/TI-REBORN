"""Private warehouse requests; first6B list deposits, second withdraws.

Direction follows original drag/drop branches a6653e/a66645 and a66725/a667b2.
"""
from .warehouse import WarehouseStore, WarehouseRejected
from .protocol.warehouse_transfer import decode_warehouse_transfer
from .protocol.warehouse import encode_private_warehouse_snapshot


def warehouse_error_reply(error: ValueError) -> bytes:
    """Use the verified localized F0/394 path, which also clears client waiting."""
    from .protocol.system_message import encode_shop_error
    reasons = {
        'Inventory is full': 'переноса: в инвентаре бойца недостаточно свободных мест',
        'Warehouse capacity exceeded': 'склада: недостаточно свободных мест',
        'Недостаточно места на складе': 'склада: недостаточно свободных мест',
        'Склад доступен только в городе или у входа в шахту': 'склада: склад доступен только в городе или у входа в шахту',
        'Insufficient item quantity': 'переноса: недостаточно предметов в выбранной стопке',
        'Unequip item before transferring': 'переноса: сначала снимите предмет с наёмника',
        'Owned mercenary required': 'переноса: ваш наёмник не найден',
        'Selected item is not in the owned source': 'переноса: предмет больше не находится в выбранном месте',
        'Invalid or repeated item selection': 'переноса: некорректный выбор предметов',
        'An item cannot move both ways': 'переноса: предмет выбран одновременно в обе стороны',
        'Only the personal warehouse is available': 'склада: доступен только личный склад',
        'Marked item ownership data is unavailable': 'склада: список помеченных предметов пока недоступен',
    }
    from .clans import ClanRejected
    return encode_shop_error(reasons.get(str(error),str(error) if isinstance(error,ClanRejected) else 'склада: не удалось перенести предметы'))


def transfer_private_items(path, account, packet, *, capacity):
    request=decode_warehouse_transfer(packet)
    if request.warehouse_type != 0:
        from .clans import ClansStore
        from .wallets import WalletStore
        from .protocol.asset_count import encode_asset_count
        current=ClansStore(path)
        inventory,_=current.exchange(account,request.actor_id,request.warehouse_type,
            deposits=request.first_items,withdrawals=request.second_items)
        assets=WalletStore(path).ensure(account)
        inventories = () if inventory is None else (inventory,)
        return (*inventories,*current.warehouse_packets(account,request.warehouse_type),encode_asset_count(assets))
    from .db_transaction import transaction
    from .wallets import WalletStore
    from .protocol.asset_count import encode_asset_count
    store = WarehouseStore(path, capacity=capacity)
    with transaction(path) as db:
        before = dict(db.execute(
            'SELECT pet_id,inventory_packet FROM owned_pets WHERE account=? AND pet_id<>?',
            (account, request.actor_id))) if request.second_items else {}
        inventory, items = store.exchange(account, request.actor_id,
            deposits=request.first_items, withdrawals=request.second_items)
        donors = tuple(packet
            for owner, pet, updated in db.execute(
                'SELECT pet_id,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id<>?',
                (account, request.actor_id)) if owner in before and updated != before[owner]
            for packet in (updated, pet)) if before else ()
        return (inventory, *donors, *encode_private_warehouse_snapshot(items),
                encode_asset_count(WalletStore(path).ensure(account)))
