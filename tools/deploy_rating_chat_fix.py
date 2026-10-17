"""Deploy the public mining rating query fix without replacing hosted saves."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote

CODE=r'''
import pathlib,json,sys,sqlite3,subprocess,tempfile,shutil,hashlib,io,unittest,contextlib
from contextlib import closing
data=json.load(sys.stdin);target=pathlib.Path('tio/mining_service.py')
assert hashlib.sha256(target.read_bytes()).hexdigest()==data['expected']
# Test the candidate in a separate Python process's memory before deployment.
from tio import mining_service
exec(compile(data['source'],str(target),'exec'),mining_service.__dict__)
namespace={'__name__':'rating_chat_regression'}
exec(compile(data['test'],'test_mining_rating_menu.py','exec'),namespace)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(namespace['MiningRatingMenuTests'])
stream=io.StringIO();result=unittest.TextTestRunner(stream=stream).run(suite)
assert result.wasSuccessful(),stream.getvalue()
path=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
def idle():
 with closing(sqlite3.connect(path)) as db:
  for t in ('battle_checkpoints','battle_settlement_jobs'):
   assert db.execute('SELECT count(*) FROM '+t).fetchone()[0]==0,'Active battles; wait for completion'
def fingerprint():
 with closing(sqlite3.connect(path)) as db:
  db.execute('BEGIN')
  assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:hashlib.sha256(repr(sorted(map(repr,db.execute('SELECT * FROM "'+t+'"').fetchall()))).encode()).hexdigest()
   for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
def backup():
 with closing(sqlite3.connect(path)) as src,closing(sqlite3.connect(folder/path.name)) as dst:src.backup(dst)
 (folder/path.name).chmod(0o600)
idle()
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
folder=pathlib.Path(tempfile.mkdtemp(prefix='tio-before-rating-chat-fix-',dir='/root'));folder.chmod(0o700)
backup();shutil.copy2(target,folder/'mining_service.py');shutil.copy2('/etc/tio-server/server.toml',folder/'server.toml')
(folder/'server.toml').chmod(0o600)
idle();subprocess.run(['systemctl','stop','tio-server'],check=True)
try:
 idle();backup();before=fingerprint()
 stage=target.with_suffix('.py.rating-new');stage.write_text(data['source'],encoding='utf-8');stage.chmod(0o644);stage.replace(target)
 checked=subprocess.run(['runuser','-u','tio','--','.venv/bin/python','-m','server','--config','/etc/tio-server/server.toml','--check'],capture_output=True,text=True)
 assert checked.returncode==0,checked.stderr
 assert fingerprint()==before,'Hosted saves changed during code update'
except BaseException:
 shutil.copy2(folder/'mining_service.py',target)
 raise
finally:
 subprocess.run(['systemctl','start','tio-server'],check=True)
receipt=dict(backup=str(folder),candidate_regression_tests=result.testsRun,database_rows_preserved=True,
 preflight_passed=True,hash=hashlib.sha256(target.read_bytes()).hexdigest(),graphical_clients_used=False)
(folder/'receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
'''

if __name__=='__main__':
    folder=ROOT/'reports/rating-chat-fix'
    expected=json.loads((folder/'inspection.json').read_text())['hash']
    result=remote(CODE,dict(expected=expected,source=(ROOT/'tio/mining_service.py').read_text(),
                            test=(ROOT/'tests/test_mining_rating_menu.py').read_text()))
    (folder/'deployment.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
