"""Atomic city repairs. Session selection never confers item ownership."""

from collections.abc import Collection, Iterable
from .db_transaction import connect,transaction
from contextlib import closing
from dataclasses import replace
from .durability import SELECTABLE_KITS,repair_inventory,repair_item,spending_order,repair_kits
from .protocol.item_action import decode_item_action
from .protocol.item_list import ItemRecord,decode_item_list,encode_item_list
from .protocol.repair import decode_repair,repair_message
from .item_ids import next_item_id


def select_kit(path,account,packet):
    action=decode_item_action(packet)
    with closing(connect(path)) as db:
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,action.pet_id)).fetchone()
    if row is None:return None
    item=next((i for i in decode_item_list(row[0])[1] if i.instance_id==action.instance_id),None)
    from .implants import policy
    if item is None or item.template_id not in (*SELECTABLE_KITS,policy()['repair']['template']):return None
    if item.equipped or item.count<1 or item.unknown_words[0]<=0:raise ValueError('Ремкомплект израсходован')
    return (action.pet_id,action.instance_id)


def repair(path,account,packet,selection=None):
    owner,target=decode_repair(packet)
    if packet[0]==0x7e and (selection is None or selection[0]!=owner):
        raise ValueError('Сначала выберите ремкомплект у этого бойца')
    with transaction(path) as db:
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row is None:raise ValueError('Боец не принадлежит аккаунту')
        if packet[:2]==b'\xc2\x03':
            result=repair_from_warehouse(db,path,account,owner,target,row[0])
            if result is not None:return result
        updated,audit=repair_inventory(row[0],target,selection[1] if packet[0]==0x7e else None,
                                       allocate=lambda:reserve_item_id(db,account))
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(updated,account,owner))
        record(db,account,owner,audit)
    return updated,repair_message(112)


def repair_from_warehouse(db,path,account,owner,target,packet):
    """Debit the same personal-city stock that supplies the repair counter."""
    from .warehouse import WarehouseStore
    from .warehouse_completion import exists,current_town,read_scope,persist_scope
    if not exists(db,'warehouse_items'):return None
    current_town(db,account)
    all_items=WarehouseStore._read(db,account)
    before=read_scope(db,account,all_items,required=True)
    pet,items,flag=decode_item_list(packet)
    item=next((i for i in items if i.instance_id==target),None)
    if item is None:raise ValueError('Предмет не принадлежит бойцу')
    kits=warehouse_kits(before.values(), repair_kits(item))
    if not kits:return None
    resource=sum(i.count*i.unknown_words[0] for i in kits)
    virtual=replace(kits[0],unknown_u32_01=1,unknown_words=(resource,*kits[0].unknown_words[1:]))
    fixed,_,spent,loss=repair_item(item,virtual)
    after, assignments, debits = debit_warehouse_kits(db, account, before, kits, spent)
    for index, (kit, debit) in enumerate(debits):
        record(db,account,owner,dict(target=target,kit=kit,spent=debit,loss=loss if index == 0 else 0),achievement=index == 0)
    updated=encode_item_list(pet,tuple(fixed if i.instance_id==target else i for i in items),flag)
    db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(updated,account,owner))
    persist_scope(db,account,before,after.values(),assignments)
    from .protocol.warehouse import encode_private_warehouse_snapshot
    from .protocol.asset_count import encode_asset_count
    from .wallets import WalletStore
    # Serialize inside the same transaction, so a failed projection rolls back
    # both repair and kit debit. Store connections join transaction(path).
    return (updated,*encode_private_warehouse_snapshot(tuple(after.values())),
            encode_asset_count(WalletStore(path).ensure(account)),repair_message(112))


def warehouse_kits(items: Iterable[ItemRecord], templates: Collection[int]) -> list[ItemRecord]:
    return sorted((i for i in items if i.template_id in templates and i.unknown_words[0] > 0
                   and i.optional_u32 is None and not any(i.unknown_bytes_02[2:])), key=spending_order)


def debit_warehouse_kits(db, account, before, kits, points):
    from .warehouse_completion import places

    if points > sum(kit.count * kit.unknown_words[0] for kit in kits):
        raise ValueError('Недостаточно ремонтных очков на личном складе')
    after, assignments, debits = dict(before), {}, []
    tagged = places(db, account)
    for kit in kits:
        if not points:
            break
        resource = kit.unknown_words[0]
        debit = min(points, kit.count * resource)
        points -= debit
        debits.append((kit.instance_id, debit))
        units, partial = divmod(kit.count * resource - debit, resource)
        del after[kit.instance_id]
        if units:
            after[kit.instance_id] = replace(kit, unknown_u32_01=units)
        if partial:
            identity = kit.instance_id
            if units:
                identity = reserve_item_id(db, account, after)
                if kit.instance_id in tagged:
                    assignments[identity] = tagged[kit.instance_id]
            after[identity] = replace(kit, instance_id=identity, unknown_u32_01=1,
                                      unknown_words=(partial, *kit.unknown_words[1:]))
    return after, assignments, debits


def reserve_item_id(db,account,extra=()):
    """Next account-unique item ID across bags, warehouse and the sequence."""
    from .warehouse_completion import exists
    seen=set(extra)
    for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
        seen.update(i.instance_id for i in decode_item_list(raw)[1])
    if exists(db,'warehouse_items'):
        seen.update(k for k, in db.execute('SELECT instance_id FROM warehouse_items WHERE account=?',(account,)))
    db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
    identity=next_item_id(db,account,seen)
    if identity>0xffffffff:raise ValueError('Item ID space exhausted')
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(account,identity+1))
    return identity


def record(db,account,owner,audit,*,achievement=True):
    db.execute('''CREATE TABLE IF NOT EXISTS item_repairs (
        id INTEGER PRIMARY KEY, account TEXT NOT NULL, pet_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL, kit_id INTEGER NOT NULL, spent INTEGER NOT NULL,
        max_loss INTEGER NOT NULL, repaired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('INSERT INTO item_repairs(account,pet_id,item_id,kit_id,spent,max_loss) VALUES (?,?,?,?,?,?)',
               (account,owner,audit['target'],audit['kit'],audit['spent'],audit['loss']))
    from .achievements import update
    if achievement:update(db,account,add={'repairs':1})
