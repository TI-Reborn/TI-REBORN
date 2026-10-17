"""Create a NEW isolated dog1 database. Never modifies the player's database."""
import sys,json,sqlite3
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tio.hiring import HireStore
from tio.city_catalogs import CityCatalogs
from tio.wallets import WalletStore
from tio.abilities import AbilityCatalog,AbilityLevel
from tio.ability_state import AbilityStateStore
from tio.protocol.abilities import AbilityEntry
from tio.protocol.pet_info import decode_pet_info,encode_pet_info,PetInfo

if __name__=='__main__':
    path=Path(sys.argv[1]).resolve()
    if path.exists() or path==(ROOT/'data/reservation.sqlite3').resolve():raise ValueError('New test database required')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb'):pass
    template=bytes.fromhex(json.loads((ROOT/'evidence/owned_pet_trial.json').read_text())['packet_hex'])
    WalletStore(path).ensure('probe_user')
    pet,_,_=HireStore(path,CityCatalogs(ROOT/'config/city_catalogs.json'),template).hire('probe_user',3)
    dog=decode_pet_info(pet,human_equipment=False)
    assert dog.fields['0x8c43eb']==1
    wounded=encode_pet_info(PetInfo(False,{**dog.fields,'0x8c4ab1':73}))
    with closing(sqlite3.connect(path)) as db,db:
        db.execute('UPDATE owned_pets SET pet_packet=? WHERE account=? AND pet_id=1',(wounded,'probe_user'))
    source=json.loads((ROOT/'config/abilities.json').read_text())
    catalog=AbilityCatalog(AbilityLevel(r['id'],r['level'],r['fields']) for r in source['records'])
    AbilityStateStore(path,catalog).replace('probe_user',1,[AbilityEntry(23,1,0,1)],expected_revision=0)
    print(path)
