"""Owned excluded miner recruits: base, medium/hammer and heavy/nailgun."""
import argparse,ast,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
qa.OUT=ROOT/'reports/miner-model-20261021';qa.ASSET=ROOT/'assets/miner-colossus-v1';qa.fixture.OUT=qa.OUT;qa.fixture.PRIVATE=ROOT/'.secrets/miner-model-20261021.json'
PARTS=('freakminer_body','freakminer_legs','freakminer_medium_body','freakminer_medium_legs','freakminer_heavy_body','freakminer_heavy_legs','freakminer_heavy_helmet')
qa.MAPPING={**{f'base/models/{name}.mdjx':f'native/{name}.mdjx' for name in PARTS},'base/models/miner.jpg':'textures/miner.jpg'}
qa.fixture.v.PREPARE+=r'''
from tio.roster_progression import profile
template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex'])
for name in request:
 assert QA_LOGIN.fullmatch(name)
 for identity,label in ((2,'Colossus QA'),(3,'Miner Hammer QA'),(4,'Miner Heavy QA')):
  packet=profile(template,identity,6,label.encode('ascii'));pet=decode_pet_info(packet,human_equipment=True)
  packet=encode_pet_info(replace(pet,fields={**pet.fields,'0x8c4aef':8,'0x8c4b05':FLOORS[7],'0x8c4a07':155,'0x8c4ab1':155}))
  def equipped(i,t,slot):return ItemRecord(i,t,bytes(2),1,1,slot,(600,600,600),bytes(4),None,bytes(3))
  entries=(item(9201,335,current=600),item(9202,336,current=600),item(9203,37,30)) if identity==2 else (
   (equipped(9301,258,4),equipped(9302,259,8),equipped(9303,335,16)) if identity==3 else
   (equipped(9401,260,4),equipped(9402,261,8),equipped(9403,262,1),equipped(9404,336,16),item(9405,37,30)))
  inventory=encode_item_list(identity,entries);OwnedPetStore(path).validate(packet,inventory,True)
  with sqlite3.connect(path) as db:
   assert excluded(db,name);db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,identity,1,packet,inventory))
 SquadStore(path).assign(name,2,2);SquadStore(path).assign(name,3,3)
'''
# Same exact-owned native login/staging path used for the canine release.
tree=ast.parse((ROOT/'tools/dog_models_gui_20261021.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch');exec(compile(ast.Module(body=[node],type_ignores=[]),'<owned graphical model QA>','exec'))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','stage','launch','restore','cleanup','network'));mode=p.parse_args().mode
 if mode=='provision':qa.fixture.provision()
 elif mode=='cleanup':qa.fixture.cleanup()
 elif mode=='network':qa.fixture.run()
 elif mode=='launch':launch()
 else:getattr(qa,mode)()
