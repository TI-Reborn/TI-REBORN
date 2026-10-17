"""Recovered read requests, with explicit limits of missing clan/mail/mark state.

B809 is an assault-clan ranking query, not a warehouse operation. B811 is
an asset refresh: original AssetCount consumer clears warehouse waiting.
Empty lists below describe absent subsystems; they do not enable transfers,
mark creation, mail attachments or clan permissions.
"""

from .db_transaction import connect
from .protocol.binary import PacketError
from .protocol.warehouse import encode_warehouse_list,encode_private_warehouse_snapshot
from .protocol.asset_count import encode_asset_count
from .warehouse import WarehouseStore,WarehouseRejected
from .wallets import WalletStore


def handles(packet):
    return packet[:1]==b'\x69' or packet[:2] in (b'\xb8\x04',b'\xb8\x09',b'\xb8\x11')


def reply(path,account,packet):
    if not isinstance(account,str) or not account:raise ValueError('Account required')
    if not handles(packet):return None
    if len(packet)!=2:raise PacketError('Invalid warehouse query length')
    if packet==b'\xb8\x11':
        assets=WalletStore(path).ensure(account)
        return (encode_asset_count(assets),)
    if packet==b'\xb8\x09':
        # RECV_AssaultClanRating 8a10bc begins with u32 count. No assault clans
        # exist in the current server; player battle ranks are unrelated.
        return (b'\xb8\x0a'+bytes(4),)
    if packet==b'\xb8\x04':
        # TANetMarkedItems original writer641740: C8/29 + u32 count.
        # Marker ownership/time is not recoverable from an ItemRecord flag.
        # Refuse inconsistent imported data rather than fabricate its owner.
        from contextlib import closing
        import sqlite3
        from .protocol.item_list import decode_item_list
        WarehouseStore(path)
        with closing(connect(path)) as db:
            db.execute('BEGIN')
            items=list(WarehouseStore._read(db,account).values())
            for inventory, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
                items.extend(decode_item_list(inventory)[1])
        if any(i.unknown_bytes_02[2] for i in items):
            raise WarehouseRejected('Marked item ownership data is unavailable')
        return (b'\xc8\x29'+bytes(4),)
    kind=packet[1]
    if kind==0:
        return encode_private_warehouse_snapshot(WarehouseStore(path).items(account))
    if kind in (1,2):
        from .clans import ClansStore
        from .protocol.warehouse import encode_warehouse_snapshot
        from .protocol.system_message import encode_shop_error
        try:return ClansStore(path).warehouse_packets(account,kind)
        except WarehouseRejected as exc:
            return (encode_warehouse_list(kind,1,0,()),encode_shop_error(str(exc)))
    if kind==3:
        # Postbox is TANetSendPostWarehouse, not WarehouseList kind3.
        # Original writer64588c: B7/75 + u32 message count. No mail delivery
        # service or attachments currently exist; no invented inbox is seeded.
        return (b'\xb7\x75'+bytes(4),)
    raise PacketError('Unknown warehouse kind')
