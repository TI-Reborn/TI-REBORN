"""Classify isolated public-suite failures; never access hosted accounts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tools.verify_public_runtime_regression import BASE_FOLDER, ROOT, extract


CHILD = r'''
import importlib,json,pathlib,sqlite3,sys,traceback
sys.path[:0]=['tests','tools']
results={}
from test_shared_special_items import SharedSpecialItemsTests
case=SharedSpecialItemsTests('test_rejected_deployment_returns_native_failure_and_keeps_account_assets')
case.setUp();snapshots=[];original=case.rows
def capture():
 rows=original();snapshots.append(rows);return rows
case.rows=capture
try:
 try:case.test_rejected_deployment_returns_native_failure_and_keeps_account_assets();error=None
 except Exception:error=traceback.format_exc()
 before,after=snapshots
 changes={}
 for table in sorted(set(before)|set(after)):
  if before.get(table)==after.get(table):continue
  changes[table]={'rows_before':len(before.get(table,())),'rows_after':len(after.get(table,()))}
  if table=='battle_checkpoints':
   with sqlite3.connect(case.case.path) as db:columns=[r[1] for r in db.execute('PRAGMA table_info(battle_checkpoints)')]
   changed=[]
   for old,new in zip(before[table],after[table]):
    for column,a,b in zip(columns,old,new):
     if a!=b:
      if column=='snapshot':
       old_json,new_json=json.loads(a),json.loads(b)
       changed.append({'column':column,'top_level_changed':[key for key in set(old_json)|set(new_json) if old_json.get(key)!=new_json.get(key)]})
      else:changed.append({'column':column,'before':a,'after':b})
   changes[table]['changed_columns']=changed
 results['rejected_mine']={'error':error,'changed_tables':changes}
finally:case.doCleanups()

from test_trade_window_refresh import NativeTradeRefreshTests
case=NativeTradeRefreshTests('test_login_and_poll_after_market_close_keep_ui_query_driven_for_two_accounts')
case.setUp()
try:
 try:case.test_login_and_poll_after_market_close_keep_ui_query_driven_for_two_accounts();error=None
 except Exception:error=traceback.format_exc()
 sessions=list(case.game.server.multi.active_accounts.values())
 results['trade_window']={'error':error,'session_failures':[type(s.failure).__name__ if s.failure else None for s in sessions],
  'safe_error_events':[{'error':e['error']} for s in sessions for e in s.events if 'error' in e]}
finally:case.doCleanups()

from test_starting_funds import StartingFundsWorkflowTests,registration_app,KEY
case=StartingFundsWorkflowTests('test_registration_form_to_game_auth_and_onboarding_preserve_balance');case.setUp()
try:
 app=registration_app(case.path,KEY,'https://registration.example.test');app.config['TESTING']=True
 try:
  response=app.test_client().get('/register/',base_url='https://registration.example.test')
  results['registration']={'status':response.status_code,'has_csrf':b'name="csrf"' in response.data,'error':None}
 except Exception:results['registration']={'error':traceback.format_exc()}
finally:case.doCleanups()
print(json.dumps(results))
'''


def main():
    parser=__import__('argparse').ArgumentParser(description=__doc__)
    parser.add_argument('--candidate9',action='store_true')
    args=parser.parse_args()
    folder=ROOT/'reports/gameplay-completion/stage9-interfaces/public-regression-candidate' if args.candidate9 else BASE_FOLDER
    bundle=folder/('local-test-bundle.tar.gz' if args.candidate9 else 'test-bundle-batch-02.tar.gz')
    target=folder/'failure-state-diagnosis.json'
    if target.exists():raise ValueError('Preserve existing failure diagnosis')
    raw=bundle.read_bytes();env=dict(os.environ)
    for key in tuple(env):
        if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','STRIPE','SERVICE_KEY')):env.pop(key)
    with tempfile.TemporaryDirectory(prefix='tio-public-failure-diagnosis-') as directory:
        stage=Path(directory);extract(raw,stage)
        completed=subprocess.run([str(ROOT/'data/registration-check-env/Scripts/python.exe'),'-X','utf8','-c',CHILD],
            cwd=stage,env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if completed.returncode:raise RuntimeError(completed.stderr[-3000:])
        result=json.loads(completed.stdout)
    result.update(test_bundle_sha256=hashlib.sha256(raw).hexdigest(),
                  tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  hosted_player_data_opened=False,hosted_runtime_modified=False,graphical_client_acceptance=False)
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
