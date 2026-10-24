"""Deploy the bounded recovery schema/bridge and prebuilt portal; never restore saves."""
import base64, hashlib, json, subprocess, sys, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_portal_stage3_remote import REMOTE
OUT=ROOT/'reports/password-recovery-20261023';KEY=str(Path.home()/'.ssh/tio_server')
SSH=['ssh','-i',KEY,'-o','BatchMode=yes','root@185.184.42.88','python3 -']

def remote(script):
 r=subprocess.run(SSH,input=script,text=True,capture_output=True,timeout=180)
 if r.returncode:
  (OUT/'deployment-private-error.log').write_text(r.stderr,encoding='utf-8')
  raise RuntimeError('Recovery deployment failed; inspect private diagnostics')
 return json.loads(r.stdout)

def main():
 prior=json.loads((OUT/'backup.json').read_text())
 assert prior['previous_portal_release']=='/opt/tio-portal/releases/tireborn-20261021-account-session'
 assert prior['sqlite_integrity']=='ok' and prior['website_dump_structure_verified']
 assert not (OUT/'deployment.json').exists()
 migration=ROOT/'web/prisma/migrations/20261023150000_password_recovery/migration.sql'
 config={'backup':prior['backup'],'previous':prior['previous_portal_release'],
  'old_bridge_hash':'db4d4197c2106f650b1b7386fb9b4b06ce4062f2c042b54a32c390134d318674',
  'old_cleanup_hash':'aa96983ccda62bf6e95d6230f8bd30bf0b3e7430e3bdf5490a29bc5cb533d48c',
  'migration':migration.read_text(), 'migration_hash':hashlib.sha256(migration.read_bytes()).hexdigest(),
  'migration_id':str(uuid.uuid4()),
  'bridge':base64.b64encode((ROOT/'registration/game_bridge.py').read_bytes()).decode(),
  'cleanup':base64.b64encode((ROOT/'web/deploy/cleanup.sql').read_bytes()).decode()}
 script=r'''import base64,hashlib,json,os,shutil,subprocess,py_compile
from pathlib import Path
c=CONFIG
os.umask(0o077)
b=Path(c['backup']);assert (b/'backup-manifest.json').is_file() and (b/'website.dump').is_file() and (b/'reservation.sqlite3').is_file()
assert str(Path('/opt/tio-portal/current').resolve())==c['previous']
bridge=Path('/opt/tio-emulator/registration/game_bridge.py');cleanup=Path('/opt/tio-portal/cleanup.sql')
assert hashlib.sha256(bridge.read_bytes()).hexdigest()==c['old_bridge_hash']
assert hashlib.sha256(cleanup.read_bytes()).hexdigest()==c['old_cleanup_hash']
for source in [bridge,cleanup]:shutil.copy2(source,b/(source.name+'.before-recovery'))
# Additive schema only. Lock/snapshot all original profiles and verify them
# unchanged inside the migration transaction. No account field is rewritten.
sql='BEGIN; SET LOCAL ROLE tionline; LOCK TABLE "User" IN SHARE MODE; CREATE TEMP TABLE recovery_original_users AS SELECT * FROM "User"; '+c['migration']+"\nDO $$ BEGIN IF EXISTS ((SELECT * FROM recovery_original_users EXCEPT SELECT * FROM \"User\") UNION ALL (SELECT * FROM \"User\" EXCEPT SELECT * FROM recovery_original_users)) THEN RAISE EXCEPTION 'Existing profile changed'; END IF; END $$;"+"INSERT INTO \"_prisma_migrations\" (id,checksum,finished_at,migration_name,logs,rolled_back_at,started_at,applied_steps_count) VALUES ('"+c['migration_id']+"','"+c['migration_hash']+"',now(),'20261023150000_password_recovery',NULL,NULL,now(),1); COMMIT;"
r=subprocess.run(['runuser','-u','postgres','--','psql','-Xq','-v','ON_ERROR_STOP=1','-d','tionline_web'],input=sql,text=True,capture_output=True)
if r.returncode:raise RuntimeError(r.stderr)
for target,encoded in [(bridge,c['bridge']),(cleanup,c['cleanup'])]:
 temporary=target.with_name(target.name+'.recovery-new')
 with temporary.open('xb') as f:f.write(base64.b64decode(encoded))
 temporary.chmod(target.stat().st_mode & 0o777);os.chown(temporary,target.stat().st_uid,target.stat().st_gid)
 if target==bridge:py_compile.compile(str(temporary),cfile=str(b/'recovery-bridge.pyc'),doraise=True)
 temporary.replace(target)
subprocess.run(['systemctl','restart','tio-game-api'],check=True)
assert subprocess.check_output(['systemctl','is-active','tio-game-api'],text=True).strip()=='active'
print(json.dumps({'schema_applied':True,'existing_profiles_preserved':True,'bridge_updated':True,'cleanup_updated':True,'game_restarted':False}))
'''.replace('CONFIG',repr(config),1)
 data=remote(script);(OUT/'schema-bridge.json').write_text(json.dumps(data,indent=2))
 archive=OUT/'portal-password-recovery-final.tar.gz';remote_archive='/root/tio-password-recovery-20261023.tar.gz'
 subprocess.run(['scp','-i',KEY,'-o','BatchMode=yes',str(archive),'root@185.184.42.88:'+remote_archive],check=True,capture_output=True)
 settings={'archive':remote_archive,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'backup':prior['backup'],'previous_release':prior['previous_portal_release'],'release_id':'tireborn-20261023-password-recovery','dist_dir':'.next-password-recovery'}
 script=REMOTE.replace('CONFIGURATION',repr(settings),1)
 # Preserve static chunks used by already-open tabs on the previous release.
 script=script.replace('point(target)\ntry:','''import shutil
old_config=json.loads((previous/'server.js').read_text().split('const nextConfig = ',1)[1].split('\\n',1)[0])
old_static=previous/old_config['distDir']/'static';new_static=target/configuration['dist_dir']/'static'
for source in old_static.rglob('*'):
 if source.is_file():
  destination=new_static/source.relative_to(old_static)
  if not destination.exists():destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
point(target)
try:''',1)
 data=remote(script);(OUT/'deployment.json').write_text(json.dumps(data,indent=2));print(json.dumps(data))

if __name__=='__main__':main()
