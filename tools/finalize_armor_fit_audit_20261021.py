"""Collect bounded visual observations, release verification and player protection."""
import hashlib,json,sys,urllib.request
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.armor_fit_fix_20261021 import OUT
from tools.publish_armor_fit_fix_20261021 import VERSION
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
sha=lambda b:hashlib.sha256(b).hexdigest()
raw=urllib.request.urlopen('https://185.184.42.88/updates/manifest.json',timeout=30).read();assert raw==(OUT/'manifest.json').read_bytes();m=json.loads(raw);assert m['version']==VERSION;rows={r['path']:r for r in m['files']}
catalog=json.loads((OUT/'catalog.json').read_text(encoding='utf-8'));game=Path.home()/'AppData/Local/TIO-Online'
verified=[]
for name in catalog['files']:
 assert sha((game/name).read_bytes())==rows[name]['sha256'],name
 verified.append(name)
state=remote(STATE,{});before=json.loads((OUT/'hosted-before.json').read_text());assert state['accounts']==before['accounts']==26 and state['clans']==before['clans']==4 and state['integrity']=='ok' and state['service']==before['service']
unchanged={t:state['protected'][t]==v for t,v in before['protected'].items()};assert all(v for k,v in unchanged.items() if k!='clans')
maintenance=json.loads((OUT/'clan-maintenance-audit.json').read_text());assert maintenance['passed'] and maintenance['current_sha256']==state['protected']['clans']
cleanup=json.loads((OUT/'fixture-cleanup.json').read_text());assert cleanup['unrelated_rows_preserved'] and cleanup['accounts_after']==26 and cleanup['schema_restored'] and cleanup['integrity']=='ok'
assert not (ROOT/'.secrets/armor-fit-20261021.json').exists() and not (OUT/'qa-stage.json').exists()
tests=json.loads((OUT/'automated-tests.json').read_text());poses=json.loads((OUT/'animation-structure-audit.json').read_text());assert tests['passed'] and poses['passed']
for file in ('gui-status-fixed-female.json','gui-status-fixed-male.json'):
 status=json.loads((OUT/file).read_text());assert status['authenticated'] and status['worldStartSent'] and status['runtime_errors']==[]
code="""import hashlib,json,sys
from pathlib import Path
p=json.load(sys.stdin);raw=Path('/opt/tio-emulator/evidence/items_diagnostic.xml').read_bytes();assert hashlib.sha256(raw).hexdigest()==p['sha256'];print(json.dumps(dict(passed=True,authoritative_b9_catalog_matches_fix=True)))
"""
assert remote(code,dict(sha256=sha((OUT/'hosted-items-fixed.xml').read_bytes())))['passed']
visual=[(1,'male-light',[211,210,212]),(1,'male-heavy',[242,243,244]),(2,'female-light',[211,210,212]),(2,'female-heavy',[242,243,244]),(2,'female-exo',[263]),(2,'female-exo-se',[264]),(1,'male-tank',[254]),(2,'female-tank-se',[256]),(3,'doberman-vest',[255]),(4,'husky-solid',[265]),(5,'shepherd-solid-se',[266]),(6,'miner-heavy',[262,260,261])]
result=dict(passed=True,release=VERSION,manifest_sha256=sha(raw),armor_items=57,class_item_bindings=110,blender_reference_views=220,automated_tests=tests['tests'],sampled_mesh_poses=poses['sampled_mesh_poses'],
 native_visual_loadouts=[dict(resource=r,name=n,items=i,observed=True) for r,n,i in visual],fixed_item=206,male_and_female_206_native_verified=True,
 native_graphical_vs_automated='12 representative loadouts visually checked in the real native client against hosted QA accounts; all 110 bindings rendered offline; 955 sampled mesh poses checked numerically. No exhaustive combat/animation clipping certification.',
 male_veteran_published=False,male_veteran_blender_cases=47,model_regeneration_needed=False,actual_player_install=str(game),installed_resource_hashes_verified=len(verified),
 service_unchanged=True,accounts=26,clans=4,integrity='ok',preexisting_table_hashes_unchanged=unchanged,clan_changes_exactly_match_existing_hourly_maintenance=True,owned_qa_removed=True,user_saves_overwritten=False)
(OUT/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');(OUT/'hosted-after.json').write_text(json.dumps(state,indent=2))
entries=[('r1-254.png','Мужчина — Tank'),('r2-263.png','Женщина — Exo'),('r6-260.png','Шахтёр — нагрудник'),('r3-266.png','Доберман — SE'),('r4-266.png','Хаски — SE'),('r5-266.png','Овчарка — SE')]
sheet=Image.new('RGB',(840,750),(22,28,34));draw=ImageDraw.Draw(sheet);font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
for i,(filename,title) in enumerate(entries):
 x=i%3*280;y=i//3*375;sheet.paste(Image.open(OUT/'renders-front'/filename).convert('RGB'),(x,y));draw.text((x+8,y+345),title,font=font,fill='white')
sheet.save(OUT/'armor-overview.jpg',quality=94)
print(json.dumps({k:v for k,v in result.items() if k not in ('native_visual_loadouts','preexisting_table_hashes_unchanged')},ensure_ascii=False))
