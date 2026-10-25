"""Shared-market transfers: native item metadata, account-local IDs, atomic money.

These helpers run only inside a caller-owned SQLite transaction. Overflow money
is retained as a durable payable; it is never truncated or lost on a refund.
"""
from dataclasses import replace
from .protocol.item_list import decode_item_list, encode_item_list
from .warehouse import WarehouseStore
from . import warehouse_completion as completion
from .item_stacking import stack_key
from .item_ids import next_item_id

MAX=0xffffffff


def initialise(db):
    db.execute('CREATE TABLE IF NOT EXISTS market_payables (account TEXT NOT NULL,currency TEXT NOT NULL,amount INTEGER NOT NULL CHECK(amount>=0),PRIMARY KEY(account,currency))')


def unsigned(value,maximum=MAX,*,positive=False):
    if type(value) is not int or not int(positive)<=value<=maximum:raise ValueError('Недопустимое количество или сумма')
    return value


def owner(db,account):
    row=db.execute('SELECT name FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
    if row is None or db.execute('SELECT 1 FROM wallets WHERE account=?',(account,)).fetchone() is None:
        raise ValueError('Требуется существующий персонаж и кошелёк')
    return bytes(row[0]).decode('cp1251')


def debit(db,account,amount,currency='credits'):
    unsigned(amount)
    if currency != 'credits':raise ValueError('Недопустимая валюта')
    if db.execute(f'UPDATE wallets SET {currency}={currency}-? WHERE account=? AND {currency}>=?',(amount,account,amount)).rowcount!=1:
        raise ValueError('Недостаточно средств')


def credit(db,account,amount,currency='credits'):
    if type(amount) is not int or amount<0 or currency != 'credits':raise ValueError('Недопустимый платёж')
    row=db.execute(f'SELECT {currency} FROM wallets WHERE account=?',(account,)).fetchone()
    if row is None:raise ValueError('Получатель платежа отсутствует')
    paid=min(amount,MAX-row[0]);db.execute(f'UPDATE wallets SET {currency}={currency}+? WHERE account=?',(paid,account))
    if paid<amount:db.execute('INSERT INTO market_payables VALUES (?,?,?) ON CONFLICT(account,currency) DO UPDATE SET amount=amount+excluded.amount',(account,currency,amount-paid))


def collect(db,account):
    for currency,amount in db.execute('SELECT currency,amount FROM market_payables WHERE account=?',(account,)).fetchall():
        db.execute('DELETE FROM market_payables WHERE account=? AND currency=?',(account,currency));credit(db,account,amount,currency)


def tradable(item):
    from .durability import definitions
    from .item_boosters import nontransferable
    # Unknown/encounter/quest templates cannot enter an unrestricted market.
    return (not nontransferable(item.template_id) and item.template_id in definitions() and item.template_id<0xff00 and not item.equipped and not item.slot
            and not any(item.unknown_bytes_02[2:]) and item.optional_u32 is None and item.count>0)


def owned(db,account):
    result={key:(item,None,0) for key,item in WarehouseStore._read(db,account).items()}
    for pet,raw in db.execute('SELECT pet_id,inventory_packet FROM owned_pets WHERE account=?',(account,)):
        ident,items,flag=decode_item_list(raw)
        if ident!=pet:raise ValueError('Недопустимый владелец инвентаря')
        for item in items:
            if item.instance_id in result:raise ValueError('Повторный ID предмета')
            result[item.instance_id]=(item,pet,flag)
    return result


def take(db,account,key,count):
    unsigned(key,positive=True);unsigned(count,0x7fffffff,positive=True)
    inventory=owned(db,account);found=inventory.get(key)
    if found is None or not tradable(found[0]) or count>found[0].count:raise ValueError('Предмет недоступен для торговли')
    item,pet,flag=found
    if pet is None and key not in completion.read_scope(db,account,required=True):raise ValueError('Предмет находится на складе другого города')
    if stack_key(item) is None and (count!=1 or item.count!=1):raise ValueError('Это не стопка предметов')
    remaining=replace(item,unknown_u32_01=item.count-count)
    if pet is None:
        if count==item.count:db.execute('DELETE FROM warehouse_items WHERE account=? AND instance_id=?',(account,key))
        else:db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',(encode_item_list(0,(remaining,)),account,key))
    else:
        items=tuple(remaining if i.instance_id==key else i for i,p,_ in inventory.values() if p==pet and (i.instance_id!=key or remaining.count))
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(encode_item_list(pet,items,flag),account,pet))
    return replace(item,unknown_u32_01=count)


def deliver(db,account,items):
    """Durable delivery ignores capacity, like existing auction/mail awards."""
    owner(db,account);inventory=owned(db,account)
    key=next_item_id(db,account,inventory)
    delivered=[]
    for item in items:
        if not 0<key<0xffff0000:raise ValueError('Исчерпаны ID предметов')
        received=replace(item,instance_id=key,unknown_u8_01=0,location_raw=0)
        completion.stash(db,account,(received,),origin='market-delivery')
        delivered.append(received);key+=1
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=excluded.next_id',(account,key))
    return tuple(delivered)


def restore(db,account,items):
    """Return seller escrow using its old ID where possible (native edit UI)."""
    from .item_stacking import MAX_STACK
    for item in items:
        inventory=owned(db,account);found=inventory.get(item.instance_id)
        if found is None:
            completion.restore_escrow(db,account,item)
        elif stack_key(found[0]) is not None and stack_key(found[0])==stack_key(item) and found[0].count+item.count<=MAX_STACK:
            old,pet,flag=found;merged=replace(old,unknown_u32_01=old.count+item.count)
            if pet is None:db.execute('UPDATE warehouse_items SET item_packet=? WHERE account=? AND instance_id=?',(encode_item_list(0,(merged,)),account,item.instance_id))
            else:
                members=tuple(merged if i.instance_id==item.instance_id else i for i,p,_ in inventory.values() if p==pet)
                db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(encode_item_list(pet,members,flag),account,pet))
        else:deliver(db,account,(item,))
    inventory=owned(db,account);key=max(inventory,default=0)+1
    db.execute('INSERT INTO item_sequences VALUES (?,?) ON CONFLICT(account) DO UPDATE SET next_id=MAX(next_id,excluded.next_id)',(account,key))
