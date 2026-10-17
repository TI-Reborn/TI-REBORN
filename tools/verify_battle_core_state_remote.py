"""Read-only hosted verification against the pre-update SQLite backup."""
from pathlib import Path
from contextlib import closing
from collections import Counter
import hashlib,json,sqlite3,subprocess,sys


def snapshot(path):
    with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {n:Counter(repr(r) for r in db.execute('SELECT * FROM "'+n.replace('"','""')+'"')) for n in tables}


def main():
    data=json.load(sys.stdin)
    before=snapshot(Path(data['backup'])/'reservation.sqlite3')
    after=snapshot('/var/lib/tio-server/reservation.sqlite3')
    assert all(not (rows-after.get(name,Counter())) for name,rows in before.items()),'Pre-existing data changed'
    for name,hashes in data['manifest'].items():
        assert hashlib.sha256((Path('/opt/tio-emulator')/name).read_bytes()).hexdigest()==hashes['after'],name
    services=subprocess.check_output(['systemctl','is-active','tio-server','tio-registration'],text=True).splitlines()
    assert services==['active','active']
    status=subprocess.check_output(['systemctl','show','tio-server','-p','NRestarts','-p','MainPID','-p','ActiveEnterTimestamp'],text=True)
    print(json.dumps({'passed':True,'existing_tables_preserved':len(before),
        'existing_rows_preserved':sum(sum(c.values()) for c in before.values()),
        'additional_accounts':sum(after['accounts'].values())-sum(before['accounts'].values()),
        'integrity':'ok','code_hashes_verified':len(data['manifest']),'services':services,'status':status},indent=2))


if __name__=='__main__':main()
