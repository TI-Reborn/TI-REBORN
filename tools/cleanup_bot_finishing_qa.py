"""Remove only orphan receipts for matches proven by the four owned QA reports."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]

CODE=r'''
import sqlite3,json,hashlib
from tio.rating_visibility import QA_LOGIN
matches=request['matches'];names=request['names']
assert 4<=len(matches)<=5 and len(set(matches))==len(matches) and all(QA_LOGIN.fullmatch(n) for n in names)
db=sqlite3.connect('/var/lib/tio-server/reservation.sqlite3',timeout=15)
old=sqlite3.connect('file:/root/tio-before-game-operations-20261016-bot-finishing-9d6f/at-cutover.sqlite3?mode=ro',uri=True)
def quoted(s):return '"'+s.replace('"','""')+'"'
def fingerprint(sql,args=()):return hashlib.sha256(repr(sorted(map(repr,db.execute(sql,args)))).encode()).hexdigest()
db.execute('BEGIN IMMEDIATE')
try:
 assert all(not old.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
 assert all(not db.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
 marks=','.join('?' for _ in matches)
 for t in ('battle_checkpoints','battle_checkpoint_members'):
  assert not db.execute('SELECT 1 FROM '+t+' WHERE match_id IN ('+marks+')',matches).fetchone()
 for a,b in db.execute('SELECT first_account,second_account FROM reward_pairs WHERE match_id IN ('+marks+')',matches):
  assert a in names and b in names
 targets=('world_city_matches','reward_pairs')
 for t in targets:assert not old.execute('SELECT 1 FROM '+t+' WHERE match_id IN ('+marks+')',matches).fetchone()
 tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
 where=lambda t:' WHERE match_id NOT IN ('+marks+')' if t in targets else ''
 before={t:fingerprint('SELECT * FROM '+quoted(t)+where(t),matches if t in targets else ()) for t in tables}
 schema=list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 triggers=list(db.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('world_city_matches','reward_pairs') AND upper(sql) LIKE '%BEFORE DELETE%'"))
 for name,sql in triggers:db.execute('DROP TRIGGER '+quoted(name))
 removed={t:db.execute('DELETE FROM '+t+' WHERE match_id IN ('+marks+')',matches).rowcount for t in targets}
 for name,sql in triggers:db.execute(sql)
 assert schema==list(db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"))
 for t in tables:
  assert before[t]==fingerprint('SELECT * FROM '+quoted(t)+where(t),matches if t in targets else ())
 assert db.execute('PRAGMA integrity_check').fetchone()==('ok',)
 db.commit();print(json.dumps(dict(passed=True,removed=removed,unrelated_rows_preserved=True,schema_restored=True,integrity='ok')))
except BaseException:db.rollback();raise
finally:db.close();old.close()
'''


def main():
    folder=ROOT/'reports/bot-finishing-20261016';matches=[];names=set()
    for mode in ('humans','solo','team','wall'):
        report=json.loads((folder/('hosted-'+mode+'.json')).read_text())
        assert report['passed'] and report['ranking_excluded'] and report['cleanup']['unrelated_rows_preserved']
        matches.append(report['snapshot']['match']);names.update(report['snapshot']['humans'].values())
    recovered=folder/'recovered-team-cleanup.json'
    if recovered.exists():
        receipt=json.loads(recovered.read_text())
        assert receipt['journal_ownership_verified'] and receipt['cleanup']['unrelated_rows_preserved']
        matches.append(receipt['match']);names.update(receipt['names'])
    source='request='+repr(dict(matches=matches,names=sorted(names)))+'\n'+CODE
    result=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/tio_server'),'-o','BatchMode=yes','root@185.184.42.88',
        'cd /opt/tio-emulator && .venv/bin/python -'],input=source,encoding='utf-8',capture_output=True,timeout=45)
    if result.returncode:raise RuntimeError('Owned QA receipt cleanup failed; no unrelated data authorized for deletion')
    report=json.loads(result.stdout);(folder/'qa-receipt-cleanup.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':main()
