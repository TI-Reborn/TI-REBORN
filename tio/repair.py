"""Atomic city repairs. Session selection never confers item ownership."""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from .durability import KITS,repair_inventory
from .protocol.item_action import decode_item_action
from .protocol.item_list import decode_item_list
from .protocol.repair import decode_repair,repair_message


def select_kit(path,account,packet):
    action=decode_item_action(packet)
    with closing(connect(path)) as db:
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,action.pet_id)).fetchone()
    if row is None:return None
    item=next((i for i in decode_item_list(row[0])[1] if i.instance_id==action.instance_id),None)
    if item is None or item.template_id not in KITS:return None
    if item.equipped or item.count!=1 or item.unknown_words[0]<=0:raise ValueError('Ремкомплект израсходован')
    return (action.pet_id,action.instance_id)


def repair(path,account,packet,selection=None):
    owner,target=decode_repair(packet)
    if packet[0]==0x7e and (selection is None or selection[0]!=owner):
        raise ValueError('Сначала выберите ремкомплект у этого бойца')
    with closing(connect(path)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
        if row is None:raise ValueError('Боец не принадлежит аккаунту')
        updated,audit=repair_inventory(row[0],target,selection[1] if packet[0]==0x7e else None)
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',(updated,account,owner))
        record(db,account,owner,audit)
    return updated,repair_message(112)


def record(db,account,owner,audit):
    db.execute('''CREATE TABLE IF NOT EXISTS item_repairs (
        id INTEGER PRIMARY KEY, account TEXT NOT NULL, pet_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL, kit_id INTEGER NOT NULL, spent INTEGER NOT NULL,
        max_loss INTEGER NOT NULL, repaired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    db.execute('INSERT INTO item_repairs(account,pet_id,item_id,kit_id,spent,max_loss) VALUES (?,?,?,?,?,?)',
               (account,owner,audit['target'],audit['kit'],audit['spent'],audit['loss']))
    from .achievements import update
    update(db,account,add={'repairs':1})
