"""Persistent regular arena slots:0 available,1..3 selected;4 special/unfit."""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from .owned_pets import OwnedPetStore
from .protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo
from .passive_stats import project_saved_pet


class SquadStore:
    def __init__(self,path):
        self.path=path
        OwnedPetStore(path)
        # Repair the old placeholder which assigned every hire to slot1.
        # Keep the first occupant of each regular slot; release only duplicates.
        with closing(connect(path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            occupied=set()
            for account,owner,human,packet in db.execute('SELECT account,pet_id,human,pet_packet FROM owned_pets ORDER BY account,pet_id').fetchall():
                pet=decode_pet_info(packet,human_equipment=bool(human));slot=pet.fields['0x8c44a6']
                if slot not in (1,2,3):continue
                key=(account,slot)
                if key in occupied:
                    self._save(db,account,owner,pet,0)
                occupied.add(key)

    @staticmethod
    def _save(db,account,owner,pet,slot):
        packet=encode_pet_info(PetInfo(pet.human_equipment,{**pet.fields,'0x8c44a6':slot}))
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(packet,account,owner))
        return project_saved_pet(db,account,owner,packet,pet.human_equipment)

    def assign(self,account,owner,slot):
        if type(slot) is not int or slot not in (0,1,2,3):raise ValueError('Invalid regular squad slot')
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            pets={i:decode_pet_info(p,human_equipment=bool(h)) for i,h,p in db.execute(
                'SELECT pet_id,human,pet_packet FROM owned_pets WHERE account=?',(account,))}
            pet=pets.get(owner)
            if pet is None:raise ValueError('Owned squad actor required')
            if pet.fields['0x8c43eb']!=owner:raise ValueError('Saved actor ID mismatch')
            if slot and (pet.fields['0x8c44a6']==4 or pet.fields['0x8c4ab1']==0):raise ValueError('Actor cannot join regular squad')
            if slot and any(i!=owner and p.fields['0x8c44a6']==slot for i,p in pets.items()):
                raise ValueError('Squad slot is occupied')
            return (self._save(db,account,owner,pet,slot),)
