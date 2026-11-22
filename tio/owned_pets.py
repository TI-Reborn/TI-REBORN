"""Persist validated owned-pet and inventory snapshots together.

Unknown wire fields are retained until their domain semantics are recovered.
Purchases update these snapshots atomically with wallets through tio.shop.
"""

from .db_transaction import connect
from .performance import timed
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
from .protocol.pet_info import decode_pet_info, encode_pet_info
from .protocol.item_list import decode_item_list


def _sync_armor(db: sqlite3.Connection, account: str, owner: int, human: int,
                pet: bytes, inventory: bytes) -> bytes:
    from .equipment import stow_armor_above_level
    level = decode_pet_info(pet, human_equipment=bool(human)).fields['0x8c4aef']
    updated = stow_armor_above_level(inventory, level)
    if updated != inventory:
        db.execute('UPDATE owned_pets SET inventory_packet=? WHERE account=? AND pet_id=?',
                   (updated, account, owner))
    return updated


class OwnedPetStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with closing(connect(self.path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS owned_pets (account TEXT NOT NULL, pet_id INTEGER NOT NULL, human INTEGER NOT NULL, pet_packet BLOB NOT NULL, inventory_packet BLOB NOT NULL, PRIMARY KEY(account,pet_id))')

    @staticmethod
    def validate(pet_packet,inventory_packet,human):
        pet=decode_pet_info(pet_packet,human_equipment=human)
        owner,items,_=decode_item_list(inventory_packet)
        if owner!=pet.fields['0x8c43eb']:
            raise ValueError('Inventory owner differs from pet ID')
        ids=[item.instance_id for item in items]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate inventory instance IDs')
        return owner

    def ensure(self,account,pet_packet,inventory_packet,*,human):
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        owner=self.validate(pet_packet,inventory_packet,human)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            if owner==1 and human and db.execute("SELECT 1 FROM sqlite_master WHERE name='characters'").fetchone():
                character=db.execute('SELECT request FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
                if character:
                    from .protocol.character_create import decode_character_create
                    from .appearance import starter
                    resource=decode_character_create(bytes(character[0])).options[0]
                    if resource in (1,2):
                        pet_packet=encode_pet_info(starter(decode_pet_info(pet_packet,human_equipment=True),resource))
            db.execute('INSERT OR IGNORE INTO owned_pets VALUES (?,?,?,?,?)',
                       (account,owner,int(human),pet_packet,inventory_packet))
            # The starter fixture carries a diagnostic name. Bind only that
            # original human fighter to the account's saved character on login.
            # Existing equipment/progress and named recruits remain untouched.
            if owner == 1 and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='characters'").fetchone():
                character = db.execute('SELECT name FROM characters WHERE account=? AND slot=1', (account,)).fetchone()
                saved = db.execute('SELECT human,pet_packet FROM owned_pets WHERE account=? AND pet_id=1', (account,)).fetchone()
                if character and saved[0]:
                    current = decode_pet_info(bytes(saved[1]), human_equipment=True)
                    name = bytes(character[0])
                    if current.fields['0x8c4489'] == b'ProbeNew' and name != b'ProbeNew':
                        renamed = encode_pet_info(replace(current, fields={**current.fields, '0x8c4489': name}))
                        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1', (renamed, account))
            from .ranks import sync
            from .level_progression import sync as sync_levels
            sync_levels(db,account)
            sync(db,account)
            row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',(account,owner)).fetchone()
            human, pet, inventory = row
            self.validate(pet,inventory,bool(human))
            inventory = _sync_armor(db, account, owner, human, pet, inventory)
        return bytes(pet),bytes(inventory)

    @timed('roster.list')
    def list(self, account):
        """Load one consistent roster snapshot, restricted to the current account."""
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        from . import ranks, level_progression
        from .equipment import stow_armor_above_level
        from .passive_stats import project_saved_roster
        query='SELECT pet_id,human,pet_packet,inventory_packet FROM owned_pets WHERE account=? ORDER BY pet_id'
        with closing(connect(self.path)) as db:
            for writing in (False, True):
                with db:
                    db.execute('BEGIN IMMEDIATE' if writing else 'BEGIN')
                    if writing:
                        # Re-read under the writer after releasing the read snapshot.
                        level_progression.sync(db,account)
                        ranks.sync(db,account)
                    rows=db.execute(query,(account,)).fetchall()
                    if not writing and (any(level_progression.normalize(p,bool(h))!=p for i,h,p,v in rows)
                            or ranks.needs_sync(db,account,[(i,h,p) for i,h,p,v in rows])
                            or any(stow_armor_above_level(v,decode_pet_info(p,human_equipment=bool(h)).fields['0x8c4aef'])!=v
                                   for i,h,p,v in rows)):
                        continue
                    if writing:
                        rows=[(i,h,p,_sync_armor(db,account,i,h,p,v)) for i,h,p,v in rows]
                    rows=project_saved_roster(db,account,rows)
                    break
        result=[]
        for owner,human,pet,inventory in rows:
            pet,inventory=bytes(pet),bytes(inventory)
            if self.validate(pet,inventory,bool(human))!=owner:
                raise ValueError('Stored pet key differs from packet ID')
            result.append((owner,pet,inventory))
        return tuple(result)

    def inventory(self, account, owner):
        """Read saved inventory after mutations; never serve another account's pet."""
        if not isinstance(account,str) or not account:raise ValueError('Account required')
        with closing(connect(self.path)) as db:
            row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                           (account,owner)).fetchone()
        if row is None:return None
        if self.validate(row[1],row[2],bool(row[0]))!=owner:
            raise ValueError('Stored pet key differs from packet ID')
        return bytes(row[2])
