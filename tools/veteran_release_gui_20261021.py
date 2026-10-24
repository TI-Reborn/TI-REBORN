"""Published Veteran on two exact-owned, ranking-excluded hosted QA accounts."""
import argparse,ast,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
from tools.publish_veteran_20261021 import OUT,ASSET,MAPPING
qa.OUT=OUT;qa.ASSET=ASSET;qa.MAPPING=MAPPING
qa.fixture.OUT=OUT;qa.fixture.PRIVATE=ROOT/'.secrets/veteran-release-20261021.json'
qa.fixture.v.PREPARE+=r'''
from tio.roster_progression import profile
from tio.appearance import with_appearance
from tio.equipment import armor_rules
template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']);rules=armor_rules()
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 cases=[(b'V Base',[]),(b'V Helmet Rags',[208,223]),(b'V Pantsu',[206]),
        (b'V Light',[211,210,212]),(b'V Heavy',[242,243,244]),(b'V Tank',[254])]
 for identity,(label,gear) in enumerate(cases,1):
  pet=decode_pet_info(profile(template,identity,1,label),human_equipment=True)
  pet=with_appearance(pet,bytes((1,0,0,1,0,0)))
  packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':20,'0x8c4b05':FLOORS[19],'0x8c4a07':250,'0x8c4ab1':250}))
  entries=[ItemRecord(60000+identity*1000+i,t,bytes(2),1,1,rules[t]['slot'],(600,600,600),bytes(4),None,bytes(3)) for i,t in enumerate(gear)]
  if index:entries.append(ItemRecord(60000+identity*1000+99,301,bytes(2),1,1,16,(600,600,600),bytes(4),None,bytes(3)))
  inventory=encode_item_list(identity,tuple(entries));OwnedPetStore(path).validate(packet,inventory,True)
  with sqlite3.connect(path) as db:
   assert excluded(db,name)
   if identity==1:db.execute('UPDATE owned_pets SET pet_packet=?,inventory_packet=? WHERE account=? AND pet_id=1',(packet,inventory,name))
   else:db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,identity,1,packet,inventory))
'''
tree=ast.parse((ROOT/'tools/dog_models_gui_20261021.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
exec(compile(ast.Module(body=[node],type_ignores=[]),'<published Veteran QA>','exec'))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','network','launch','cleanup'));p.add_argument('--account',type=int,choices=(0,1),default=0);args=p.parse_args()
 if args.mode=='provision':qa.fixture.provision()
 elif args.mode=='network':qa.fixture.run()
 elif args.mode=='cleanup':qa.fixture.cleanup()
 else:
  if args.account:exec(compile(ast.unparse(node).replace("data['names'][0]","data['names'][1]").replace("data['passwords'][0]","data['passwords'][1]"),'<second Veteran QA>','exec'))
  launch()
