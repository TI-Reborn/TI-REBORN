"""Verify the published miner, audit saves and package its Blender sources."""
import ast,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.publish_miner_model_20261021 import validate,verify,ASSET,OUT,VERSION,sha,qa
from tools.deploy_stage4_economy import remote
from tools.publish_ability_icons_20261020 import STATE
validate();verify()
visual=json.loads((OUT/'gui-visual-published.json').read_text());assert visual['passed'] and visual['published_assets_only'] and len(visual['loadouts'])==3
auth=json.loads((OUT/'gui-status-published.json').read_text());assert auth['authenticated'] and auth['worldStartSent'] and not auth['runtime_errors']
assert json.loads((OUT/'hosted-admission.json').read_text())['passed']
cleanup=json.loads((OUT/'fixture-cleanup.json').read_text());assert cleanup['unrelated_rows_preserved'] and cleanup['integrity']=='ok'
for mode in ('qa','saved'):
 installed=json.loads((OUT/(mode+'-installed.json')).read_text());update=json.loads((OUT/(mode+'-launcher-update.json')).read_text())
 assert installed['passed'] and installed['version']==VERSION and update['passed'] and update['Version']==VERSION and update['Metrics']['PayloadRequests']==8
state=remote(STATE,{});publication=json.loads((OUT/'publication.json').read_text());before=json.loads((OUT/'hosted-before.json').read_text())
assert state['service']==publication['service']==before['service'] and state['integrity']=='ok'
assert state['accounts']==before['accounts'] and state['clans']==before['clans']
changed=[t for t in before['protected'] if state['protected'][t]!=before['protected'][t]]
if changed:
 assert changed==['clans'],'Inspect genuine player activity; never restore hosted data'
 tree=ast.parse((ROOT/'tools/audit_dog_model_hosted_state_20261021.py').read_text())
 code=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CODE' for t in n.targets)))
 # Pin both read-only snapshots to this release's verified state history.
 start=code.index('paths=');end=code.index('\nstates=',start)
 code=code[:start]+"paths="+repr(dict(baseline='/root/tio-before-dog-models-a94awnhn/reservation.sqlite3',publication=publication['backup']+'/reservation.sqlite3',current='/var/lib/tio-server/reservation.sqlite3'))+code[end:]
 audit=remote(code,dict(baseline_clans_sha256=before['protected']['clans']));assert audit['passed'] and audit['current_clans_sha256']==state['protected']['clans']
 (OUT/'clan-maintenance-audit.json').write_text(json.dumps(audit,indent=2))
(OUT/'final-hosted-state.json').write_text(json.dumps(state,indent=2))
validation=json.loads((OUT/'validation.json').read_text());validation.update(published=True,local_installed=True,hosted_three_loadouts_graphically_verified=True,
 hosted_two_accounts_protocol_verified=True,temporary_accounts_removed=True,existing_player_data_preserved=True,expected_server_maintenance_only=changed,
 server_backup=publication['backup'],manifest_sha256=publication['manifest_sha256'],full_graphical_battle_regression=False)
(ASSET/'validation.json').write_text(json.dumps(validation,indent=2)+'\n')
(ASSET/'installed.json').write_text(json.dumps(dict(version=VERSION,manifest_sha256=publication['manifest_sha256'],mapping=qa.MAPPING,
 local_root=json.loads((OUT/'saved-installed.json').read_text())['root'],server_backup=publication['backup']),indent=2)+'\n')
archive=ROOT/'output/miner-colossus-v1.zip';archive.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for f in sorted(ASSET.rglob('*')):
  if f.is_file() and f.suffix!='.blend1':z.write(f,f.relative_to(ASSET.parent))
 for name in ('mdjx_mesh.py','miner_native_mesh.py','dog_native_animation.py','dog_models_blender_20261021.py','miner_model_blender_20261021.py','validate_miner_blender_20261021.py'):
  z.write(ROOT/'tools'/name,'miner-colossus-v1/build-tools/'+name)
 for name in ['freakminer_skeleton.mdjx','miner.jpg','miner_mask.png']+[p['part']+'.mdjx' for p in json.loads((ASSET/'model.json').read_text())['parts']]:
  z.write(OUT/'source/base/models'/name,'miner-colossus-v1/source-inputs/'+name)
 for name in json.loads((ASSET/'model.json').read_text())['animations']:
  z.write(OUT/'source/base/models/anim'/(name+'.adjx'),'miner-colossus-v1/source-inputs/anim/'+name+'.adjx')
 for name in ('validation.json','https-verification.json','gui-visual-candidate.json','gui-visual-published.json','hosted-admission.json','qa-launcher-update.json','saved-installed.json','fixture-cleanup.json'):
  z.write(OUT/name,'miner-colossus-v1/verification/'+name)
 if (OUT/'clan-maintenance-audit.json').exists():z.write(OUT/'clan-maintenance-audit.json','miner-colossus-v1/verification/clan-maintenance-audit.json')
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
result=dict(passed=True,version=VERSION,rig_bones=50,archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive.read_bytes()),
 published=True,local_installed=True,accounts=state['accounts'],clans=state['clans'],temporary_accounts_removed=True,existing_player_data_preserved=True)
(OUT/'completion.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
