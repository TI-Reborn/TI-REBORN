"""Atomic city repairs. Session selection never confers item ownership."""

from .db_transaction import connect,transaction
from contextlib import closing
from dataclasses import replace
from .durability import KITS,repair_inventory,repair_item,spending_order
from .protocol.item_action import decode_item_action
from .protocol.item_list import decode_item_list,encode_item_list
from .protocol.repair import decode_repair,repair_message


def select_kit(path,account,packet):
    action=decode_item_action(packet)
    with closing(connect(path)) as db:
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,action.pet_id)).fetchone()
    if row is None:return None
    item=next((i for i in decode_item_list(row[0])[1] if i.instance_id==action.instance_id),None)
    if item is None or item.template_id not in KITS:return None
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
    from .warehouse_completion import exists,current_town,read_scope,places,persist_scope
    if not exists(db,'warehouse_items'):return None
    current_town(db,account)
    all_items=WarehouseStore._read(db,account)
    before=read_scope(db,account,all_items,required=True)
    kits=sorted((i for i in before.values() if i.template_id in KITS and i.unknown_words[0]>0
                 and i.optional_u32 is None and not i.unknown_bytes_02[3]),key=spending_order)
    if not kits:return None
    pet,items,flag=decode_item_list(packet)
    item=next((i for i in items if i.instance_id==target),None)
    if item is None:raise ValueError('Предмет не принадлежит бойцу')
    resource=sum(i.count*i.unknown_words[0] for i in kits)
    virtual=replace(kits[0],unknown_u32_01=1,unknown_words=(resource,*kits[0].unknown_words[1:]))
    fixed,_,spent,loss=repair_item(item,virtual)
    after=dict(before);assignments={};tagged=places(db,account)
    remaining=spent;first=True
    for kit in kits:
        if not remaining:break
        debit=min(remaining,kit.count*kit.unknown_words[0]);remaining-=debit
        units,partial=divmod(kit.count*kit.unknown_words[0]-debit,kit.unknown_words[0])
        del after[kit.instance_id]
        if units:after[kit.instance_id]=replace(kit,unknown_u32_01=units)
        if partial:
            identity=kit.instance_id
            if units:
                # Split a stack without changing the untouched units.
                identity=reserve_item_id(db,account,set(all_items)|set(after))
                if kit.instance_id in tagged:assignments[identity]=tagged[kit.instance_id]
            after[identity]=replace(kit,instance_id=identity,unknown_u32_01=1,unknown_words=(partial,*kit.unknown_words[1:]))
        record(db,account,owner,dict(target=target,kit=kit.instance_id,spent=debit,loss=loss if first else 0),achievement=first)
        first=False
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


def reserve_item_id(db,account,extra=()):
    """Next account-unique item ID across bags, warehouse and the sequence."""
    from .warehouse_completion import exists
    seen=set(extra)
    for raw, in db.execute('SELECT inventory_packet FROM owned_pets WHERE account=?',(account,)):
        seen.update(i.instance_id for i in decode_item_list(raw)[1])
    if exists(db,'warehouse_items'):
        seen.update(k for k, in db.execute('SELECT instance_id FROM warehouse_items WHERE account=?',(account,)))
    db.execute('CREATE TABLE IF NOT EXISTS item_sequences (account TEXT PRIMARY KEY, next_id INTEGER NOT NULL)')
    seq=db.execute('SELECT next_id FROM item_sequences WHERE account=?',(account,)).fetchone()
    identity=max(max(seen,default=0)+1,seq[0] if seq else 1)
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
