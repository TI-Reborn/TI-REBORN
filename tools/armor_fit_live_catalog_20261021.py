"""Patch only item206 in the authoritative catalog sent by native B9.

The server supplies this XML afresh at login, superseding the on-disk client copy.
Inspect and back up the actual hosted XML; never replace it with the local catalog.
"""
import argparse,base64,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.deploy_stage4_economy import remote
from tools.armor_fit_fix_20261021 import OUT,patch
CODE=r'''
import base64,fcntl,hashlib,json,os,shutil,sqlite3,subprocess,sys,tarfile,tempfile
from contextlib import closing
from pathlib import Path
sys.path.insert(0,'/opt/tio-emulator')
from tio.rating_visibility import QA_LOGIN
from tio.protocol.item_list import decode_item_list
p=json.load(sys.stdin);path=Path('/opt/tio-emulator/evidence/items_diagnostic.xml');raw=path.read_bytes();sha=lambda b:hashlib.sha256(b).hexdigest()
def state():return subprocess.check_output(['systemctl','show','tio-server','-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True)
def protected():
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  db.execute('BEGIN');assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
  return {t:sha(repr(sorted(map(repr,db.execute('SELECT * FROM '+t).fetchall()))).encode()) for t in ('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')}
if p['mode']=='inspect':
 count=0
 with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
  for account,packet in db.execute('SELECT account,inventory_packet FROM owned_pets'):
   if not QA_LOGIN.fullmatch(account):count+=sum(i.template_id==206 and bool(i.equipped) for i in decode_item_list(packet)[1])
 print(json.dumps(dict(passed=True,xml=base64.b64encode(raw).decode(),sha256=sha(raw),ordinary_players_equipped_206=count,service=state())))
 sys.exit(0)
lock=open('/root/.tio-gameplay-client.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
before=base64.b64decode(p['before']);after=base64.b64decode(p['after']);assert raw==before
assert p['mode']=='stage';prior=protected();service=state();assert 'ActiveState=active' in service
backup=Path(tempfile.mkdtemp(prefix='tio-before-armor-catalog-',dir='/root'));backup.chmod(0o700);(backup/'items_diagnostic.xml').write_bytes(before)
shutil.copy2('/etc/tio-server/server.toml',backup/'server.toml');shutil.copy2('/etc/systemd/system/tio-server.service',backup/'tio-server.service')
with tarfile.open(backup/'previous-code-config.tar.gz','w:gz') as tar:
 for folder,pattern in (('tio','*.py'),('server','*.py'),('tools','*.py'),('config','*.json'),('evidence','*.xml')):
  for file in sorted((Path('/opt/tio-emulator')/folder).rglob(pattern)):tar.add(file,arcname=file.relative_to('/opt/tio-emulator').as_posix())
with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as src,closing(sqlite3.connect(backup/'reservation.sqlite3')) as dst:
 src.backup(dst);assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert path.read_bytes()==before and state()==service and protected()==prior
fd,name=tempfile.mkstemp(prefix='.armor-catalog-',dir=path.parent)
with os.fdopen(fd,'wb') as f:f.write(after);f.flush();os.fsync(f.fileno())
os.chmod(name,0o644);os.replace(name,path)
assert path.read_bytes()==after and protected()==prior and state()==service
print(json.dumps(dict(passed=True,backup=str(backup),before_sha256=sha(before),after_sha256=sha(after),service_unchanged=True,database_written=False,local_player_data_uploaded=False)))
'''
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('inspect','stage'));mode=parser.parse_args().mode
 if mode=='inspect':
  r=remote(CODE,dict(mode=mode));raw=base64.b64decode(r.pop('xml'));(OUT/'hosted-items-before.xml').write_bytes(raw);(OUT/'hosted-catalog-inspect.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
 else:
  before=(OUT/'hosted-items-before.xml').read_bytes();after=patch(before);info=json.loads((OUT/'hosted-catalog-inspect.json').read_text());assert info['ordinary_players_equipped_206']==0
  assert not (OUT/'hosted-catalog-fix.json').exists();r=remote(CODE,dict(mode=mode,before=base64.b64encode(before).decode(),after=base64.b64encode(after).decode()));(OUT/'hosted-items-fixed.xml').write_bytes(after);(OUT/'hosted-catalog-fix.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
