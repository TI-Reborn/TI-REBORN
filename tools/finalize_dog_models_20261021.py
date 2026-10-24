"""Package all three editable canine assets after hosted and graphical QA."""
import json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_dog_models_20261021 import validate,verify,ASSET,OUT,VERSION,sha,qa
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
validate();verify()
visual=json.loads((OUT/'gui-visual-published.json').read_text());assert visual['passed'] and visual['published_assets_only'] and len(visual['breeds'])==3
auth=json.loads((OUT/'gui-status-published.json').read_text());assert auth['authenticated'] and auth['worldStartSent'] and not auth['runtime_errors']
network=json.loads((OUT/'hosted-admission.json').read_text());assert network['passed']
cleanup=json.loads((OUT/'fixture-cleanup.json').read_text());assert cleanup['unrelated_rows_preserved'] and cleanup['integrity']=='ok'
for mode in ('qa','saved'):
 installed=json.loads((OUT/(mode+'-installed.json')).read_text());assert installed['passed'] and installed['version']==VERSION
 update=json.loads((OUT/(mode+'-launcher-update.json')).read_text());assert update['passed'] and update['Version']==VERSION and update['Metrics']['PayloadRequests']==6
state=remote(STATE,{});publication=json.loads((OUT/'publication.json').read_text());before=json.loads((OUT/'hosted-before.json').read_text())
assert state['service']==publication['service']==before['service'] and state['integrity']=='ok'
assert state['accounts']==before['accounts'] and state['clans']==before['clans']
changed=[t for t in before['protected'] if state['protected'][t]!=before['protected'][t]]
if changed:
 audit=json.loads((OUT/'clan-maintenance-audit.json').read_text())
 assert changed==['clans'] and audit['passed'] and audit['publication_matches_current']
 assert audit['baseline_clans_sha256']==before['protected']['clans'] and audit['current_clans_sha256']==state['protected']['clans']
(OUT/'final-hosted-state.json').write_text(json.dumps(state,indent=2))
validation=json.loads((OUT/'validation.json').read_text());validation.update(published=True,local_installed=True,
 hosted_graphical_three_breeds_verified=True,hosted_two_accounts_protocol_verified=True,qa_accounts_cleaned=True,
 preexisting_players_preserved=True,expected_server_maintenance_only=changed,server_backup=publication['backup'],manifest_sha256=publication['manifest_sha256'],
 doberman_armor_255_reviewed=True,full_graphical_battle_and_armor_regression=False)
(ASSET/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
installed=dict(version=VERSION,manifest_sha256=publication['manifest_sha256'],mapping=qa.MAPPING,
 local_root=json.loads((OUT/'saved-installed.json').read_text())['root'],server_backup=publication['backup'])
(ASSET/'installed.json').write_text(json.dumps(installed,indent=2)+'\n')
archive=ROOT/'output/dog-mercenaries-v1.zip';archive.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for f in sorted(ASSET.rglob('*')):
  if f.is_file() and f.suffix not in ('.blend1',):z.write(f,f.relative_to(ASSET.parent))
 for name in ('mdjx_mesh.py','dog_native_animation.py','dog_models_blender_20261021.py','validate_dog_models_blender_20261021.py','dog_models_showcase_20261021.py'):
  z.write(ROOT/'tools'/name,'dog-mercenaries-v1/build-tools/'+name)
 # Include exact original compatible topology and clip inputs for inspection.
 for name in ['dog_skeleton.mdjx','dog_mask.png']+[f'dog_{b}{ext}' for b in ('doberman','huski','alsatian') for ext in ('.mdjx','.jpg')]:
  z.write(OUT/'source/base/models'/name,'dog-mercenaries-v1/source-inputs/'+name)
 for clip in ('dog_idle','dog_run','dog_attack','dog_sit','dog_sit_idle','dog_death_v01'):
  z.write(OUT/'source/base/models/anim'/(clip+'.adjx'),'dog-mercenaries-v1/source-inputs/anim/'+clip+'.adjx')
 for name in ('validation.json','https-verification.json','gui-visual-candidate.json','gui-visual-published.json','hosted-admission.json','qa-launcher-update.json','saved-installed.json','fixture-cleanup.json','clan-maintenance-audit.json'):
  z.write(OUT/name,'dog-mercenaries-v1/verification/'+name)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
result=dict(passed=True,version=VERSION,archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()),
 breeds=3,blender_bones_per_dog=31,game_deform_bones_per_dog=26,published=True,local_installed=True,
 accounts=state['accounts'],clans=state['clans'],temporary_accounts_removed=True,existing_player_data_preserved=True)
(OUT/'completion.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
