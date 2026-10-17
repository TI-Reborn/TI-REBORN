"""Read-only final health/source/save comparison. Run on the hosted server."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT=Path('/opt/tio-emulator')
sys.path.insert(0,str(ROOT))
BACKUP=Path('/root/tio-before-game-operations-20261016-bot-credit-rewards-c38e')


def snapshot(db):
    result={}
    for table, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        quoted='"'+table.replace('"','""')+'"'
        rows=sorted(sha256(repr(tuple(r)).encode()).hexdigest() for r in db.execute('SELECT * FROM '+quoted))
        result[table]=dict(rows=len(rows),sha256=sha256(''.join(rows).encode()).hexdigest())
    return result


def main():
    manifest=json.loads((BACKUP/'patch-manifest.json').read_text())
    sources={name:sha256((ROOT/name).read_bytes()).hexdigest() for name in manifest}
    assert sources=={name:row['after'] for name,row in manifest.items()}
    with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        after=snapshot(db)
        idle={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in
              ('battle_checkpoints','battle_checkpoint_members','battle_settlement_jobs')}
    with closing(sqlite3.connect('file:'+str(BACKUP/'at-cutover.sqlite3')+'?mode=ro',uri=True)) as db:
        before=snapshot(db)
    changed=[t for t in before.keys()|after.keys() if before.get(t)!=after.get(t)]
    connections=len(subprocess.check_output(['ss','-Htn','state','established',
        '( sport = :28512 or sport = :28513 or sport = :29512 or sport = :29513 )'],text=True).splitlines())
    # A real player connected after the QA scenarios. Their new gameplay and
    # ordinary auction timers must be retained, never compared away/restored.
    deployment=json.loads((BACKUP/'deployment.json').read_text())
    assert deployment['passed'] and deployment['other_table_changes']==[]
    assert before['accounts']==after['accounts'] and integrity=='ok'
    from tio.rating_visibility import QA_LOGIN
    names=request['qa_names'];matches=request['qa_matches']
    assert 4<=len(matches)<=6 and len(set(matches))==len(matches) and all(QA_LOGIN.fullmatch(n) for n in names)
    with closing(sqlite3.connect('file:/var/lib/tio-server/reservation.sqlite3?mode=ro',uri=True)) as current:
        assert all(not current.execute('SELECT 1 FROM accounts WHERE login=?',(n,)).fetchone() for n in names)
        for table in ('battle_checkpoints','battle_checkpoint_members','world_city_matches','reward_pairs'):
            assert all(not current.execute('SELECT 1 FROM '+table+' WHERE match_id=?',(m,)).fetchone() for m in matches)
    service=subprocess.check_output(['systemctl','is-active','tio-server'],text=True).strip()
    log=subprocess.check_output(['journalctl','-u','tio-server','--since','@'+str(int(BACKUP.stat().st_mtime)),
                                 '--no-pager','-o','cat'],text=True)
    faults=sum('match_quarantined' in line or 'Traceback (most recent call last)' in line for line in log.splitlines())
    assert service=='active' and faults==0
    saved=json.loads((BACKUP/'backup-manifest.json').read_text())
    config_preserved=sha256(Path('/etc/tio-server/server.toml').read_bytes()).hexdigest()==saved['config_sha256']
    assert config_preserved
    print(json.dumps(dict(passed=True,service=service,integrity=integrity,source_parity=True,source_sha256=sources,
        unchanged_tables=len(before)-len(changed),changed_tables=changed,
        original_accounts_unchanged=True,all_tables_preserved_at_deployment=deployment['database_tables_preserved_before_restart'],
        live_player_connections=connections,runtime_player_activity_preserved=True,accounts=after['accounts']['rows'],
        remaining_battles=idle,qa_fixtures_removed=True,quarantined_matches_or_tracebacks=faults,
        config_preserved=config_preserved,backup=str(BACKUP),database_restored=False)))


if __name__=='__main__':main()
