"""Use the established portal backup/preflight/symlink/rollback deployment."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_portal_stage3_remote import REMOTE
OUT=ROOT/'reports/account-session-20261021';KEY=str(Path.home()/'.ssh/tio_server')
archive=OUT/'portal-account-session.tar.gz';prior=json.loads((OUT/'backup.json').read_text())
assert prior['previous_portal_release']=='/opt/tio-portal/releases/tireborn-20261019-bug-reports-v3'
remote_archive='/root/tio-account-session-20261021.tar.gz';checker='/root/tio-account-session-acceptance-20261021.py'
for source,dest in ((archive,remote_archive),(ROOT/'tools/portal_session_acceptance_remote.py',checker)):
 subprocess.run(['scp','-i',KEY,'-o','BatchMode=yes',str(source),'root@185.184.42.88:'+dest],capture_output=True,check=True)
settings=dict(archive=remote_archive,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),backup=prior['backup'],previous_release=prior['previous_portal_release'],release_id='tireborn-20261021-account-session',dist_dir='.next-account-session')
script=REMOTE.replace('CONFIGURATION',repr(settings),1)
marker="        else:raise RuntimeError('Release preflight health failed; inspect private preflight log')"
assert marker in script
script=script.replace(marker,marker+"\n        import importlib.util\n        spec=importlib.util.spec_from_file_location('account_session_acceptance',"+repr(checker)+")\n        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n        acceptance=module.run('http://127.0.0.1:3002',0)\n        (backup/'account-session-preflight.json').write_text(json.dumps(acceptance,indent=2))")
marker="game=subprocess.check_output"
assert marker in script
# Arm already-issued long-lived sessions only after the new release is healthy.
# This updates authorization deadlines, never users, passwords or player data.
script=script.replace(marker,"subprocess.run(['runuser','-u','postgres','--','psql','-X','-d','tionline_web','-c',\"UPDATE \\\"Session\\\" SET \\\"expiresAt\\\"=LEAST(\\\"expiresAt\\\",now()+interval '5 minutes')\"],check=True,stdout=subprocess.DEVNULL)\n"+marker)
script=script.replace("'linux_release_preflight':'ok',","'linux_release_preflight':'ok','account_session_acceptance':acceptance,'legacy_session_deadlines_armed':True,")
r=subprocess.run(['ssh','-i',KEY,'-o','BatchMode=yes','root@185.184.42.88','python3 -'],input=script,capture_output=True,text=True,timeout=180)
if r.returncode:raise RuntimeError(r.stderr[-2000:])
data=json.loads(r.stdout);(OUT/'deployment.json').write_text(json.dumps(data,indent=2));print(json.dumps(data))
