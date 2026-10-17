"""Local candidate hiring with atomic wallet/roster updates."""

from .db_transaction import connect
from contextlib import closing
import sqlite3
from dataclasses import replace
from .owned_pets import OwnedPetStore
from .wallets import WalletStore
from .shop import PurchaseRejected
from .protocol.pet_info import PetInfo,decode_pet_info,encode_pet_info,SCHEMAS
from .protocol.item_list import encode_item_list,decode_item_list
from .protocol.asset_count import AssetCount
from .protocol.hire import encode_hire_request,encode_pet_deleted


class HireStore:
    def __init__(self,path,catalogs,template):
        self.path=path;self.catalogs=catalogs
        self.template=decode_pet_info(template,human_equipment=True)
        OwnedPetStore(path);WalletStore(path)
        from .locations import LocationStore
        LocationStore(path)
        with closing(connect(path)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS hired_candidates (account TEXT NOT NULL,candidate_id INTEGER NOT NULL,pet_id INTEGER NOT NULL,PRIMARY KEY(account,candidate_id))')
            # Rename legacy emulator defaults once; preserve player-chosen names.
            miner_name=next(c.name for c in catalogs.candidates if c.resource_type==6)
            legacy_names={"Шахтёр".encode('cp1251'),b'Freak Miner',b'Oaoo??'}
            for account,owner,packet in db.execute('SELECT account,pet_id,pet_packet FROM owned_pets WHERE human=1').fetchall():
                if int.from_bytes(packet[5:9],'little')!=6:continue
                pet=decode_pet_info(packet,human_equipment=True)
                if pet.fields['0x8c4489'] not in legacy_names:continue
                pet.fields['0x8c4489']=miner_name
                db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=?',(encode_pet_info(pet),account,owner))

    def available(self,account):
        with closing(connect(self.path)) as db:
            return self._available(db,account)

    def _available(self,db,account):
        # Fixed stride leaves existing IDs1/2 valid and permits future pool additions.
        used={r[0] for r in db.execute('SELECT candidate_id FROM hired_candidates WHERE account=?',(account,))}
        result=[]
        row=db.execute('SELECT town_id FROM character_locations WHERE account=?',(account,)).fetchone()
        town=row[0] if row else 3
        from .cities import CITIES
        if town not in (*CITIES,9):return ()
        for c in self.catalogs.candidates:
            if (c.resource_type==6) != (town==9):continue
            if not 0<c.candidate_id<1000:raise PurchaseRejected('Invalid candidate pool ID')
            generations=[i for i in used if i%1000==c.candidate_id]
            candidate_id=max(generations)+1000 if generations else c.candidate_id
            if candidate_id<=0xffffffff:
                result.append(replace(c,unknown_u32_01=candidate_id))
        return tuple(result)

    def dismiss(self,account,pet_id):
        if not isinstance(account,str) or not account:raise PurchaseRejected('Account required')
        reply=encode_pet_deleted(pet_id)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT human,pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=?',
                           (account,pet_id)).fetchone()
            hired=db.execute('SELECT 1 FROM hired_candidates WHERE account=? AND pet_id=?',(account,pet_id)).fetchone()
            if row is None:raise PurchaseRejected('Wallet or owned recipient missing')
            # The bootstrap actor is retained; only explicitly hired recruits can leave.
            if hired is None:raise PurchaseRejected('Starting actor cannot be dismissed')
            if OwnedPetStore.validate(row[1],row[2],bool(row[0]))!=pet_id:
                raise PurchaseRejected('Pet ID mismatch')
            if decode_item_list(row[2])[1]:raise PurchaseRejected('Recruit inventory is not empty')
            db.execute('DELETE FROM owned_pets WHERE account=? AND pet_id=?',(account,pet_id))
            # Keep hire history: dismissed IDs cannot be reused by later hires.
        return reply

    def hire(self,account,candidate_id):
        if not isinstance(account,str) or not account:raise PurchaseRejected('Account required')
        encode_hire_request(candidate_id)
        with closing(connect(self.path)) as db,db:
            db.execute('BEGIN IMMEDIATE')
            found=[c for c in self._available(db,account) if c.candidate_id==candidate_id]
            if len(found)!=1:raise PurchaseRejected('Unknown, stale or ambiguous offer')
            c=found[0]
            if c.resource_type not in (1,2,3,4,5,6):raise PurchaseRejected('Unsupported recruit type')
            human=c.resource_type in (1,2,6)
            from .level_progression import FLOORS,RULES
            if not 1<=c.unknown_u8<=20:raise PurchaseRejected('Invalid recruit level')
            base_hp=RULES['initial_hp'][str(c.resource_type)]+(c.unknown_u8-1)*RULES['hp_per_level']
            if c.stat_float_bits!=(0x41200000,)*16 or c.optional_bytes!=b'\0'*6 or c.unknown_u16_01!=base_hp:
                raise PurchaseRejected('Recruit stats differ from supported local actor fixture')
            if db.execute('SELECT 1 FROM hired_candidates WHERE account=? AND candidate_id=?',(account,candidate_id)).fetchone():
                raise PurchaseRejected('Candidate already hired')
            wallet=db.execute('SELECT credits,gold FROM wallets WHERE account=?',(account,)).fetchone()
            if wallet is None:raise PurchaseRejected('Wallet or owned recipient missing')
            if wallet[0]<c.price_credits:raise PurchaseRejected('Insufficient credits')
            count,highest=db.execute('SELECT COUNT(*),COALESCE(MAX(pet_id),0) FROM owned_pets WHERE account=?',(account,)).fetchone()
            from .services import power
            if count>=7+power(db,account,2):raise PurchaseRejected('Roster full')
            historical=db.execute('SELECT COALESCE(MAX(pet_id),0) FROM hired_candidates WHERE account=?',(account,)).fetchone()[0]
            owner=max(highest,historical)+1
            if owner>0xffffffff:raise PurchaseRejected('Pet IDs exhausted')
            # Local human fixture: unknown fields remain unchanged, equipment empty.
            fields={**self.template.fields,'0x8c43eb':owner,'0x8c446f':c.resource_type,
                    '0x8c4489':c.name,'0x8c4aef':c.unknown_u8,'0x8c44a6':0,
                    '0x8c4bbc':1,'0x8c4bd0':0,'0x8c4be3':0,'0x8c4bf6':20}
            if c.resource_type==6:
                # Manual p43; PetInfo getters confirmed in the original reader.
                fields.update({'0x8c4a07':98,'0x8c4ab1':98,'0x8c4a1b':8,
                               '0x8c4a2f':14,'0x8c4b57':1000,'0x8c4ac5':0})
            from .weight import base_capacity
            fields['0x8c4b57']=base_capacity(c.resource_type,c.unknown_u8)
            fields['0x8c4b6d']=0
            fields['0x8c4b05']=FLOORS[c.unknown_u8-1]
            fields['0x8c4a07']=base_hp
            fields['0x8c4ab1']=fields['0x8c4a07']
            schema=SCHEMAS[(human,bool(fields['0x6d0203']),bool(fields['0x8c4565']))]
            fields={key:fields.get(key,0) for key,_,_ in schema}
            from .weapon_proficiency import ProficiencyRules
            pet=ProficiencyRules().normalize(encode_pet_info(PetInfo(human,fields)),human);inventory=encode_item_list(owner,())
            OwnedPetStore.validate(pet,inventory,human)
            db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(account,owner,int(human),pet,inventory))
            db.execute('INSERT INTO hired_candidates VALUES (?,?,?)',(account,candidate_id,owner))
            db.execute('UPDATE wallets SET credits=? WHERE account=?',(wallet[0]-c.price_credits,account))
        return pet,inventory,AssetCount(wallet[0]-c.price_credits,wallet[1])
