"""12 exact-owned hosted loadouts cover all four classes and female-only suits."""
import argparse,ast,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools import fighter_model_gui_20261021 as qa
OUT=ROOT/'reports/armor-fit-20261021';qa.OUT=OUT;qa.ASSET=ROOT/'assets/armor-fit-fixes-v1';qa.fixture.OUT=OUT;qa.fixture.PRIVATE=ROOT/'.secrets/armor-fit-20261021.json'
qa.MAPPING={'base/shared config/items.xml':'items.xml'} if (qa.ASSET/'items.xml').exists() else {}
LOADOUTS=[
 [(1,'M Light',[211,210,212]),(2,'F Light',[211,210,212]),(1,'M Heavy',[242,243,244]),(2,'F Heavy',[242,243,244]),(2,'F Exo',[263]),(2,'F Exo SE',[264])],
 [(1,'M Tank',[254]),(2,'F Tank SE',[256]),(3,'Dob Vest',[255]),(4,'Husky Solid',[265]),(5,'Shepherd SE',[266]),(6,'Miner Heavy',[262,260,261])]
]
qa.fixture.v.PREPARE+='\nLOADOUTS='+repr(LOADOUTS)+r'''
from tio.roster_progression import profile
from tio.appearance import with_appearance
from tio.equipment import armor_rules
template=bytes.fromhex(json.loads(Path('evidence/owned_pet_trial.json').read_text())['packet_hex']);rules=armor_rules()
for index,name in enumerate(request):
 assert QA_LOGIN.fullmatch(name)
 for identity,(resource,label,templates) in enumerate(LOADOUTS[index],2):
  human=resource in (1,2,6);packet=profile(template,identity,resource,label.encode('ascii'))
  pet=decode_pet_info(packet,human_equipment=human)
  pet=replace(pet,fields={**pet.fields,'0x8c4aef':20,'0x8c4b05':FLOORS[19],'0x8c4a07':250,'0x8c4ab1':250})
  if resource in (1,2):pet=with_appearance(pet,bytes((resource,0 if resource==1 else 10,0,1,0,0)))
  entries=[]
  for at,template_id in enumerate(templates):
   rule=rules[template_id]
   assert rule['dog']==(resource in (3,4,5)) and bool(rule.get('miner'))==(resource==6)
   assert not rule.get('female') or resource==2
   entries.append(ItemRecord(identity*10000+at,template_id,bytes(2),1,1,rule['slot'],(600,600,600),bytes(4),None,bytes(3)))
  weapon=301 if resource in (1,2) else 335 if resource==6 else None
  if weapon:entries.append(ItemRecord(identity*10000+99,weapon,bytes(2),1,1,16,(600,600,600),bytes(4),None,bytes(3)))
  packet=encode_pet_info(pet);inventory=encode_item_list(identity,tuple(entries));OwnedPetStore(path).validate(packet,inventory,human)
  with sqlite3.connect(path) as db:
   assert excluded(db,name);db.execute('INSERT INTO owned_pets VALUES (?,?,?,?,?)',(name,identity,int(human),packet,inventory))
'''
tree=ast.parse((ROOT/'tools/dog_models_gui_20261021.py').read_text(encoding='utf-8'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='launch')
# Release the owned process even when a staged-file assertion fails.
at=next(i for i,n in enumerate(node.body) if isinstance(n,ast.For) and 'MAPPING' in ast.unparse(n.iter))
guard=next(i for i,n in enumerate(node.body) if isinstance(n,ast.Try))
node.body[guard].body=node.body[at:guard]+node.body[guard].body
del node.body[at:guard]
exec(compile(ast.Module(body=[node],type_ignores=[]),'<owned armor graphical QA>','exec'))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('provision','launch','cleanup','network','stage','restore'));p.add_argument('--account',type=int,default=0,choices=(0,1));args=p.parse_args()
 if args.mode=='provision':qa.fixture.provision()
 elif args.mode=='cleanup':qa.fixture.cleanup()
 elif args.mode=='network':qa.fixture.run()
 elif args.mode=='restore':
  journal=OUT/'qa-stage.json';record=json.loads(journal.read_text());assert len(record['files'])==1
  row=record['files'][0];assert row['path']=='base/shared config/items.xml';actual=(qa.GAME/row['path']).read_bytes()
  if qa.sha(actual)==row['after']:qa.restore()
  else:
   known=[(OUT/n).read_bytes() for n in ('hosted-items-before.xml','hosted-items-fixed.xml') if (OUT/n).exists()]
   assert actual in known,'Unrecognized private client change; preserve for investigation'
   old=(OUT/'qa-original-files'/row['path']).read_bytes();assert qa.sha(old)==row['before']
   (OUT/'qa-b9-delivered.xml').write_bytes(actual);qa.atomic(qa.GAME/row['path'],old)
   (OUT/'qa-restored.json').write_text(json.dumps(dict(passed=True,files=1,all_original_bytes_restored=True,reason='Authoritative B9 delivery superseded private staged XML; restored verified public bytes'),indent=2));journal.unlink()
   print(json.dumps(dict(restored=True,files=1,known_b9_delivery=True)))
 elif args.mode=='stage':qa.stage()
 else:
  # Select the second of our own accounts without changing its stored credentials.
  if args.account:
   source=ast.unparse(node).replace("data['names'][0]","data['names'][1]").replace("data['passwords'][0]","data['passwords'][1]")
   exec(compile(source,'<second owned armor QA>','exec'))
  launch()
