"""Five owned native character slots with independent durable save owners."""

from .db_transaction import connect,transaction
import re
from contextlib import closing
import sqlite3
from pathlib import Path
from .protocol.character_create import encode_character_create, decode_character_create
from .protocol.character_select import CharacterRecord
from .character_identity import MAX_CHARACTERS, PREFIX, alias, initialise, owner_for_slot

class CreateRejected(ValueError):
    def __init__(self,status):
        self.status=status
        super().__init__(f'Character create rejected: {status}')

class CharacterStore:
    def __init__(self,path):
        self.path=Path(path)
        with closing(connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS characters (account TEXT NOT NULL, slot INTEGER NOT NULL, name BLOB NOT NULL, name_key TEXT NOT NULL UNIQUE, request BLOB NOT NULL, PRIMARY KEY(account,slot))")
            initialise(db)

    def create(self,account,request):
        raw=encode_character_create(request)
        alias(account,1)
        # Native 8a7ba8/8a7c1d: male=1, female=2. Zero is retained for
        # pre-existing diagnostic/admin records. Other fields are zero in UI.
        if request.unknown_u16!=0 or request.options[0] not in (0,1,2) or any(request.options[1:]):
            raise CreateRejected(1)
        if not re.fullmatch(rb'[A-Za-z][A-Za-z0-9]{2,15}',request.name_bytes):raise CreateRejected(4)
        key=request.name_bytes.decode('ascii').lower()
        with transaction(self.path) as db:
            if db.execute('SELECT 1 FROM characters WHERE name_key=?',(key,)).fetchone():raise CreateRejected(3)
            occupied = {slot for slot,_ in self._owners(db,account)}
            slot = next((value for value in range(1,MAX_CHARACTERS+1) if value not in occupied),None)
            if slot is None:raise CreateRejected(2)
            from .character_lifecycle import allocate
            owner = allocate(db, account, slot)
            first_generation = owner == alias(account, slot)
            if slot != 1 and first_generation:
                # An alias is unloggable. Never reuse unexpected old data under
                # it, or mint a fresh wallet over a historical owner.
                if db.execute('SELECT 1 FROM characters WHERE account=?',(owner,)).fetchone():
                    raise ValueError('Character owner key already exists')
                db.execute('INSERT INTO character_identities VALUES (?,?,?)',(account,slot,owner))
            db.execute('INSERT INTO characters VALUES (?,?,?,?,?)',(owner,1,request.name_bytes,key,raw))
            if not first_generation or request.options[0] in (1, 2):
                from .wallets import WalletStore
                WalletStore(self.path).seed_character(owner, first_generation=first_generation)
            if request.options[0] in (1,2):
                from .onboarding import initialize_created
                initialize_created(self.path,owner)
        return self.list(account)

    @staticmethod
    def _owners(db,account):
        from .character_lifecycle import retired, latest
        result=[]
        if (db.execute('SELECT 1 FROM characters WHERE account=? AND slot=1',(account,)).fetchone()
                and not retired(db, account)):
            result.append((1,account))
        # This supports prepare/list of a particular save owner as well as
        # authentication-scoped lists on the native selection screen.
        if not account.startswith(PREFIX):
            for slot,owner in db.execute('SELECT slot,owner FROM character_identities WHERE login=? ORDER BY slot',(account,)):
                if latest(db, account, slot) is not None:
                    continue
                if owner_for_slot(db,account,slot)!=owner:raise ValueError('Corrupt character mapping')
                result.append((slot,owner))
            for slot in range(1, MAX_CHARACTERS + 1):
                revision = latest(db, account, slot)
                if revision is not None and revision[2] is None:
                    result.append((slot, owner_for_slot(db, account, slot)))
        return tuple(sorted(result))

    def delete(self, account: str, slot: int, *, now: float) -> None:
        """Retire one owned character without deleting saves or credentials."""
        from .character_lifecycle import retire
        from .character_deletion import require_retirable
        with transaction(self.path) as db:
            owner = owner_for_slot(db, account, slot)
            require_retirable(db, owner, now)
            retire(db, account, slot, owner, now)

    def owner(self,account,slot):
        with closing(connect(self.path)) as db:
            return owner_for_slot(db,account,slot)

    def select(self,account,slot):
        owner=self.owner(account,slot)
        record=next(record for record in self.list(account) if record.record_id==slot)
        return owner,record

    def list(self,account):
        with closing(connect(self.path)) as db, db:
            rows=[]
            has_pets=db.execute("SELECT 1 FROM sqlite_master WHERE name='owned_pets'").fetchone()
            for slot,owner in self._owners(db,account):
                name,raw=db.execute('SELECT name,request FROM characters WHERE account=? AND slot=1',(owner,)).fetchone()
                pet=db.execute('SELECT pet_packet,inventory_packet FROM owned_pets WHERE account=? AND pet_id=1',(owner,)).fetchone() if has_pets else None
                rows.append((slot,name,raw,pet))
        records=[]
        for slot,name,raw,pet_row in rows:
            resource=decode_character_create(bytes(raw)).options[0] or 1
            appearance=b''
            words=[0]*19
            level=0
            if pet_row is not None:
                from .protocol.pet_info import decode_pet_info
                from .protocol.item_list import decode_item_list
                from .appearance import appearance_bytes
                pet=decode_pet_info(bytes(pet_row[0]),human_equipment=True)
                resource=pet.fields['0x8c446f']
                if pet.fields['0x6d0203']:appearance=appearance_bytes(pet)
                level=pet.fields['0x8c4aef']
                # CharSelectInfo 88a0d7..88a284 uses the same equipment property
                # masks as PetInfo and ItemList; words 2/3 are discarded.
                slots={1:0,2:1,16:4,128:5,4:6,8:7,1024:8,
                       0x40000:9,0x80000:10,0x100000:11,0x200000:12}
                for item in decode_item_list(bytes(pet_row[1]))[1]:
                    if item.equipped and item.client_slot in slots:
                        words[slots[item.client_slot]]=item.template_id
            records.append(CharacterRecord(slot,bytes(name),resource,0,0,0,int(bool(appearance)),appearance,tuple(words),level,0,0))
        return tuple(records)
