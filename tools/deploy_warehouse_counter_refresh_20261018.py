"""Validate the scoped native crest upload against actual hosted sources."""
import argparse,base64,hashlib,io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import SSH
OUT=ROOT/'reports/warehouse-counters-20261018';WORK=ROOT/'work/warehouse-counters-20261018'
REMOTE=r'''
import base64,hashlib,io,json,os,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
root=Path('/opt/tio-emulator');sha=lambda b:hashlib.sha256(b).hexdigest()
folder=Path('/root/warehouse-counters-20261018-refresh');folder.mkdir(exist_ok=True)
baseline={}
for name,entry in request['files'].items():
 assert (sha((root/name).read_bytes()) if (root/name).is_file() else None)==entry['before']
 assert sha(base64.b64decode(entry['raw']))==entry['after'];baseline[name]=entry['before']
(folder/'baseline.json').write_text(json.dumps(baseline))
if request['mode']=='validate':
 stage=Path(tempfile.mkdtemp(prefix='tio-warehouse-counters-check-',dir='/opt'))
 for n in ('server','tio','tools','config','evidence'):shutil.copytree(root/n,stage/n,ignore=shutil.ignore_patterns('__pycache__'))
 for name,entry in request['files'].items():(stage/name).write_bytes(base64.b64decode(entry['raw']))
 with tarfile.open(fileobj=io.BytesIO(base64.b64decode(request['tests']))) as tar:tar.extractall(stage,filter='data')
 run=subprocess.run([str(root/'.venv/bin/python'),'-m','unittest',*request['modules'],'-q'],cwd=stage,env={**os.environ,'PYTHONPATH':str(stage)+':'+str(stage/'tests')},capture_output=True,text=True,timeout=360)
 result=dict(passed=run.returncode==0,hashes={n:v['after'] for n,v in request['files'].items()},stage=str(stage),log=run.stdout+run.stderr,isolated_database=True)
 (folder/'validation.json').write_text(json.dumps(result));print(json.dumps(result))
else:
 validation=json.loads((folder/'validation.json').read_text());assert validation['passed'] and validation['hashes']=={n:v['after'] for n,v in request['files'].items()}
 manifest={n:dict(before=v['before'],after=v['after']) for n,v in request['files'].items()}
 with tarfile.open(folder/'patch.tar.gz','w:gz') as tar:
  for n,raw in [(n,base64.b64decode(v['raw'])) for n,v in request['files'].items()]+[('manifest.json',json.dumps(manifest).encode())]:
   entry=tarfile.TarInfo(n);entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
 sys.argv=['deployer','--archive',str(folder/'patch.tar.gz'),'--sha256',sha((folder/'patch.tar.gz').read_bytes()),'--baseline',str(folder/'baseline.json'),'--backup','/root/tio-before-game-operations-warehouse-counters-refresh-20261018','--scope','warehouse-counter-refresh']
 if request['maintenance_restart']:sys.argv.append('--maintenance-restart')
 exec(compile(request['deployer'],'warehouse-counters-scoped-deployer','exec'),{'__name__':'__main__'})
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('mode',choices=('validate','deploy'));p.add_argument('--maintenance-restart',action='store_true');args=p.parse_args()
 review=json.loads((OUT/'refresh-review.json').read_text());files={n:dict(before=v['before'],after=v['after'],raw=base64.b64encode((WORK/'candidate'/n).read_bytes()).decode()) for n,v in review.items()}
 request=dict(mode=args.mode,files=files,maintenance_restart=args.maintenance_restart,deployer=(ROOT/'tools/deploy_game_operations_remote.py').read_text())
 if args.mode=='validate':
  buf=io.BytesIO()
  with tarfile.open(fileobj=buf,mode='w:gz') as tar:
   tar.add(ROOT/'tests',arcname='tests',filter=lambda i:None if '__pycache__' in Path(i.name).parts else i)

  request.update(tests=base64.b64encode(buf.getvalue()).decode(),modules=['test_warehouse_resources', 'test_repair_warehouse_regression', 'test_wallets', 'test_bank_economy.EconomyTests.test_shared_stock_quote_no_instant_arbitrage_and_price_replay','test_bank_economy.EconomyTests.test_financial_failure_leaves_quote_holdings_and_wallet_unchanged', 'test_warehouse', 'test_warehouse_transfer', 'test_durability', 'test_clans.ClanTests.test_creation_level_names_and_unique_membership', 'test_clans.ClanTests.test_expired_invite_and_revoked_inviter_do_not_join', 'test_clans.ClanTests.test_rights_cannot_cross_clans_or_grant_leadership', 'test_clans.ClanTests.test_shared_items_remap_ids_and_conserve_metadata', 'test_clans.ClanTests.test_concurrent_withdrawals_cannot_duplicate_shared_item', 'test_clans.ClanTests.test_concurrent_treasury_withdrawals_and_overdraft', 'test_clans.ClanTests.test_asset_projection_clears_stale_funds_after_revocation_or_exit', 'test_clans.ClanTests.test_failed_audit_rolls_back_money_inventory_and_sequence', 'test_clans.ClanTests.test_leader_transfer_leave_and_empty_dissolution', 'test_clans.ClanTests.test_influence_and_upgrade_are_atomic_and_use_native_cost', 'test_clans.ClanTests.test_battle_settlement_does_not_repeat_clan_influence', 'test_clans.ClanTests.test_city_influence_reservation_zero_denver_one_and_replay', 'test_clans.ClanTests.test_service_rejects_mutation_in_battle_and_on_world_map', 'test_clans.ClanTests.test_safe_rejects_wrong_categories_and_preserves_upgrade_kits'])
 r=subprocess.run(SSH+['python3 -'],input='request='+repr(request)+'\n'+REMOTE,capture_output=True,encoding='utf-8',timeout=360)
 if r.returncode:raise RuntimeError(r.stderr[-1800:])
 value=json.loads(r.stdout);(OUT/('refresh-checks.json' if args.mode=='validate' else 'refresh-deployment.json')).write_text(json.dumps(value,indent=2));print(json.dumps({k:v for k,v in value.items() if k!='log'}))
if __name__=='__main__':main()
