"""Excluded hosted fixtures for missing face and bare/weapon-held hands."""
import argparse,ast,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
from tools.armor_missing_parts_20261021 import OUT,ASSET
qa.OUT=OUT;qa.ASSET=ASSET;qa.MAPPING={};qa.fixture.OUT=OUT;qa.fixture.PRIVATE=ROOT/'.secrets/armor-missing-parts-20261021.json'
qa.fixture.v.PREPARE+=r'''
from tio.roster_progression import profile
from tio.appearance import with_appearance
from tio.equipment import armor_rules
template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']);rules=armor_rules()
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 cases=[(1,b'A Helmet Rags',[208,223]),(2,b'B Helmet Rags',[208,223]),(2,b'C Exo',[263]),(2,b'D Exo SE',[264])]
 for identity,(resource,label,gear) in enumerate(cases,1):
  pet=decode_pet_info(profile(template,identity,resource,label),human_equipment=True)
  pet=with_appearance(pet,bytes((resource,0 if resource==1 else 10,0,1,0,0)))
  packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':20,'0x8c4b05':FLOORS[19],'0x8c4a07':250,'0x8c4ab1':250}))
  entries=[ItemRecord(50000+identity*1000+i,t,bytes(2),1,1,rules[t]['slot'],(600,600,600),bytes(4),None,bytes(3)) for i,t in enumerate(gear)]
  if index:entries.append(ItemRecord(50000+identity*1000+99,301,bytes(2),1,1,16,(600,600,600),bytes(4),None,bytes(3)))
  inventory=encode_item_list(identity,tuple(entries));OwnedPetStore(path).validate(packet,inventory,True)
  with sqlite3.connect(path) as db:
   assert excluded(db,name)
   if identity==1:db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(packet,inventory,name))
   else:db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,identity,1,packet,inventory))
'''
tree=ast.parse((ROOT/'tools/dog_models_gui_20261021.py').read_text(encoding='utf-8'));node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
exec(compile(ast.Module(body=[node],type_ignores=[]),'<missing parts graphical QA>','exec'))
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('provision','launch','cleanup','network'));parser.add_argument('--account',type=int,default=0);args=parser.parse_args()
 if args.mode=='provision':qa.fixture.provision()
 elif args.mode=='cleanup':qa.fixture.cleanup()
 elif args.mode=='network':qa.fixture.run()
 else:
  assert args.account in (0,1)
  if args.account:exec(compile(ast.unparse(node).replace("data['names'][0]","data['names'][1]").replace("data['passwords'][0]","data['passwords'][1]"),'<second owned fixture>','exec'))
  launch()
