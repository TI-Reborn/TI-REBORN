"""Add suspect catalog item to our already excluded QA owners only."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import armor_fit_gui_20261021 as qa
code=r'''
import json,sqlite3
from pathlib import Path
from dataclasses import replace
from tio.rating_visibility import QA_LOGIN,excluded
from tio.roster_progression import profile
from tio.owned_pets import OwnedPetStore
from tio.appearance import with_appearance
from tio.protocol.pet_info import decode_pet_info,encode_pet_info
from tio.protocol.item_list import ItemRecord,encode_item_list
from tio.level_progression import FLOORS
path='/var/lib/tio-server/reservation.sqlite3';template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
for i,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 r=1 if i==0 else 2
 pet=decode_pet_info(profile(template,8,r,b'Z Pantsu QA'),human_equipment=True)
 pet=with_appearance(pet,bytes((r,0 if r==1 else 10,0,1,0,0)))
 raw=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':20,'0x8c4b05':FLOORS[19],'0x8c4a07':250,'0x8c4ab1':250}))
 inventory=encode_item_list(8,(ItemRecord(80001,206,bytes(2),1,1,8,(300,300,300),bytes(4),None,bytes(3)),))
 OwnedPetStore(path).validate(raw,inventory,True)
 with sqlite3.connect(path) as db:
  assert excluded(db,name)
  assert not db.execute('SELECT 1 FROM owned_pets WHERE account=? AND pet_id=8',(name,)).fetchone()
  db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,8,1,raw,inventory))
print(json.dumps(dict(passed=True,only_exact_owned_qa=True,extra_case=206)))
'''
data=json.loads(qa.qa.fixture.PRIVATE.read_text());result=qa.qa.fixture.v.remote(code,data['names']);(qa.OUT/'extra-fixture.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
