"""Validate and deploy only reviewed barter files over the inspected hosted code."""
import argparse,base64,hashlib,io,json,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.provision_user_test_accounts import remote
from tools.deploy_avatar_types import VALIDATE
FOLDER=ROOT/'reports/direct-trade-20261014'
NAMES=('tio/player_trade.py','tio/protocol/player_trade.py','server/player_trade.py','server/multi.py','tools/loopback_exchange.py','config/english_translations.json')
MODULES=('test_player_trade','test_player_trade_transport','test_private_market','test_mail','test_mail_service','test_item_stacking','test_warehouse_transfer','test_warehouse_completion','test_game_tls')

def inputs():
    return dict(expected={n:hashlib.sha256((FOLDER/'runtime'/n).read_bytes()).hexdigest() if (FOLDER/'runtime'/n).exists() else None for n in NAMES},
                sources={n:(FOLDER/'candidate'/n).read_text(encoding='utf-8') for n in NAMES})

DEPLOY=r'''
import json,sys,pathlib,hashlib,subprocess,sqlite3,os,shutil,time
from contextlib import closing
d=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator');dbpath=pathlib.Path('/var/lib/tio-server/reservation.sqlite3')
backup=pathlib.Path(d['backup'])
assert backup.is_dir() and str(backup).startswith('/root/tio-before-launcher-')
assert (backup/'game-code.tar.gz').is_file() and (backup/'operational-config.tar.gz').is_file()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def parity():
 for n,h in d['expected'].items():assert (sha(root/n) if (root/n).exists() else None)==h,'Hosted source changed: '+n
def idle():
 # A short, authorised deployment may disconnect idle city clients. Battles
 # must be absent before and after graceful shutdown; take the final backup
 # only after workers have saved their ordinary city state.
 with closing(sqlite3.connect(dbpath)) as db:
  for table in ('battle_checkpoints','battle_settlement_jobs'):assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,'Battle state present; defer deployment'
def rows():
 with closing(sqlite3.connect(dbpath)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
  return {t:hashlib.sha256(repr(sorted(map(repr,db.execute('SELECT * FROM "'+t.replace('"','""')+'"').fetchall()))).encode()).hexdigest() for t, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
def atomic(path,raw):
 tmp=path.with_name(path.name+'.trade-new')
 with tmp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 tmp.chmod(0o644);tmp.replace(path)
parity();idle()
undo=backup/'direct-trade-code';undo.mkdir(mode=0o700)
for n in d['sources']:
 if (root/n).exists():
  p=undo/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/n,p)
config=pathlib.Path('/etc/tio-server/server.toml')
config_hash=sha(config);client_manifest=pathlib.Path('/var/www/tio-client/updates/manifest.json');manifest_hash=sha(client_manifest)
subprocess.run(['systemctl','stop','tio-server'],check=True)
try:
 idle();parity()
 with closing(sqlite3.connect(dbpath)) as src,closing(sqlite3.connect(backup/'before-direct-trade.sqlite3')) as dst:src.backup(dst)
 (backup/'before-direct-trade.sqlite3').chmod(0o600);before=rows()
 for n,text in d['sources'].items():atomic(root/n,text.encode('utf-8'))
 result=subprocess.run(['runuser','-u','tio','--',str(root/'.venv/bin/python'),'-m','server','--config',str(config),'--check'],cwd=root,text=True,capture_output=True)
 assert result.returncode==0,'Server configuration check failed: '+result.stderr[-1500:]
 # Initialise only the new additive receipt schema, with the service stopped.
 subprocess.run(['runuser','-u','tio','--',str(root/'.venv/bin/python'),'-c','from tio.player_trade import TradeStore; TradeStore("'+str(dbpath)+'")'],cwd=root,check=True)
 after=rows();assert all(after[t]==h for t,h in before.items()),'Existing hosted rows changed'
 assert set(after)-set(before)=={'player_trade_receipts'}
 assert sha(config)==config_hash and sha(client_manifest)==manifest_hash
except BaseException:
 for n in d['sources']:
  if (undo/n).exists():atomic(root/n,(undo/n).read_bytes())
  else:(root/n).unlink(missing_ok=True)
 # Current hosted data is never rolled back or replaced.
 raise
finally:subprocess.run(['systemctl','start','tio-server'],check=True)
for _ in range(20):
 if subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active':break
 time.sleep(.25)
assert subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()=='active'
receipt=dict(passed=True,backup=str(backup),existing_tables_preserved=len(before),additive_tables=['player_trade_receipts'],client_manifest_preserved=True,configuration_preserved=True,service_restarts=1,local_player_data_used=False,files={n:sha(root/n) for n in d['sources']})
(backup/'direct-trade-deployment.json').write_text(json.dumps(receipt,indent=2));print(json.dumps(receipt))
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=('validate','check','deploy'));args=p.parse_args();data=inputs()
    if args.command=='validate':
        blob=io.BytesIO()
        with zipfile.ZipFile(blob,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in (ROOT/'tests').glob('*.py'):archive.write(path,'tests/'+path.name)
            for path in (ROOT/'tests/fixtures/game_tls').glob('*.pem'):
                archive.write(path,path.relative_to(ROOT).as_posix())
            for name in ('special_items_native.json','battle_item_native.json','battle_move_native.json','move_request_native.json'):
                archive.write(ROOT/'evidence'/name,'evidence/'+name)
        data.update(tests=base64.b64encode(blob.getvalue()).decode(),modules=MODULES)
        code=VALIDATE.split('result=subprocess.run(')[0].replace('tio-avatar-types-check-','tio-direct-trade-check-')+r'''
