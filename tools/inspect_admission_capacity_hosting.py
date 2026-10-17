"""Read-only post-update source, service, database and preservation checks."""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'reports/stage2-admission-capacity'


def main():
    deployment=json.loads((FOLDER/'deployment.log').read_text(encoding='utf-8-sig').strip())
    expected=json.loads((FOLDER/'manifest.json').read_text())
    code='''import pathlib,sqlite3,json,sys,hashlib,subprocess,time
data=json.load(sys.stdin);root=pathlib.Path('/opt/tio-emulator')
backup=pathlib.Path(data['backup'])
if backup.parent!=pathlib.Path('/root') or not backup.name.startswith('tio-before-admission-capacity-'):raise ValueError('Unexpected backup path')
old=sqlite3.connect((backup/'reservation.sqlite3').as_uri()+'?mode=ro',uri=True)
live=sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True);live.execute('BEGIN')
def names(db):return [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
def records(db,table):return {repr(r) for r in db.execute('SELECT * FROM "'+table.replace('"','""')+'"')}
old_tables=names(old);lost={}
for name in old_tables:
 missing=records(old,name)-records(live,name)
 if missing:lost[name]=len(missing)
def run(args):
 p=subprocess.run(args,capture_output=True,text=True,check=True);return p.stdout.strip()
hashes={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in data['files']}
out=dict(timestamp_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
 service=run(['systemctl','show','tio-server','-p','ActiveState','-p','SubState','-p','NRestarts','-p','ExecMainStatus','-p','ActiveEnterTimestamp']),
 quick_check=live.execute('PRAGMA quick_check').fetchone()[0],
 accounts_before=old.execute('SELECT count(*) FROM accounts').fetchone()[0],
 accounts_after=live.execute('SELECT count(*) FROM accounts').fetchone()[0],
 existing_tables_checked=len(old_tables),missing_or_changed_old_rows=lost,
 pending_settlements=live.execute('SELECT count(*) FROM battle_settlement_jobs').fetchone()[0],
 unresolved_match_failures=live.execute('SELECT count(*) FROM battle_failure_audit WHERE resolved=0').fetchone()[0],
 source_hashes=hashes,source_parity=all(hashes[n]==h for n,h in data['files'].items()),
 listeners=run(['ss','-ltn','( sport = :28512 or sport = :28513 )']),
 journal=run(['journalctl','-u','tio-server','--since','10 minutes ago','-n','25','--no-pager']))
print(json.dumps(out))'''
    payload=dict(backup=deployment['backup'],files={n:h['after'] for n,h in expected.items()})
    completed=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes',
        'root@185.184.42.88','python3 -c '+shlex.quote(code)],input=json.dumps(payload),
        capture_output=True,text=True,encoding='utf-8',check=True,timeout=90)
    data=json.loads(completed.stdout)
    (FOLDER/'remote-after.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    safe=data['quick_check']=='ok' and data['source_parity'] and not data['missing_or_changed_old_rows']
    print(json.dumps({k:v for k,v in data.items() if k not in ('source_hashes','journal','listeners')},ensure_ascii=False,indent=2))
    if not safe:raise RuntimeError('Post-deployment preservation/source check failed')


if __name__=='__main__':main()
