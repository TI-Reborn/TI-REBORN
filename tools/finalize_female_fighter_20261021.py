"""Package the published editable female asset and final verification evidence."""
import json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_female_fighter_20261021 import validate,verify,ASSET,OUT,VERSION,sha,qa
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
validate();verify()
proof=json.loads((OUT/'gui-visual-published.json').read_text());assert proof['passed'] and proof['published_assets_only']
auth=json.loads((OUT/'gui-status-published.json').read_text());assert auth['authenticated'] and auth['worldStartSent'] and not auth['runtime_errors']
network=json.loads((OUT/'hosted-admission.json').read_text());assert network['passed']
cleanup=json.loads((OUT/'fixture-cleanup.json').read_text());assert cleanup['preexisting_players_preserved'] and cleanup['integrity']=='ok'
local=json.loads((OUT/'local-installed.json').read_text());assert local['passed'] and local['version']==VERSION
update=json.loads((OUT/'launcher-update.json').read_text());assert update['passed'] and update['Version']==VERSION and update['Metrics']['PayloadRequests']==6
state=remote(STATE,{});publication=json.loads((OUT/'publication.json').read_text());assert state['service']==publication['service'] and state['integrity']=='ok'
assert state['accounts']==26 and state['clans']==4
(OUT/'final-hosted-state.json').write_text(json.dumps(state,indent=2))
validation=json.loads((OUT/'validation.json').read_text());validation.update(version=VERSION,published=True,installed_local=local['root'],
 real_native_graphical_client_verified=True,hosted_two_accounts_verified=True,qa_accounts_cleaned=True,preexisting_players_preserved=True,
 server_backup=publication['backup'],manifest_sha256=publication['manifest_sha256'])
(ASSET/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
(ASSET/'installed.json').write_text(json.dumps(dict(version=VERSION,manifest_sha256=publication['manifest_sha256'],mapping=qa.MAPPING,local_root=local['root']),indent=2)+'\n')
archive=ROOT/'output/female-fighter-scout-v1.zip';archive.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for f in sorted(ASSET.rglob('*')):
  if f.is_file() and f.suffix not in ('.blend1',):z.write(f,f.relative_to(ASSET.parent))
 for name in ('mdjx_mesh.py','female_fighter_blender_20261021.py','validate_female_fighter_blender_20261021.py','validate_fighter_model_blender_20261021.py'):
  z.write(ROOT/'tools'/name,'female-fighter-v1/build-tools/'+name)
 for f in (ROOT/'tools/FemaleFighterTexturePack').glob('*'):
  if f.is_file():z.write(f,'female-fighter-v1/build-tools/FemaleFighterTexturePack/'+f.name)
 for name in ('validation.json','https-verification.json','gui-visual-candidate.json','gui-visual-published.json','hosted-admission.json','launcher-update.json','local-installed.json','fixture-cleanup.json'):
  z.write(OUT/name,'female-fighter-v1/verification/'+name)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
result=dict(passed=True,archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()),version=VERSION,rig_bones=51,
 published=True,local_installed=True,accounts=state['accounts'],clans=state['clans'],temporary_accounts_removed=True)
(OUT/'completion.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
