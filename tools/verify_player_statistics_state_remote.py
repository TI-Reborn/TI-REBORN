"""Hosting-only persistence audit; refuses to interrupt active game clients."""
from pathlib import Path
from contextlib import closing
from collections import Counter
import json,sqlite3,subprocess

ROOT=Path('/opt/tio-emulator')
DB=Path('/var/lib/tio-server/reservation.sqlite3')
BACKUP=Path('/root/tio-before-player-statistics-9k6st2lp')

def command(*args):return subprocess.run(args,cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
def rows(path):
    with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name:Counter(repr(r) for r in db.execute('SELECT * FROM "'+name.replace('"','""')+'"')) for name in names}

def main():
    if command('ss','-Htn','state','established','( sport = :28512 or sport = :28513 )'):
        raise RuntimeError('Active gameplay connections; restart check postponed')
    prior=rows(BACKUP/'reservation.sqlite3');current=rows(DB)
    assert all(not (values-current.get(name,Counter())) for name,values in prior.items()),'Existing player data changed'
    command('systemctl','stop','tio-server')
    try:
        before=rows(DB)
    finally:command('systemctl','start','tio-server')
    assert command('systemctl','is-active','tio-server')=='active'
    assert rows(DB)==before,'Restart altered persisted data'
    with closing(sqlite3.connect(f'file:{DB}?mode=ro',uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        accounts=db.execute('SELECT account,seconds FROM player_online').fetchall()
        assert len(accounts)==2 and all(n>0 for _,n in accounts),accounts
        battles=db.execute('SELECT account,result,kills,deaths,damage_dealt,damage_received FROM player_battle_statistics').fetchall()
        assert len(battles)==2,battles
    result=dict(service='active',integrity='ok',original_tables_preserved=len(prior),
                restart_all_rows_identical=True,online=accounts,battles=battles)
    (BACKUP/'statistics-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
