"""Verify final service state and preserve hosted saves after session acceptance."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.inspect_training_base_20261018 import remote
OUT=ROOT/'reports/account-session-20261021'
lines=(OUT/'hosted-timed-check.log').read_text(encoding='utf-8-sig').splitlines()
timed=json.loads(lines[-1]);assert timed['passed'] and timed['elapsed_seconds']==310 and timed['website_users']==18
(OUT/'hosted-timed-check.json').write_text(json.dumps(timed,indent=2))
baseline=json.loads((OUT/'backup.json').read_text())['game_table_fingerprints']
tables=('accounts','characters','owned_pets','wallets','warehouse_items','clans','clan_members')
payload={name:baseline[name] for name in tables}
source='baseline='+repr(payload)+'\n'+r'''
import hashlib,json,sqlite3,subprocess,shutil,os
from pathlib import Path
assert str(Path('/opt/tio-portal/current').resolve())=='/opt/tio-portal/releases/tireborn-20261021-account-session'
db=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)
assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
for table,expected in baseline.items():
 columns=len(db.execute('pragma table_info('+table+')').fetchall());digest=hashlib.sha256();count=0
 for row in db.execute('select * from '+table+' order by '+','.join(str(i+1) for i in range(columns))):digest.update(repr(tuple(row)).encode('utf-8')+bytes([10]));count+=1
 assert dict(rows=count,sha256=digest.hexdigest())==expected,table
states={n:subprocess.check_output(['systemctl','show',n,'-p','MainPID','-p','NRestarts','-p','ActiveState'],text=True) for n in ('tio-server','tio-game-api','tio-portal')}
assert all('ActiveState=active' in s and 'NRestarts=0' in s for s in states.values())
assert 'MainPID=338357' in states['tio-server'] and 'MainPID=797' in states['tio-game-api']
code=subprocess.check_output(['curl','-sS','--max-time','20','-o','/dev/null','-w','%{http_code}','https://ti-reborn.com/ru'],text=True);assert code=='200'
archive=Path('/root/tio-account-session-20261021.tar.gz')
assert archive.is_file() and not archive.is_symlink()
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='5b19aba833f6ab9395edadcdacb6b484ebd063b4eb47faa929602893465d9bfd'
archive.unlink()
assert shutil.disk_usage('/').free>768*1024*1024
print(json.dumps(dict(passed=True,protected_game_tables_preserved=len(baseline),sqlite_integrity='ok',game_accounts=db.execute('select count(*) from accounts').fetchone()[0],services=states,website_http_status=200,only_own_uploaded_archive_removed=True,free_bytes=shutil.disk_usage('/').free)))
'''
r=remote(source);(OUT/'hosted-final.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