worker=stage/'worker.py'
worker.write_text("import json,pathlib,subprocess,os,re\ntry:\n r=subprocess.run("+repr([str(root/'.venv/bin/python'),'-m','unittest',*data['modules']])+",cwd="+repr(str(stage))+",capture_output=True,text=True,timeout=300,env={**os.environ,'PYTHONPATH':"+repr(str(stage)+':'+str(stage/'tests'))+"})\n failures=re.findall(r'^(?:FAIL|ERROR): (.+)$',r.stderr,re.M)\n baseline=subprocess.run("+repr([str(root/'.venv/bin/python'),'-m','unittest','test_item_stacking'])+",cwd="+repr(str(root))+",capture_output=True,text=True,timeout=120,env={**os.environ,'PYTHONPATH':"+repr(str(root)+':'+str(stage/'tests'))+"})\n previous=re.findall(r'^(?:FAIL|ERROR): (.+)$',baseline.stderr,re.M)\n out=dict(passed=(not failures or (set(failures)==set(previous) and all('test_item_stacking.' in f for f in failures))),candidate_returncode=r.returncode,output=r.stderr[-20000:],baseline_output=baseline.stderr[-15000:],unchanged_baseline_failures=previous,hosted_database_used=False)\nexcept Exception as e:\n out=dict(passed=False,error=type(e).__name__)\npathlib.Path("+repr(str(stage/'result.json'))+").write_text(json.dumps(out))\n")
subprocess.Popen([str(root/'.venv/bin/python'),str(worker)],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
print(json.dumps(dict(stage=str(stage),pending=True)))
'''
        result=remote(code,data);name='pending-tests.json'
    elif args.command=='check':
        result=remote("import json,sys,pathlib;d=json.load(sys.stdin);p=pathlib.Path(d['stage'])/'result.json';print(p.read_text() if p.exists() else json.dumps({'pending':True}))",json.loads((FOLDER/'pending-tests.json').read_text()))
        name='pending-check.json' if result.get('pending') else 'remote-tests.json'
    else:
        assert json.loads((FOLDER/'remote-tests.json').read_text())['passed']
        assert json.loads((FOLDER/'native-proof.json').read_text())['passed']
        backup=json.loads((FOLDER/'predeployment-backup.json').read_text())['backup'];data['backup']=backup
        result=remote(DEPLOY,data);name='deployment.json'
    (FOLDER/name).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
