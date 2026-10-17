"""Inspect temporary authoritative state after three failed native TCP assertions.

Runs only the immutable public .5 test bundle locally. No SSH, production
database, real game clients, account credentials or current local runtime.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tools.verify_public_runtime_regression import BASE_FOLDER, extract

CHILD = r'''
from contextlib import closing
import importlib,json,pathlib,sqlite3,sys,traceback
sys.path[:0]=['tests','tools']
from tio.protocol.item_list import decode_item_list
targets=(('test_character_slots','CharacterSlotsTCPTests','test_native_creation_secondary_selection_purchase_restart_primary_preserved'),
 ('test_multi_account','MultiAccountTests','test_premium_purchase_and_personal_shop_prices'),
 ('test_multi_account','MultiAccountTests','test_city_weapon_swap_tcp_persists_and_is_account_isolated'))
if len(sys.argv)>1 and sys.argv[1]=='slots':targets=targets[:1]
sync=len(sys.argv)>1 and sys.argv[1]=='slots-sync'
if sync:targets=targets[:1]
results=[]
for module,cls,method in targets:
 case=getattr(importlib.import_module(module),cls)(method)
 case.setUp()
 tracked=[]
 if sync:
  original_connect=case.connect
  def connect(*args,**kwargs):
   peer=original_connect(*args,**kwargs);tracked.append(peer);return peer
  case.connect=connect
 try:
  error=None
  try:getattr(case,method)()
  except Exception as failure:error=traceback.format_exc()
  if sync and tracked:case.case.ping(tracked[-1])
  path=getattr(case,'path',None) or case.config.database
  with closing(sqlite3.connect(path)) as db:
   wallets=db.execute('SELECT account,credits,gold FROM wallets ORDER BY account').fetchall()
   inventory=[{'account':account,'pet':pet,'slots':[item.client_slot for item in decode_item_list(raw)[1]]}
    for account,pet,raw in db.execute('SELECT account,pet_id,inventory_packet FROM owned_pets ORDER BY account,pet_id')]
  fixture=getattr(case,'case',case);hub=fixture.server.multi.team_arena
  battles=[{'owner':owner,'kind':battle.get('kind'),'loading':sorted(battle.get('arena')._loading.get(battle['room'].room_id,()))}
    for owner,battle in hub.battles.items()]
  results.append({'test':module+'.'+cls+'.'+method,'original_assertion_passed':error is None,
   'error':error,'authoritative_temporary_wallets':wallets,'authoritative_temporary_inventory_slots':inventory,
   'temporary_active_battles':battles,'temporary_pending_results':sorted(hub.results),
   'native_ping_barrier_after_assertion':sync})
 finally:
  case.tearDown();case.doCleanups()
print(json.dumps({'cases':results,'hosted_player_data_opened':False,'graphical_client_acceptance':False}))
'''


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--slots-only',action='store_true')
    parser.add_argument('--slots-sync',action='store_true')
    args=parser.parse_args()
    name='tcp-slot-sync-diagnosis.json' if args.slots_sync else 'tcp-slot-state-diagnosis.json' if args.slots_only else 'tcp-failure-state-diagnosis.json'
    target=BASE_FOLDER/name
    if target.exists():raise ValueError('Preserve earlier diagnostics')
    raw=(BASE_FOLDER/'test-bundle.tar.gz').read_bytes()
    env=dict(os.environ)
    for key in tuple(env):
        if any(word in key.upper() for word in ('TOKEN','SECRET','PASSWORD','STRIPE','SERVICE_KEY')):env.pop(key)
    with tempfile.TemporaryDirectory(prefix='tio-public-tcp-diagnosis-') as temporary:
        stage=Path(temporary);extract(raw,stage)
        python=Path(__file__).resolve().parents[1]/'data/registration-check-env/Scripts/python.exe'
        mode=['slots-sync'] if args.slots_sync else ['slots'] if args.slots_only else []
        completed=subprocess.run([str(python),'-X','utf8','-c',CHILD,*mode],cwd=stage,env=env,
            capture_output=True,text=True,encoding='utf-8',timeout=120)
        if completed.returncode:raise RuntimeError('Isolated diagnosis failed: '+completed.stderr[-2000:])
        result=json.loads(completed.stdout)
    result['public_test_bundle_sha256']=hashlib.sha256(raw).hexdigest()
    result['tool_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'cases':len(result['cases']),'assertion_results':[r['original_assertion_passed'] for r in result['cases']],
        'hosted_player_data_opened':False}))


if __name__=='__main__':main()
